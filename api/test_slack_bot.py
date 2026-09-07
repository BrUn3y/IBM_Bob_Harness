"""Unit tests for the Slack bot's pure logic.

These never open a Slack connection or hit the network: `urllib.request.urlopen`
is mocked, so they run fast and offline (same discipline as test_server.py).
"""
import io
import json
import logging
import os
import threading
import time
import urllib.error
from unittest.mock import patch

import slack_bot


# --------------------------------------------------------------------------- #
# should_handle
# --------------------------------------------------------------------------- #
def test_should_handle_accepts_plain_user_message():
    assert slack_bot.should_handle({"text": "hola bob", "channel": "C1", "user": "U1"})


def test_should_handle_rejects_bot_messages():
    # This is the anti-loop guard: the bot's own posts carry a bot_id.
    assert not slack_bot.should_handle({"text": "hi", "bot_id": "B1"})


def test_should_handle_rejects_subtypes():
    assert not slack_bot.should_handle({"text": "x", "subtype": "message_changed"})


def test_should_handle_rejects_empty_text():
    assert not slack_bot.should_handle({"text": "   ", "channel": "C1"})
    assert not slack_bot.should_handle({"channel": "C1"})


def test_should_handle_accepts_file_only_message():
    event = {
        "subtype": "file_share",
        "files": [{"id": "F1", "name": "photo.png"}],
        "channel": "C1",
        "user": "U1",
    }
    assert slack_bot.should_handle(event)


def test_should_handle_respects_allowlist():
    ev = {"text": "hi", "channel": "C_OTHER"}
    assert not slack_bot.should_handle(ev, allowed_channels={"C_OK"})
    assert slack_bot.should_handle({"text": "hi", "channel": "C_OK"}, allowed_channels={"C_OK"})


def test_parse_allowed():
    assert slack_bot._parse_allowed(None) is None
    assert slack_bot._parse_allowed("") is None
    assert slack_bot._parse_allowed(" C1 , C2 ,") == {"C1", "C2"}


# --------------------------------------------------------------------------- #
# Slack attachments
# --------------------------------------------------------------------------- #
def test_download_slack_file_uses_auth_and_safe_name(tmp_path):
    captured = {}

    class FileResponse:
        def __init__(self):
            self.stream = io.BytesIO(b"image-bytes")

        def read(self, size=-1):
            return self.stream.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["auth"] = request.headers.get("Authorization")
        captured["url"] = request.full_url
        return FileResponse()

    files = [{
        "id": "F123",
        "name": "../../photo.png",
        "mimetype": "image/png",
        "size": 11,
        "url_private_download": "https://files.slack.test/photo",
    }]
    with patch.object(slack_bot.urllib.request, "urlopen", side_effect=fake_urlopen):
        downloaded, errors = slack_bot.download_slack_files(
            files, token="xoxb-secret", dest_dir=str(tmp_path), max_bytes=100
        )

    assert errors == []
    assert captured == {
        "auth": "Bearer xoxb-secret",
        "url": "https://files.slack.test/photo",
    }
    assert downloaded[0]["path"] == str(tmp_path / "F123_photo.png")
    assert (tmp_path / "F123_photo.png").read_bytes() == b"image-bytes"


def test_download_slack_file_rejects_oversize_without_network(tmp_path):
    files = [{"name": "large.pdf", "size": 101, "url_private": "https://files/x"}]
    with patch.object(slack_bot.urllib.request, "urlopen") as urlopen:
        downloaded, errors = slack_bot.download_slack_files(
            files, token="x", dest_dir=str(tmp_path), max_bytes=100
        )
    assert downloaded == []
    assert "exceeds" in errors[0]
    urlopen.assert_not_called()


def test_add_attachments_to_prompt_includes_local_path_and_default_request():
    prompt = slack_bot.add_attachments_to_prompt(
        "",
        [{"path": "/workspace/slack_uploads/F1_photo.png", "name": "photo.png", "mimetype": "image/png"}],
        [],
    )
    assert "Analyze the attached files" in prompt
    assert "/workspace/slack_uploads/F1_photo.png" in prompt
    assert "untrusted user-provided content" in prompt


