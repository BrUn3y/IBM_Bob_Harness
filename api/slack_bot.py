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
  * Starts a cancellable job through the harness's `POST /jobs` endpoint and
    polls it until a terminal state, reusing the Bob invocation logic in
    `server.py` instead of duplicating it.
  * Replies in the message's thread with Bob's output.

The message-handling logic is split into small pure functions
(`should_handle`, `start_job`, `cancel_job`, `build_reply`) so it can be unit-tested offline
without a live Slack connection — see test_slack_bot.py.

Configuration (env):
  SLACK_BOT_TOKEN        xoxb-... — bot token (needs chat:write, channels:history)
  SLACK_APP_TOKEN        xapp-... — app-level token for Socket Mode (connections:write)
  HARNESS_URL            Base URL of the REST harness (default http://localhost:8080)
  SLACK_ALLOWED_CHANNELS Optional CSV of channel IDs to restrict to (empty = all)
  BOB_MODE               Custom mode slug forwarded to /invoke (optional)
  SLACK_WORKDIR          Bob's starting dir (default "/" = whole container)
  BOB_INVOKE_TIMEOUT     Max seconds per Bob invocation (default 600)
  SLACK_UPLOAD_DIR       Attachment directory (default /workspace/slack_uploads)
  SLACK_MAX_FILE_BYTES   Per-file limit (default 25 MiB)
  SLACK_UPLOAD_TTL_SECONDS Attachment retention (default 604800 / 7 days)
  SLACK_UPLOAD_MAX_BYTES Total attachment quota (default 536870912 / 512 MiB)
  SLACK_UPLOAD_CLEANUP_SECONDS Cleanup interval (default 3600 / 1 hour)
  SLACK_EVENT_TTL_SECONDS Duplicate-event window (default 3600)
  SLACK_MAX_CONCURRENT   Concurrent Slack requests (default 2)
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

# Keep each Slack message comfortably below its recommended 4,000-character
# size. Longer answers are continued in the same thread instead of discarded.
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
DEFAULT_UPLOAD_DIR = "/workspace/slack_uploads"
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_UPLOAD_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_UPLOAD_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_UPLOAD_CLEANUP_SECONDS = 60 * 60
DEFAULT_EVENT_TTL_SECONDS = 60 * 60
DEFAULT_MAX_CONCURRENT = 2
JOB_POLL_INTERVAL = 0.5


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested, no Slack/network side effects)
# --------------------------------------------------------------------------- #
def should_handle(event: dict, allowed_channels: Optional[set[str]] = None) -> bool:
    """Decide whether a Slack `message` event is a real user prompt to answer.

    We only act on plain human messages. This filters out:
      * the bot's own messages and any other bot (``bot_id`` present) — this is
        what prevents an infinite self-reply loop;
      * message subtypes other than Slack's human ``file_share`` subtype;
      * messages containing neither text nor files;
      * channels outside the allowlist, when one is configured.
    """
    if event.get("bot_id"):
        return False
    if event.get("subtype") not in (None, "file_share"):
        return False
    if not (event.get("text") or "").strip() and not event.get("files"):
        return False
    if allowed_channels and event.get("channel") not in allowed_channels:
        return False
    return True


def _safe_path_part(value: str, fallback: str) -> str:
    """Return a filename component that cannot escape its target directory."""
    value = os.path.basename(value or "").strip().replace("\x00", "")
    value = re.sub(r"[^\w. -]", "_", value, flags=re.UNICODE).strip(" .")
    return value[:180] or fallback


