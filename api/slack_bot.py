"""Bidirectional Slack bot for the Bob Shell harness.

This is the conversational counterpart to the REST API in `server.py`. It runs
as a separate process (see the `slack-bot` service in docker-compose.yml) and
lets people talk to Bob in a Slack channel **without @-mentioning it**:

    user (in #some-channel):  refactor the auth module and add a test
    bob  (in-thread reply):   <Bob's output>

How it works:

  * Connects to Slack over **Socket Mode** (an outbound WebSocket), so the
    container never needs a public URL for Slack to reach.
  * Subscribes to plain `message` events in channels the bot is a member of
    (event `message.channels`) — no mention required.
  * Forwards the message text to the harness's own `POST /invoke` endpoint,
    reusing all of the `bob -p` invocation logic already in `server.py` instead
    of duplicating it.
  * Replies in the message's thread with Bob's output.

The message-handling logic is split into small pure functions
(`should_handle`, `run_prompt`, `build_reply`) so it can be unit-tested offline
without a live Slack connection — see test_slack_bot.py.

Configuration (env):
  SLACK_BOT_TOKEN        xoxb-... — bot token (needs chat:write, channels:history)
  SLACK_APP_TOKEN        xapp-... — app-level token for Socket Mode (connections:write)
  HARNESS_URL            Base URL of the REST harness (default http://localhost:8080)
  SLACK_ALLOWED_CHANNELS Optional CSV of channel IDs to restrict to (empty = all)
  BOB_MODE               Custom mode slug forwarded to /invoke (optional)
  SLACK_WORKDIR          Bob's starting dir (default "/" = whole container)
  BOB_INVOKE_TIMEOUT     Max seconds per Bob invocation (default 600)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from typing import Optional

# Very long Bob transcripts are noise in a channel — keep replies readable and
# let people re-run in a terminal for the full log.
MAX_REPLY_CHARS = 3500

# Bob's headless output carries reasoning + tooling noise around the actual
# answer. attempt_completion wraps the final answer between these markers.
_OUTPUT_MARKER = "---output---"

# Placeholders rotated in place while Bob works, so a long run visibly keeps
# "loading" instead of sitting on one static line that reads as stuck. The first
# entry is what we post immediately; a background thread cycles through the rest.
THINKING_PHRASES = [
    "_Bob is thinking…_",
    "_Bob is working on it…_",
    "_Still crunching…_",
    "_Hang tight, this one's bigger…_",
    "_Bob is still on it…_",
    "_Almost there…_",
]
# Back-compat: the initial placeholder and the historical single-phrase value.
THINKING_TEXT = THINKING_PHRASES[0]

# Seconds between placeholder edits. A run shorter than this never gets rotated
# (no flicker); a max-length 600s run is ~120 edits of one message — comfortably
# within chat.update rate limits for a single channel.
THINKING_INTERVAL = int(os.environ.get("SLACK_THINKING_INTERVAL", "5"))


def thinking_phrase(tick: int) -> str:
    """Return the placeholder text for animation step `tick` (round-robin)."""
    return THINKING_PHRASES[tick % len(THINKING_PHRASES)]


def is_thinking_text(text: str) -> bool:
    """True if `text` is one of our placeholder phrases (any rotation step).

    Used to skip an in-flight placeholder when rebuilding thread context, so a
    concurrent run's rotating message never leaks into Bob's prompt.
    """
    return (text or "").strip() in THINKING_PHRASES

# Thread-context limits: how many prior messages to feed back, and a per-message
# cap so one huge paste can't blow up the prompt.
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_MSG_CHARS = 1500


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested, no Slack/network side effects)
# --------------------------------------------------------------------------- #
def should_handle(event: dict, allowed_channels: Optional[set[str]] = None) -> bool:
    """Decide whether a Slack `message` event is a real user prompt to answer.

    We only act on plain human messages. This filters out:
      * the bot's own messages and any other bot (``bot_id`` present) — this is
        what prevents an infinite self-reply loop;
      * message subtypes (edits, joins, channel_topic, thread broadcasts, ...),
        which carry a ``subtype`` field;
      * empty / textless messages;
      * channels outside the allowlist, when one is configured.
    """
    if event.get("bot_id"):
        return False
    if event.get("subtype"):
        return False
    if not (event.get("text") or "").strip():
        return False
    if allowed_channels and event.get("channel") not in allowed_channels:
        return False
    return True


def run_prompt(
    text: str,
    *,
    harness_url: str,
    mode: Optional[str] = None,
    workdir: Optional[str] = None,
    timeout: int = 600,
) -> str:
    """Send `text` to the harness `POST /invoke` and return a human-readable result.

    Reuses the REST harness rather than shelling out to `bob` directly, so the
    Slack bot stays a thin client. `workdir` sets Bob's starting directory, which
    scopes its file tools (use "/" to reach the whole container). Network/HTTP
    failures are turned into a short message suitable for posting back to the
    channel (we never raise).
    """
    payload: dict = {"prompt": text}
    if mode:
        payload["mode"] = mode
    if workdir:
        payload["workdir"] = workdir
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{harness_url.rstrip('/')}/invoke",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return f":x: Harness error (HTTP {exc.code}): {detail[:800]}"
    except urllib.error.URLError as exc:
        return f":x: Could not reach the harness at {harness_url}: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return f":x: Request to the harness failed: {exc}"

    output = (body.get("output") or "").strip()
    if not body.get("ok", False):
        err = (body.get("error") or "").strip()
        tail = clean_output(err or output) or "(no output)"
        return f":warning: Bob exited with code {body.get('exit_code')}:\n{tail}"
    return clean_output(output) or "(Bob produced no output)"


def _strip_noise(text: str) -> str:
    """Remove <thinking> blocks, [using tool ...] annotations, and blank runs."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = re.sub(r"\[using tool\b.*?\]", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_BOB2_SEPARATOR_RE = re.compile(r"\n[──]{20,}\n")