def test_cleanup_uploads_applies_ttl_then_total_quota(tmp_path):
    now = 1_000_000
    old = tmp_path / "C1" / "T1" / "F1_old.txt"
    quota_old = tmp_path / "C1" / "T2" / "F2_middle.txt"
    newest = tmp_path / "C1" / "T3" / "F3_new.txt"
    for path, content, modified in (
        (old, b"x" * 10, now - 200),
        (quota_old, b"y" * 8, now - 20),
        (newest, b"z" * 8, now - 10),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (modified, modified))

    result = slack_bot.cleanup_uploads(
        str(tmp_path), ttl_seconds=100, max_total_bytes=10, now=now
    )

    assert not old.exists()
    assert not quota_old.exists()
    assert newest.exists()
    assert result == {"removed_files": 2, "removed_bytes": 18, "remaining_bytes": 8}


def test_cleanup_upload_loop_runs_periodically_and_stops(tmp_path):
    expired = tmp_path / "expired.txt"
    expired.write_text("old")
    os.utime(expired, (1, 1))
    stop = threading.Event()
    worker = threading.Thread(
        target=slack_bot._cleanup_upload_loop,
        args=(str(tmp_path), 1, 1024, 0.01, threading.Lock(), stop),
    )
    worker.start()
    for _ in range(50):
        if not expired.exists():
            break
        time.sleep(0.01)
    stop.set()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert not expired.exists()


def test_list_thread_attachments_restores_prior_files(tmp_path):
    first = tmp_path / "F1_photo.png"
    second = tmp_path / "F2_notes.txt"
    hidden = tmp_path / ".download-partial"
    first.write_bytes(b"png")
    second.write_text("notes")
    hidden.write_bytes(b"partial")

    attachments = slack_bot.list_thread_attachments(str(tmp_path))

    assert [item["name"] for item in attachments] == ["photo.png", "notes.txt"]
    assert attachments[0]["mimetype"] == "image/png"
    prompt = slack_bot.add_attachments_to_prompt("¿qué dice la imagen anterior?", attachments, [])
    assert str(first) in prompt and str(second) in prompt


def test_processing_gate_deduplicates_and_limits_concurrency():
    gate = slack_bot.ProcessingGate(max_concurrent=1, event_ttl_seconds=10)
    assert gate.begin("E1", now=100) == "accepted"
    assert gate.begin("E1", now=101) == "duplicate"
    assert gate.begin("E2", now=101) == "busy"
    gate.end()
    assert gate.begin("E2", now=102) == "accepted"
    gate.end()
    assert gate.begin("E1", now=111) == "accepted"
    gate.end()


def test_event_key_prefers_event_id_then_client_message_id():
    event = {"client_msg_id": "M1", "channel": "C1", "ts": "123.4"}
    assert slack_bot.event_key({"event_id": "E1"}, event) == "E1"
    assert slack_bot.event_key({}, event) == "M1"
    assert slack_bot.event_key({}, {"channel": "C1", "ts": "123.4"}) == "C1:123.4"


# --------------------------------------------------------------------------- #
# run_prompt
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body: dict):
        self._data = json.dumps(body).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_run_prompt_returns_output_on_success():
    resp = _FakeResp({"ok": True, "exit_code": 0, "output": "done!"})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=resp) as urlopen:
        out = slack_bot.run_prompt("do it", harness_url="http://h:8080", mode="reviewer")

    assert out == "done!"
    # POSTs JSON to /invoke with the prompt and forwarded mode.
    req = urlopen.call_args.args[0]
    assert req.full_url == "http://h:8080/invoke"
    assert json.loads(req.data.decode()) == {"prompt": "do it", "mode": "reviewer"}


def test_run_prompt_forwards_workdir():
    resp = _FakeResp({"ok": True, "exit_code": 0, "output": "ok"})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=resp) as urlopen:
        slack_bot.run_prompt("x", harness_url="http://h:8080", workdir="/")
    assert json.loads(urlopen.call_args.args[0].data.decode())["workdir"] == "/"


def test_run_prompt_reports_bob_failure():
    resp = _FakeResp({"ok": False, "exit_code": 2, "output": "", "error": "boom"})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=resp):
        out = slack_bot.run_prompt("x", harness_url="http://h:8080")
    assert "code 2" in out and "boom" in out


def test_run_prompt_handles_http_error():
    err = urllib.error.HTTPError(
        url="http://h:8080/invoke", code=500, msg="err", hdrs=None,
        fp=io.BytesIO(b"kaboom"),
    )
    with patch.object(slack_bot.urllib.request, "urlopen", side_effect=err):
        out = slack_bot.run_prompt("x", harness_url="http://h:8080")
    assert "HTTP 500" in out and "kaboom" in out