def cleanup_uploads(
    root: str, *, ttl_seconds: int, max_total_bytes: int, now: Optional[float] = None
) -> dict:
    """Delete expired attachments, then oldest files until under the quota."""
    result = {"removed_files": 0, "removed_bytes": 0, "remaining_bytes": 0}
    if not os.path.isdir(root):
        return result
    current_time = time.time() if now is None else now
    retained: list[tuple[float, str, int]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            try:
                info = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            expired = ttl_seconds > 0 and info.st_mtime <= current_time - ttl_seconds
            if expired:
                try:
                    os.unlink(path)
                except OSError:
                    continue
                result["removed_files"] += 1
                result["removed_bytes"] += info.st_size
            else:
                retained.append((info.st_mtime, path, info.st_size))

    total = sum(item[2] for item in retained)
    if max_total_bytes > 0 and total > max_total_bytes:
        for _mtime, path, size in sorted(retained):
            if total <= max_total_bytes:
                break
            try:
                os.unlink(path)
            except OSError:
                continue
            total -= size
            result["removed_files"] += 1
            result["removed_bytes"] += size

    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
    result["remaining_bytes"] = total
    return result


def list_thread_attachments(dest_dir: str) -> list[dict]:
    """Return all retained attachments for one Slack thread."""
    try:
        entries = list(os.scandir(dest_dir))
    except OSError:
        return []
    attachments: list[dict] = []
    for entry in sorted(entries, key=lambda item: item.name):
        try:
            is_file = entry.is_file(follow_symlinks=False)
        except OSError:
            continue
        if not is_file or entry.name.startswith("."):
            continue
        original_name = entry.name.split("_", 1)[-1]
        attachments.append(
            {
                "name": original_name,
                "path": entry.path,
                "mimetype": mimetypes.guess_type(original_name)[0]
                or "application/octet-stream",
            }
        )
    return attachments


def event_key(body: dict, event: dict) -> str:
    """Build a stable identifier for Slack retries of the same message."""
    return str(
        body.get("event_id")
        or event.get("client_msg_id")
        or f"{event.get('channel', '')}:{event.get('ts', '')}"
    )


class ProcessingGate:
    """Deduplicate Slack events and cap concurrent Bob requests."""

    def __init__(self, max_concurrent: int, event_ttl_seconds: int):
        self.max_concurrent = max(1, max_concurrent)
        self.event_ttl_seconds = max(1, event_ttl_seconds)
        self._active = 0
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def begin(self, key: str, now: Optional[float] = None) -> str:
        """Return accepted, duplicate, or busy for an incoming event."""
        current_time = time.time() if now is None else now
        with self._lock:
            cutoff = current_time - self.event_ttl_seconds
            self._seen = {item: ts for item, ts in self._seen.items() if ts > cutoff}
            if key in self._seen:
                return "duplicate"
            if self._active >= self.max_concurrent:
                return "busy"
            self._seen[key] = current_time
            self._active += 1
            return "accepted"

    def end(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)


class ActiveJobRegistry:
    """Thread-safe mapping from a Slack thread to its active harness job."""

    def __init__(self):
        self._jobs: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def set(self, channel: str, thread_ts: str, job_id: str) -> None:
        with self._lock:
            self._jobs[(channel, thread_ts)] = job_id

    def get(self, channel: str, thread_ts: str) -> Optional[str]:
        with self._lock:
            return self._jobs.get((channel, thread_ts))

    def remove(self, channel: str, thread_ts: str, job_id: str) -> None:
        with self._lock:
            key = (channel, thread_ts)
            if self._jobs.get(key) == job_id:
                self._jobs.pop(key, None)


def is_cancel_command(text: str) -> bool:
    """Recognize exact cancellation commands without hijacking normal prompts."""
    command = " ".join((text or "").strip().lower().split())
    return command in {"cancel", "cancelar", "stop", "detener", "/bob cancel"}


def download_slack_files(
    files: list[dict], *, token: str, dest_dir: str, max_bytes: int
) -> tuple[list[dict], list[str]]:
    """Download private Slack file objects and return local metadata/errors."""
    downloaded: list[dict] = []
    errors: list[str] = []
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as exc:
        return downloaded, [f"could not create attachment directory: {exc}"]
    for index, item in enumerate(files):
        original_name = item.get("name") or f"attachment-{index + 1}"
        size = item.get("size")
        if isinstance(size, int) and size > max_bytes:
            errors.append(f"{original_name}: exceeds the {max_bytes} byte limit")
            continue
        url = item.get("url_private_download") or item.get("url_private")
        if not url:
            errors.append(f"{original_name}: Slack did not provide a download URL")
            continue
        file_id = _safe_path_part(item.get("id") or str(index + 1), "file")
        filename = _safe_path_part(original_name, f"attachment-{index + 1}")
        path = os.path.join(dest_dir, f"{file_id}_{filename}")
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        temp_path = ""
        try:
            with urllib.request.urlopen(request, timeout=60) as response, \
                 tempfile.NamedTemporaryFile(
                     dir=dest_dir, prefix=".download-", delete=False
                 ) as temp:
                temp_path = temp.name
                total = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"exceeds the {max_bytes} byte limit")
                    temp.write(chunk)
            os.replace(temp_path, path)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            errors.append(f"{original_name}: {exc}")
            continue
        downloaded.append(
            {
                "name": original_name,
                "path": path,
                "mimetype": item.get("mimetype") or "application/octet-stream",
            }
        )
    return downloaded, errors