_BOB2_ASSISTANT_RE = re.compile(r"^Assistant\s*\(\d+\)[^\n]*\n(.*)", re.DOTALL)


def _extract_bob2_answer(text: str) -> str:
    """Extract the last assistant reply from a bob 2.x separator-delimited transcript."""
    for segment in reversed(_BOB2_SEPARATOR_RE.split(text)):
        m = _BOB2_ASSISTANT_RE.match(segment.strip())
        if m:
            return m.group(1).strip()
    return ""


def clean_output(raw: str) -> str:
    """Extract Bob's final answer from its headless transcript.

    bob 2.x: separator-delimited transcript — extract the last Assistant block.
    bob 1.x: ``---output---`` markers — return the last non-empty block.
    Fallback: strip noise from the whole output.
    """
    text = raw or ""
    if _BOB2_SEPARATOR_RE.search(text):
        answer = _extract_bob2_answer(text)
        if answer:
            return _strip_noise(answer)
    if _OUTPUT_MARKER in text:
        for segment in reversed(text.split(_OUTPUT_MARKER)):
            cleaned = _strip_noise(segment)
            if cleaned:
                return cleaned
    return _strip_noise(text)


# Unambiguous "this is code/patch" signals: diff/patch headers and shebangs.
_CODE_STRONG_RE = re.compile(r"^(---|\+\+\+|@@|diff --git|Index:|#!)")
# Weaker per-line code signals; used with a majority vote. NOTE: we deliberately
# do NOT treat a leading "- " / "+ " as a code signal — those are far more often
# Markdown/plain bullet markers (which Slack renders fine as a normal message)
# than diff lines. Real diffs are caught by _CODE_STRONG_RE (---, +++, @@, ...).
_CODE_WEAK_RE = re.compile(
    r"^(\s{2,}|\t|def |class |import |from \S+ import |function |const |let |var |"
    r"public |private |#include|<\?php|package |func |return |[{}();])"
)


def looks_like_code(text: str) -> bool:
    """Heuristic: is this whole message code/diff (so it should be monospaced)?"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    if any(_CODE_STRONG_RE.match(ln) for ln in lines):
        return True
    codey = sum(1 for ln in lines if _CODE_WEAK_RE.match(ln))
    return codey >= max(2, (len(lines) + 1) // 2)


def build_reply(result_text: str) -> str:
    """Format Bob's output for Slack: plain text, but code/diffs in a code block.

    * If Bob already emitted fenced ``` blocks, pass it through untouched.
    * Else if the whole message looks like code/diff, wrap it in a code block.
    * Otherwise send it as a normal message.
    """
    text = result_text.strip() or "(no output)"
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS] + "\n… (output truncated)"
    if "```" in text:
        return text
    if looks_like_code(text):
        return f"```\n{text}\n```"
    return text