def test_run_prompt_handles_unreachable_harness():
    err = urllib.error.URLError("connection refused")
    with patch.object(slack_bot.urllib.request, "urlopen", side_effect=err):
        out = slack_bot.run_prompt("x", harness_url="http://h:8080")
    assert "Could not reach the harness" in out


# --------------------------------------------------------------------------- #
# Cancellable harness jobs
# --------------------------------------------------------------------------- #
def test_start_job_posts_async_request():
    response = _FakeResp({"id": "job123", "status": "pending"})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=response) as urlopen:
        job_id, error = slack_bot.start_job(
            "do it", harness_url="http://h:8080", mode="reviewer", workdir="/", timeout=42
        )
    request = urlopen.call_args.args[0]
    assert job_id == "job123" and error == ""
    assert request.full_url == "http://h:8080/jobs"
    assert request.method == "POST"
    assert json.loads(request.data.decode()) == {
        "prompt": "do it",
        "timeout": 42,
        "mode": "reviewer",
        "workdir": "/",
    }


def test_wait_for_job_returns_clean_completed_output():
    responses = [
        _FakeResp({"id": "job123", "status": "running", "output": ""}),
        _FakeResp({"id": "job123", "status": "completed", "output": "---output---\ndone\n---output---"}),
    ]
    with patch.object(slack_bot.urllib.request, "urlopen", side_effect=responses), \
         patch.object(slack_bot.time, "sleep"):
        result = slack_bot.wait_for_job(
            "job123", harness_url="http://h:8080", timeout=10, poll_interval=0
        )
    assert result == "done"


def test_wait_for_job_reports_cancelled():
    response = _FakeResp({"id": "job123", "status": "cancelled", "output": ""})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=response):
        result = slack_bot.wait_for_job("job123", harness_url="http://h:8080", timeout=10)
    assert "cancelled" in result


def test_cancel_job_sends_delete():
    response = _FakeResp({"id": "job123", "status": "cancelling", "cancel_requested": True})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=response) as urlopen:
        requested, message = slack_bot.cancel_job("job123", harness_url="http://h:8080")
    request = urlopen.call_args.args[0]
    assert requested is True and "requested" in message
    assert request.full_url == "http://h:8080/jobs/job123"
    assert request.method == "DELETE"


def test_cancel_commands_and_active_job_registry():
    assert slack_bot.is_cancel_command("  CANCELAR ")
    assert slack_bot.is_cancel_command("/bob cancel")
    assert not slack_bot.is_cancel_command("cancelar el schedule de mañana")
    registry = slack_bot.ActiveJobRegistry()
    registry.set("C1", "T1", "job123")
    assert registry.get("C1", "T1") == "job123"
    registry.remove("C1", "T1", "different")
    assert registry.get("C1", "T1") == "job123"
    registry.remove("C1", "T1", "job123")
    assert registry.get("C1", "T1") is None


# --------------------------------------------------------------------------- #
# clean_output
# --------------------------------------------------------------------------- #
def test_clean_output_extracts_answer_between_markers():
    raw = (
        "<thinking>\nThe user is greeting me...\n</thinking>\n\n"
        "Sí, te escucho...[using tool attempt_completion: done | Cost: 0.08]\n"
        "---output---\n\n"
        "Sí, te escucho perfectamente. Soy Bob Shell.\n\n"
        "---output---\n"
    )
    assert slack_bot.clean_output(raw) == "Sí, te escucho perfectamente. Soy Bob Shell."


def test_clean_output_picks_last_block_not_tool_summary():
    # Bob emits one ---output--- block per tool; the answer is the LAST one,
    # not the first ("Listed 20 item(s).").
    raw = (
        "<thinking>plan</thinking>\n[using tool list_files: .]\n"
        "---output---\nListed 20 item(s).\n---output---\n"
        "<thinking>done</thinking>\n[using tool attempt_completion: ok]\n"
        "---output---\n\n[DIR] app\n[DIR] bin\n[DIR] var\n\n---output---\n"
    )
    assert slack_bot.clean_output(raw) == "[DIR] app\n[DIR] bin\n[DIR] var"


def test_clean_output_strips_thinking_and_tool_noise_without_markers():
    raw = "<thinking>plan it</thinking>\nHecho.[using tool read_file: ok]"
    assert slack_bot.clean_output(raw) == "Hecho."


def test_clean_output_empty():
    assert slack_bot.clean_output("") == ""