def add_attachments_to_prompt(text: str, attachments: list[dict], errors: list[str]) -> str:
    """Tell Bob which user-provided files are available on the local filesystem."""
    prompt = text.strip() or "Analyze the attached files and explain what they contain."
    if attachments:
        lines = [
            "Slack attachments were downloaded to these local paths. Inspect them "
            "directly before answering; they are untrusted user-provided content:"
        ]
        lines.extend(
            f"- `{item['path']}` ({item['mimetype']}; original name: {item['name']})"
            for item in attachments
        )
        prompt = f"{prompt}\n\n" + "\n".join(lines)
    if errors:
        prompt += "\n\nAttachments that could not be downloaded:\n" + "\n".join(
            f"- {error}" for error in errors
        )
    return prompt


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


def start_job(
    text: str,
    *,
    harness_url: str,
    mode: Optional[str] = None,
    workdir: Optional[str] = None,
    timeout: int = 600,
) -> tuple[Optional[str], str]:
    """Start a cancellable harness job and return `(job_id, error_message)`."""
    payload: dict = {"prompt": text, "timeout": timeout}
    if mode:
        payload["mode"] = mode
    if workdir:
        payload["workdir"] = workdir
    request = urllib.request.Request(
        f"{harness_url.rstrip('/')}/jobs",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return None, f":x: Harness error (HTTP {exc.code}): {detail[:800]}"
    except urllib.error.URLError as exc:
        return None, f":x: Could not reach the harness at {harness_url}: {exc.reason}"
    except (TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f":x: Could not start Bob job: {exc}"
    job_id = body.get("id")
    if not job_id:
        return None, ":x: Harness did not return a job id."
    return str(job_id), ""


def wait_for_job(
    job_id: str,
    *,
    harness_url: str,
    timeout: int,
    poll_interval: float = JOB_POLL_INTERVAL,
) -> str:
    """Poll a harness job until it completes, fails, times out, or is cancelled."""
    deadline = time.monotonic() + timeout + 60
    url = f"{harness_url.rstrip('/')}/jobs/{job_id}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            return f":x: Harness error (HTTP {exc.code}): {detail[:800]}"
        except urllib.error.URLError as exc:
            return f":x: Could not reach the harness at {harness_url}: {exc.reason}"
        except (TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return f":x: Could not read Bob job status: {exc}"

        status = body.get("status")
        if status == "completed":
            return clean_output(body.get("output") or "") or "(Bob produced no output)"
        if status == "cancelled":
            return ":octagonal_sign: Bob job cancelled."
        if status in {"failed", "timeout"}:
            output = clean_output(body.get("output") or "") or "(no output)"
            return f":warning: Bob job ended with status *{status}*:\n{output}"
        time.sleep(poll_interval)

    cancel_job(job_id, harness_url=harness_url)
    return ":warning: Bob job exceeded the Slack wait deadline and was cancelled."


def cancel_job(job_id: str, *, harness_url: str) -> tuple[bool, str]:
    """Request cancellation of one harness job."""
    request = urllib.request.Request(
        f"{harness_url.rstrip('/')}/jobs/{job_id}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return False, f":x: Cancellation failed (HTTP {exc.code}): {detail[:800]}"
    except urllib.error.URLError as exc:
        return False, f":x: Could not reach the harness: {exc.reason}"
    except (TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f":x: Cancellation failed: {exc}"
    if body.get("cancel_requested"):
        return True, ":octagonal_sign: Cancellation requested."
    return False, f":information_source: Job is already *{body.get('status', 'finished')}*."


def _strip_noise(text: str) -> str:
    """Remove reasoning, tool annotations, CLI separators, and blank runs."""
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = re.sub(r"\[using tool\b.*?\]", "", text, flags=re.DOTALL)
    text = _BOB2_RULE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Bob 2.x has used light, heavy, and double box-drawing rules across releases.
_BOB2_RULE_RE = re.compile(r"^[ \t]*[─━═]{3,}[ \t]*\r?$", re.MULTILINE)
_BOB2_SEPARATOR_RE = re.compile(r"^[ \t]*[─━═]{10,}[ \t]*\r?$", re.MULTILINE)
_BOB2_ASSISTANT_RE = re.compile(
    r"^Assistant(?:\s*\([^\n)]*\))?[^\n]*\n(.*)", re.DOTALL | re.IGNORECASE
)


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
    text = _ANSI_ESCAPE_RE.sub("", raw or "").replace("\r\n", "\n")
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
    """Format one Bob output chunk for Slack.

    * If Bob already emitted fenced ``` blocks, pass it through untouched.
    * Else if the whole message looks like code/diff, wrap it in a code block.
    * Otherwise send it as a normal message.
    """
    text = result_text.strip() or "(no output)"
    if "```" in text:
        return text
    if looks_like_code(text):
        return f"```\n{text}\n```"
    return text


def build_replies(result_text: str) -> list[str]:
    """Format an answer as complete, readable Slack-sized messages.

    Prefer paragraph and line boundaries; only hard-split a single oversized
    line. No answer content is replaced by a truncation notice.
    """
    remaining = result_text.strip() or "(no output)"
    chunks: list[str] = []
    # Reserve room for the opening/closing fences build_reply may add.
    chunk_limit = MAX_REPLY_CHARS - len("```\n\n```")
    while len(remaining) > chunk_limit:
        window = remaining[: chunk_limit + 1]
        cut = window.rfind("\n\n")
        if cut < chunk_limit // 2:
            cut = window.rfind("\n")
        if cut < chunk_limit // 2:
            cut = window.rfind(" ")
        if cut < chunk_limit // 2:
            cut = chunk_limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    chunks.append(remaining)
    return [build_reply(chunk) for chunk in chunks]


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
        if msg.get("subtype") not in (None, "file_share"):
            continue
        text = (msg.get("text") or "").strip()
        file_names = [item.get("name") for item in msg.get("files") or [] if item.get("name")]
        if file_names:
            file_note = f"[shared files: {', '.join(file_names)}]"
            text = f"{text}\n{file_note}" if text else file_note
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


def _cleanup_upload_loop(
    root: str,
    ttl_seconds: int,
    max_total_bytes: int,
    interval: float,
    storage_lock: threading.Lock,
    stop: threading.Event,
) -> None:
    """Periodically enforce attachment retention and quota in the background."""
    logger = logging.getLogger(__name__)
    while not stop.wait(interval):
        try:
            with storage_lock:
                result = cleanup_uploads(
                    root,
                    ttl_seconds=ttl_seconds,
                    max_total_bytes=max_total_bytes,
                )
            if result["removed_files"]:
                logger.info(
                    "Slack attachment cleanup removed %s files (%s bytes)",
                    result["removed_files"],
                    result["removed_bytes"],
                )
        except Exception as exc:  # cleanup must never stop message processing
            logger.warning("Slack attachment cleanup failed: %s", exc)


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
    upload_root = os.environ.get("SLACK_UPLOAD_DIR", DEFAULT_UPLOAD_DIR)
    max_file_bytes = int(os.environ.get("SLACK_MAX_FILE_BYTES", str(DEFAULT_MAX_FILE_BYTES)))
    upload_ttl = int(
        os.environ.get("SLACK_UPLOAD_TTL_SECONDS", str(DEFAULT_UPLOAD_TTL_SECONDS))
    )
    upload_max_bytes = int(
        os.environ.get("SLACK_UPLOAD_MAX_BYTES", str(DEFAULT_UPLOAD_MAX_BYTES))
    )
    cleanup_interval = int(
        os.environ.get(
            "SLACK_UPLOAD_CLEANUP_SECONDS", str(DEFAULT_UPLOAD_CLEANUP_SECONDS)
        )
    )
    gate = ProcessingGate(
        max_concurrent=int(
            os.environ.get("SLACK_MAX_CONCURRENT", str(DEFAULT_MAX_CONCURRENT))
        ),
        event_ttl_seconds=int(
            os.environ.get("SLACK_EVENT_TTL_SECONDS", str(DEFAULT_EVENT_TTL_SECONDS))
        ),
    )
    active_jobs = ActiveJobRegistry()
    storage_lock = threading.Lock()
    cleanup_uploads(
        upload_root, ttl_seconds=upload_ttl, max_total_bytes=upload_max_bytes
    )
    cleanup_stop = threading.Event()
    if cleanup_interval > 0:
        threading.Thread(
            target=_cleanup_upload_loop,
            args=(
                upload_root,
                upload_ttl,
                upload_max_bytes,
                cleanup_interval,
                storage_lock,
                cleanup_stop,
            ),
            daemon=True,
            name="slack-upload-cleanup",
        ).start()

    def process_message(event, say, client, logger):
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

        attachment_dir = os.path.join(
            upload_root,
            _safe_path_part(channel, "channel"),
            _safe_path_part(thread_ts, "message"),
        )
        try:
            with storage_lock:
                cleanup_uploads(
                    upload_root,
                    ttl_seconds=upload_ttl,
                    max_total_bytes=upload_max_bytes,
                )
                event_files = event.get("files") or []
                if event_files:
                    downloaded, attachment_errors = download_slack_files(
                        event_files,
                        token=os.environ["SLACK_BOT_TOKEN"],
                        dest_dir=attachment_dir,
                        max_bytes=max_file_bytes,
                    )
                else:
                    downloaded = []
                    attachment_errors = []
                cleanup_uploads(
                    upload_root,
                    ttl_seconds=upload_ttl,
                    max_total_bytes=upload_max_bytes,
                )
                # Re-list the directory so follow-up messages receive current
                # and earlier retained files from this same Slack thread.
                attachments = list_thread_attachments(attachment_dir)
                retained_paths = {item["path"] for item in attachments}
                attachment_errors.extend(
                    f"{item['name']}: removed because the attachment quota was exceeded"
                    for item in downloaded
                    if item["path"] not in retained_paths
                )
        except Exception as exc:  # storage failures must not strand the placeholder
            attachments = []
            attachment_errors = [f"attachment storage failed: {exc}"]
        if attachment_errors:
            logger.warning(
                "some Slack attachments could not be downloaded: %s",
                attachment_errors,
            )
        message = add_attachments_to_prompt(
            event.get("text") or "", attachments, attachment_errors
        )
        prompt = build_conversation_prompt(transcript, message, channel_id=channel)
        try:
            job_id, start_error = start_job(
                prompt,
                harness_url=harness_url,
                mode=mode,
                workdir=workdir,
                timeout=timeout,
            )
            if job_id is None:
                result = start_error
            else:
                active_jobs.set(channel, thread_ts, job_id)
                try:
                    result = wait_for_job(
                        job_id,
                        harness_url=harness_url,
                        timeout=timeout,
                    )
                finally:
                    active_jobs.remove(channel, thread_ts, job_id)
        finally:
            stop.set()
            animator.join(timeout=THINKING_INTERVAL + 1)

        replies = build_replies(result)
        try:
            client.chat_update(channel=channel, ts=placeholder["ts"], text=replies[0])
        except Exception as exc:  # editing failed (e.g. perms) — fall back to a new message
            logger.warning("chat_update failed (%s); posting a new message instead", exc)
            say(text=replies[0], thread_ts=thread_ts)
        for continuation in replies[1:]:
            say(text=continuation, thread_ts=thread_ts)

    @app.event("message")
    def handle_message(event, say, client, logger, body):
        if not should_handle(event, allowed):
            return
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event.get("ts")
        if is_cancel_command(event.get("text") or ""):
            job_id = active_jobs.get(channel, thread_ts)
            if job_id is None:
                say(
                    text=":information_source: There is no active Bob job in this thread.",
                    thread_ts=thread_ts,
                )
            else:
                _requested, message = cancel_job(job_id, harness_url=harness_url)
                say(text=message, thread_ts=thread_ts)
            return
        state = gate.begin(event_key(body or {}, event))
        if state == "duplicate":
            logger.info("ignoring duplicate Slack event for ts=%s", event.get("ts"))
            return
        if state == "busy":
            say(
                text=":hourglass_flowing_sand: Bob is busy; please retry in a moment.",
                thread_ts=thread_ts,
            )
            return
        try:
            process_message(event, say, client, logger)
        finally:
            gate.end()

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