def format_thread(messages: list[dict], current_ts: Optional[str] = None) -> str:
    """Turn a Slack thread's messages into a User/Assistant transcript.

    `messages` is the raw list from `conversations.replies` (chronological). The
    current message (`current_ts`), the "thinking" placeholder, and empty/other
    subtype messages are skipped. Bot messages are labelled ``Assistant``, human
    messages ``User``. Only the last MAX_HISTORY_MESSAGES are kept.
    """
    lines: list[str] = []
    for msg in messages:
        if current_ts and msg.get("ts") == current_ts:
            continue
        if msg.get("subtype"):  # joins, topic changes, etc.
            continue
        text = (msg.get("text") or "").strip()
        if not text or is_thinking_text(text):
            continue
        role = "Assistant" if msg.get("bot_id") else "User"
        if len(text) > MAX_HISTORY_MSG_CHARS:
            text = text[:MAX_HISTORY_MSG_CHARS] + " …"
        lines.append(f"{role}: {text}")
    return "\n".join(lines[-MAX_HISTORY_MESSAGES:])


# Steer Bob to answer with actual results instead of a bare summary/count, and
# to enumerate fully when a directory listing could be truncated.
_ANSWER_GUIDANCE = (
    "Answer guidance: when the user asks to list files or show file/command "
    "output, put the ACTUAL results in your final answer (file names, full "
    'contents, or command output) — never reply with only a count like "Listed '
    'N items". If a directory listing could be truncated, run a shell command '
    "such as `ls -la` to enumerate everything and include that output."
)


def build_conversation_prompt(
    transcript: str, text: str, channel_id: Optional[str] = None
) -> str:
    """Build Bob's prompt: answer guidance + optional thread context + message.

    With no prior history it's the guidance plus the message. With history, Bob
    is also given the conversation so it can answer with continuity (files it
    created, prior decisions, language, etc.). `channel_id`, when given, is
    surfaced so Bob can target *this* channel when scheduling recurring tasks.
    """
    ctx = _ANSWER_GUIDANCE
    if channel_id:
        ctx += (
            f"\n\nSlack context: this conversation is in channel `{channel_id}`. "
            "If the user asks to schedule a recurring task that should post its "
            'results back here, set the schedule\'s "channel" to this id.'
        )
    if not transcript.strip():
        return f"{ctx}\n\n{text}"
    return (
        f"{ctx}\n\n"
        "You are continuing a Slack conversation. Here is the conversation so "
        "far (oldest first):\n\n"
        f"{transcript}\n\n"
        "Respond to the latest user message, keeping the above context in mind "
        "(files you already created, prior decisions, and the user's language):\n\n"
        f"User: {text}"
    )


# --------------------------------------------------------------------------- #
# Outbound posting (used by the scheduler to deliver run results to a channel)
# --------------------------------------------------------------------------- #
def post_message(
    channel: str,
    text: str,
    *,
    token: Optional[str] = None,
    thread_ts: Optional[str] = None,
) -> tuple[bool, str]:
    """Post `text` to a Slack `channel` via the Web API (chat.postMessage).

    Uses the bot token (arg or ``SLACK_BOT_TOKEN`` env). This is a thin urllib
    call — no slack_bolt needed — so the API process can deliver scheduled run
    results without holding a Socket Mode connection. Returns (ok, error).
    """
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return False, "SLACK_BOT_TOKEN not set"
    if not channel:
        return False, "no channel"
    payload: dict = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)
    return bool(body.get("ok")), body.get("error", "")


# --------------------------------------------------------------------------- #
# Slack wiring
# --------------------------------------------------------------------------- #
def _parse_allowed(raw: Optional[str]) -> Optional[set[str]]:
    if not raw:
        return None
    channels = {c.strip() for c in raw.split(",") if c.strip()}
    return channels or None