def test_clean_output_extracts_bob2_answer_and_removes_cli_rules():
    raw = (
        "\x1b[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m\n"
        "User (1)\nactualiza el perfil\n"
        "────────────────────────────────\n"
        "Assistant (2) final\nPushed successfully.\n────\n"
        "════════════════════════════════\n"
    )
    assert slack_bot.clean_output(raw) == "Pushed successfully."


def test_run_prompt_cleans_success_output():
    raw = "<thinking>x</thinking>\n---output---\nHola\n---output---"
    resp = _FakeResp({"ok": True, "exit_code": 0, "output": raw})
    with patch.object(slack_bot.urllib.request, "urlopen", return_value=resp):
        assert slack_bot.run_prompt("hi", harness_url="http://h:8080") == "Hola"


# --------------------------------------------------------------------------- #
# build_reply
# --------------------------------------------------------------------------- #
def test_build_reply_plain_prose_stays_plain():
    assert slack_bot.build_reply("Listo, creé el archivo en /workspace.") == \
        "Listo, creé el archivo en /workspace."


def test_build_reply_wraps_diff_in_code_block():
    diff = (
        "Index: hello.py\n"
        "--- hello.py\tOriginal\n"
        "+++ hello.py\tWritten\n"
        "@@ -0,0 +1,3 @@\n"
        '+print("Hello, World!")'
    )
    reply = slack_bot.build_reply(diff)
    assert reply.startswith("```\n") and reply.endswith("\n```")
    assert "Index: hello.py" in reply


def test_build_reply_wraps_source_code():
    code = 'def add(a, b):\n    return a + b\n\nprint(add(1, 2))'
    reply = slack_bot.build_reply(code)
    assert reply.startswith("```")


def test_build_reply_passes_through_existing_fences():
    fenced = "Aquí tienes:\n```python\nprint(1)\n```"
    assert slack_bot.build_reply(fenced) == fenced


def test_looks_like_code_detects_and_rejects():
    assert slack_bot.looks_like_code("@@ -1 +1 @@\n+x = 1")
    assert slack_bot.looks_like_code("#!/usr/bin/env python3\nprint(1)")
    assert not slack_bot.looks_like_code("Hola, ¿en qué te ayudo hoy?")


def test_build_reply_bulleted_list_stays_plain():
    # A prose message with a "- " bullet list must NOT be wrapped in a code
    # block (a "- " prefix is a bullet marker, not a diff line).
    msg = (
        "I have full access to:\n"
        "- The entire container filesystem\n"
        "- Shell command execution\n"
        "- File operations (read, write, edit)\n"
        "- Code analysis and development tools\n\n"
        "What would you like me to work on?"
    )
    reply = slack_bot.build_reply(msg)
    assert not reply.startswith("```")
    assert reply == msg


def test_build_replies_preserves_long_output_without_truncation():
    text = "A" * 2000 + "\n\n" + "B" * 2000
    replies = slack_bot.build_replies(text)
    assert len(replies) == 2
    assert all(len(reply) <= slack_bot.MAX_REPLY_CHARS for reply in replies)
    assert "\n\n".join(replies) == text
    assert all("output truncated" not in reply for reply in replies)


# --------------------------------------------------------------------------- #
# post_message (outbound, used by the scheduler)
# --------------------------------------------------------------------------- #
def test_post_message_ok(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["auth"] = req.headers.get("Authorization")
        return _Resp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok, err = slack_bot.post_message("C123", "hola")
    assert ok and err == ""
    assert captured["url"].endswith("/api/chat.postMessage")
    assert captured["body"]["channel"] == "C123" and captured["body"]["text"] == "hola"
    assert captured["auth"] == "Bearer xoxb-test"


def test_post_message_requires_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    ok, err = slack_bot.post_message("C123", "hola")
    assert not ok and "SLACK_BOT_TOKEN" in err


def test_build_conversation_prompt_includes_channel():
    p = slack_bot.build_conversation_prompt("", "hola", channel_id="C999")
    assert "C999" in p


# --------------------------------------------------------------------------- #
# Thread context: format_thread / build_conversation_prompt
# --------------------------------------------------------------------------- #
def test_format_thread_labels_roles_and_skips_noise():
    msgs = [
        {"ts": "1", "text": "crea un hello world", "user": "U1"},
        {"ts": "2", "text": "hecho", "bot_id": "B1"},
        {"ts": "3", "text": slack_bot.THINKING_TEXT, "bot_id": "B1"},  # placeholder
        {"ts": "3b", "text": slack_bot.THINKING_PHRASES[1], "bot_id": "B1"},  # rotated placeholder
        {"ts": "4", "subtype": "channel_join", "text": "joined"},       # noise
        {"ts": "5", "text": "donde quedó?", "user": "U1"},              # current msg
    ]
    out = slack_bot.format_thread(msgs, current_ts="5")
    assert out == "User: crea un hello world\nAssistant: hecho"


def test_format_thread_caps_message_count():
    msgs = [{"ts": str(i), "text": f"m{i}", "user": "U1"} for i in range(40)]
    out = slack_bot.format_thread(msgs)
    assert len(out.splitlines()) == slack_bot.MAX_HISTORY_MESSAGES


def test_format_thread_keeps_prior_file_share_context():
    msgs = [{
        "ts": "1",
        "subtype": "file_share",
        "text": "compara esta captura",
        "files": [{"name": "before.png"}],
        "user": "U1",
    }]
    assert slack_bot.format_thread(msgs) == (
        "User: compara esta captura\n[shared files: before.png]"
    )


def test_build_conversation_prompt_without_history_has_guidance_and_message():
    prompt = slack_bot.build_conversation_prompt("", "hola")
    assert "Answer guidance" in prompt
    assert prompt.strip().endswith("hola")


def test_build_conversation_prompt_with_history_wraps_context():
    prompt = slack_bot.build_conversation_prompt("User: hi\nAssistant: hello", "y ahora?")
    assert "Answer guidance" in prompt
    assert "conversation so far" in prompt
    assert "User: hi" in prompt and "Assistant: hello" in prompt
    assert prompt.strip().endswith("User: y ahora?")


# --------------------------------------------------------------------------- #
# Thinking-placeholder animation: thinking_phrase / is_thinking_text / rotator
# --------------------------------------------------------------------------- #
def test_thinking_phrase_round_robin():
    n = len(slack_bot.THINKING_PHRASES)
    assert n >= 2
    assert slack_bot.thinking_phrase(0) == slack_bot.THINKING_PHRASES[0]
    assert slack_bot.thinking_phrase(1) == slack_bot.THINKING_PHRASES[1]
    assert slack_bot.thinking_phrase(n) == slack_bot.THINKING_PHRASES[0]  # wraps around
    assert slack_bot.thinking_phrase(0) != slack_bot.thinking_phrase(1)


def test_is_thinking_text():
    for phrase in slack_bot.THINKING_PHRASES:
        assert slack_bot.is_thinking_text(phrase)
    assert slack_bot.is_thinking_text(slack_bot.THINKING_TEXT)
    # Surrounding whitespace is ignored.
    assert slack_bot.is_thinking_text(f"  {slack_bot.THINKING_PHRASES[0]}  ")
    assert not slack_bot.is_thinking_text("Listo, creé el archivo.")
    assert not slack_bot.is_thinking_text("")


class _RecordingClient:
    """Fake Slack client that records chat_update text (optionally raising)."""

    def __init__(self, raise_always: bool = False):
        self.texts: list[str] = []
        self._raise = raise_always

    def chat_update(self, channel, ts, text):
        self.texts.append(text)
        if self._raise:
            raise RuntimeError("rate limited")


def _run_animator(client, interval=0.01, alive=0.06):
    stop = threading.Event()
    t = threading.Thread(
        target=slack_bot._animate_thinking,
        args=(client, "C1", "123.45", stop, interval, logging.getLogger("test")),
        daemon=True,
    )
    t.start()
    time.sleep(alive)  # let a few ticks fire
    stop.set()
    t.join(timeout=1)
    return t


def test_animate_thinking_rotates_until_stopped():
    client = _RecordingClient()
    t = _run_animator(client)
    assert not t.is_alive()  # exits promptly once stop is set
    assert len(client.texts) >= 1
    assert all(slack_bot.is_thinking_text(txt) for txt in client.texts)
    if len(client.texts) >= 2:  # consecutive ticks rotate to different phrases
        assert client.texts[0] != client.texts[1]


def test_animate_thinking_does_not_fire_for_fast_runs():
    # Interval longer than the window => run finished before the first edit.
    client = _RecordingClient()
    t = _run_animator(client, interval=5, alive=0.02)
    assert not t.is_alive()
    assert client.texts == []  # no flicker for quick answers


def test_animate_thinking_survives_update_errors():
    client = _RecordingClient(raise_always=True)
    t = _run_animator(client)
    assert not t.is_alive()      # kept animating despite errors, then exited cleanly
    assert len(client.texts) >= 1