def _animate_thinking(client, channel, ts, stop, interval, logger) -> None:
    """Rotate the placeholder text every `interval`s until `stop` is set.

    Runs on a daemon thread while the handler blocks on run_prompt(). Sleeps
    first (via stop.wait), so a run shorter than `interval` gets no edit at all
    — no flicker. Best-effort: a failed chat_update (rate limit, transient) is
    logged and the loop continues; it never raises.
    """
    tick = 1
    while not stop.wait(interval):
        try:
            client.chat_update(channel=channel, ts=ts, text=thinking_phrase(tick))
        except Exception as exc:  # noqa: BLE001 - keep animating on any API hiccup
            logger.warning("thinking animation update failed: %s", exc)
        tick += 1


def create_app():
    """Build and return a configured slack_bolt App (imported lazily)."""
    from slack_bolt import App

    # Socket Mode authenticates via the app-level token, not the HTTP signing
    # secret — disable request verification so no signing_secret is required.
    app = App(
        token=os.environ["SLACK_BOT_TOKEN"],
        signing_secret=None,
        request_verification_enabled=False,
    )

    harness_url = os.environ.get("HARNESS_URL", "http://localhost:8080")
    mode = os.environ.get("BOB_MODE") or None
    # Start Bob at "/" so its file tools can reach the whole container (its shell
    # already could). Override with SLACK_WORKDIR to scope it back (e.g. /workspace).
    workdir = os.environ.get("SLACK_WORKDIR", "/")
    timeout = int(os.environ.get("BOB_INVOKE_TIMEOUT", "600"))
    allowed = _parse_allowed(os.environ.get("SLACK_ALLOWED_CHANNELS"))

    @app.event("message")
    def handle_message(event, say, client, logger):
        if not should_handle(event, allowed):
            return
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event.get("ts")
        logger.info("Bob prompt from channel=%s user=%s", channel, event.get("user"))

        # Give Bob memory of the thread: pull prior messages and feed them back
        # as context. New (non-threaded) messages just get themselves. Fetch
        # BEFORE posting the placeholder so it isn't part of the transcript.
        transcript = ""
        try:
            replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=100)
            transcript = format_thread(replies.get("messages", []), current_ts=event.get("ts"))
        except Exception as exc:
            logger.warning("could not fetch thread history (%s); answering statelessly", exc)

        # There is no native "typing…" indicator for channel bots (the old RTM
        # user_typing API is gone), so we post a placeholder and edit it in place
        # once Bob is done — same felt experience, only chat:write needed. While
        # Bob works (run_prompt blocks), a background thread rotates the
        # placeholder text so a long run visibly keeps loading instead of
        # looking stuck. We stop and join it BEFORE the final edit so the answer
        # always wins the race with the animator.
        placeholder = say(text=THINKING_PHRASES[0], thread_ts=thread_ts)
        stop = threading.Event()
        animator = threading.Thread(
            target=_animate_thinking,
            args=(client, channel, placeholder["ts"], stop, THINKING_INTERVAL, logger),
            daemon=True,
        )
        animator.start()

        prompt = build_conversation_prompt(transcript, event["text"], channel_id=channel)
        try:
            result = run_prompt(prompt, harness_url=harness_url, mode=mode, workdir=workdir, timeout=timeout)
        finally:
            stop.set()
            animator.join(timeout=THINKING_INTERVAL + 1)

        reply = build_reply(result)
        try:
            client.chat_update(channel=channel, ts=placeholder["ts"], text=reply)
        except Exception as exc:  # editing failed (e.g. perms) — fall back to a new message
            logger.warning("chat_update failed (%s); posting a new message instead", exc)
            say(text=reply, thread_ts=thread_ts)

    return app


def main() -> None:
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    # Surface slack_bolt's INFO logs (connection established, event handling)
    # to stdout so `docker/podman logs` shows the bot's status.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    for var in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
        if not os.environ.get(var):
            raise SystemExit(f"ERROR: {var} is not set (required for the Slack bot).")

    app = create_app()
    print(
        "Bob Slack bot: connecting via Socket Mode "
        f"(harness={os.environ.get('HARNESS_URL', 'http://localhost:8080')})"
    )
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
