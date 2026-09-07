"""Unit tests for the Bob REST API wrapper.

These tests never call the real `bob` binary or the IBM API: `subprocess.run`
and `os.makedirs` are mocked, so they run fast and offline.
"""
import subprocess
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(monkeypatch):
    # Guarantee a key is present by default; individual tests can drop it.
    monkeypatch.setenv("BOBSHELL_API_KEY", "test-key")
    return TestClient(server.app)


def _fake_completed(returncode=0, stdout="done", stderr=""):
    return subprocess.CompletedProcess(
        args=["bob"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health_ok(client):
    with patch.object(server, "_bob_available", return_value=True):
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["bob_present"] is True
    assert body["api_key_set"] is True
    assert body["default_mode"] == server.DEFAULT_MODE


def test_health_reports_missing_key(monkeypatch):
    monkeypatch.delenv("BOBSHELL_API_KEY", raising=False)
    c = TestClient(server.app)
    r = c.get("/health")
    assert r.json()["api_key_set"] is False


# --------------------------------------------------------------------------- #
# /invoke — validation
# --------------------------------------------------------------------------- #
def test_invoke_empty_prompt_returns_400(client):
    r = client.post("/invoke", json={"prompt": "   "})
    assert r.status_code == 400


def test_invoke_missing_key_returns_500(monkeypatch):
    monkeypatch.delenv("BOBSHELL_API_KEY", raising=False)
    c = TestClient(server.app)
    r = c.post("/invoke", json={"prompt": "hi"})
    assert r.status_code == 500
    assert "BOBSHELL_API_KEY" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# /invoke — command construction
# --------------------------------------------------------------------------- #
def test_invoke_success_builds_default_command(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "run", return_value=_fake_completed(stdout="OK")
    ) as run:
        r = client.post("/invoke", json={"prompt": "say ok"})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["exit_code"] == 0
    assert body["output"] == "OK"

    cmd = run.call_args.args[0]
    assert cmd == [
        "bob",
        "run",
        "--accept-license",
        "--mode",
        "unrestricted-dev",
        "say ok",
    ]
    # Runs in the default workdir.
    assert run.call_args.kwargs["cwd"] == server.DEFAULT_WORKDIR


def test_invoke_yolo_false_omits_flag(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "run", return_value=_fake_completed()
    ) as run:
        client.post("/invoke", json={"prompt": "x", "yolo": False})
    assert "--yolo" not in run.call_args.args[0]


def test_invoke_custom_mode_and_workdir(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "run", return_value=_fake_completed()
    ) as run:
        client.post(
            "/invoke",
            json={"prompt": "x", "mode": "reviewer", "workdir": "/tmp/proj"},
        )
    cmd = run.call_args.args[0]
    assert "--mode" in cmd and "reviewer" in cmd
    assert run.call_args.kwargs["cwd"] == "/tmp/proj"


def test_invoke_nonzero_exit_sets_ok_false(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "run", return_value=_fake_completed(returncode=2, stderr="boom")
    ):
        r = client.post("/invoke", json={"prompt": "x"})
    body = r.json()
    assert body["ok"] is False
    assert body["exit_code"] == 2
    assert body["error"] == "boom"


# --------------------------------------------------------------------------- #
# /invoke — subprocess failures
# --------------------------------------------------------------------------- #
def test_invoke_bob_not_found_returns_500(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "run", side_effect=FileNotFoundError()
    ):
        r = client.post("/invoke", json={"prompt": "x"})
    assert r.status_code == 500
    assert "not found" in r.json()["detail"]


def test_invoke_timeout_returns_504(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="bob", timeout=1)
    ):
        r = client.post("/invoke", json={"prompt": "x", "timeout": 1})
    assert r.status_code == 504


def test_invoke_timeout_out_of_range_returns_422(client):
    r = client.post("/invoke", json={"prompt": "x", "timeout": 99999})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# /jobs and /stream (async background execution)
# --------------------------------------------------------------------------- #
class FakePopen:
    """Minimal stand-in for subprocess.Popen used by Job.run()."""

    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._rc = returncode
        self.returncode = None

    def wait(self, timeout=None):
        self.returncode = self._rc
        return self._rc

    def kill(self):  # pragma: no cover - only hit on timeout paths
        pass


def _wait_done(run_id, timeout=5):
    server._runs[run_id].done.wait(timeout=timeout)


def test_create_job_runs_and_completes(client):
    fake = FakePopen(["hello\n", "world\n"], returncode=0)
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", return_value=fake
    ):
        r = client.post("/jobs", json={"prompt": "x"})
        assert r.status_code == 202
        jid = r.json()["id"]
        # The worker thread may already be running or even done by now.
        assert r.json()["status"] in ("pending", "running", "completed")

        _wait_done(jid)
        view = client.get(f"/jobs/{jid}").json()

    assert view["status"] == "completed"
    assert view["exit_code"] == 0
    assert "hello" in view["output"] and "world" in view["output"]


def test_job_failed_exit_code(client):
    fake = FakePopen(["oops\n"], returncode=3)
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", return_value=fake
    ):
        jid = client.post("/jobs", json={"prompt": "x"}).json()["id"]
        _wait_done(jid)
        view = client.get(f"/jobs/{jid}").json()

    assert view["status"] == "failed"
    assert view["exit_code"] == 3


def test_job_bob_not_found(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", side_effect=FileNotFoundError()
    ):
        jid = client.post("/jobs", json={"prompt": "x"}).json()["id"]
        _wait_done(jid)
        view = client.get(f"/jobs/{jid}").json()

    assert view["status"] == "failed"
    assert view["exit_code"] == 127
    assert "not found" in view["output"]


def test_get_unknown_job_returns_404(client):
    assert client.get("/jobs/deadbeef").status_code == 404


def test_cancel_unknown_job_returns_404(client):
    assert client.delete("/jobs/deadbeef").status_code == 404


def test_cancel_job_kills_process_group_and_reaches_cancelled(client):
    with patch.object(server.os, "makedirs"), patch.object(
        server, "_bob_cmd", return_value=["bash", "-c", "sleep 30 & wait"]
    ):
        jid = client.post("/jobs", json={"prompt": "x"}).json()["id"]
        for _ in range(100):
            if server._runs[jid].status == "running":
                break
            time.sleep(0.01)
        response = client.delete(f"/jobs/{jid}")
        assert response.status_code == 200
        assert response.json()["cancel_requested"] is True
        _wait_done(jid)
        view = client.get(f"/jobs/{jid}").json()

    assert view["status"] == "cancelled"
    assert "cancelled by user" in view["output"]


def test_cancel_completed_job_is_idempotent(client):
    fake = FakePopen(["done\n"], returncode=0)
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", return_value=fake
    ):
        jid = client.post("/jobs", json={"prompt": "x"}).json()["id"]
        _wait_done(jid)
        response = client.delete(f"/jobs/{jid}")
    assert response.json() == {
        "id": jid,
        "status": "completed",
        "cancel_requested": False,
    }


# --------------------------------------------------------------------------- #
# Timeout watchdog kills the whole process tree (no hung jobs)
# --------------------------------------------------------------------------- #
def test_job_starts_child_in_own_session(client):
    # start_new_session=True is what lets the watchdog SIGKILL the process
    # group instead of just the direct child.
    fake = FakePopen(["hi\n"], returncode=0)
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", return_value=fake
    ) as popen:
        jid = client.post("/jobs", json={"prompt": "x"}).json()["id"]
        _wait_done(jid)
    assert popen.call_args.kwargs["start_new_session"] is True


def test_stream_exec_kills_process_tree_on_timeout():
    # A grandchild (`sleep 30`) inherits the stdout pipe. Killing only the
    # direct child (bash) would leave the pipe open and block the read loop for
    # ~30s. Killing the process group unblocks it, so this returns promptly.
    sink = server.Job(["true"], "/", 1)
    start = time.monotonic()
    _out, rc, timed_out = server._stream_exec(
        sink, ["bash", "-c", "sleep 30 & wait"], cwd="/", timeout=0.5
    )
    elapsed = time.monotonic() - start

    assert timed_out is True
    assert rc is None
    assert elapsed < 10, f"read loop blocked on the grandchild ({elapsed:.1f}s)"


def test_stream_emits_data_and_done_events(client):
    fake = FakePopen(["line-a\n", "line-b\n"], returncode=0)
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", return_value=fake
    ):
        r = client.post("/stream", json={"prompt": "x"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = r.text

    assert "data: line-a" in body
    assert "data: line-b" in body
    assert "event: done" in body


# --------------------------------------------------------------------------- #
# /run (orchestration: execute -> verify -> retry)
# --------------------------------------------------------------------------- #
def test_run_no_check_uses_bob_exit_code(client):
    fake = FakePopen(["built\n"], returncode=0)
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", return_value=fake
    ):
        rid = client.post("/run", json={"prompt": "build it"}).json()["id"]
        _wait_done(rid)
        view = client.get(f"/jobs/{rid}").json()

    assert view["type"] == "harness"
    assert view["status"] == "completed"
    assert view["success"] is True
    assert len(view["attempts"]) == 1


def test_run_passes_check_on_first_attempt(client):
    # First Popen = bob (ok), second Popen = check (ok).
    seq = [FakePopen(["work\n"], 0), FakePopen(["tests ok\n"], 0)]
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", side_effect=seq
    ):
        rid = client.post("/run", json={"prompt": "x", "check": "pytest"}).json()["id"]
        _wait_done(rid)
        view = client.get(f"/jobs/{rid}").json()

    assert view["success"] is True
    assert len(view["attempts"]) == 1
    assert view["attempts"][0]["check_exit_code"] == 0


def test_run_retries_then_succeeds(client):
    # attempt1: bob ok, check FAIL(1); attempt2: bob ok, check PASS(0)
    seq = [
        FakePopen(["work1\n"], 0),
        FakePopen(["fail\n"], 1),
        FakePopen(["work2\n"], 0),
        FakePopen(["pass\n"], 0),
    ]
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", side_effect=seq
    ):
        rid = client.post(
            "/run", json={"prompt": "x", "check": "pytest", "max_attempts": 3}
        ).json()["id"]
        _wait_done(rid)
        view = client.get(f"/jobs/{rid}").json()

    assert view["success"] is True
    assert view["status"] == "completed"
    assert len(view["attempts"]) == 2


def test_run_exhausts_attempts(client):
    # check always fails -> both attempts fail
    seq = [
        FakePopen(["w1\n"], 0),
        FakePopen(["bad\n"], 1),
        FakePopen(["w2\n"], 0),
        FakePopen(["bad\n"], 1),
    ]
    with patch.object(server.os, "makedirs"), patch.object(
        server.subprocess, "Popen", side_effect=seq
    ):
        rid = client.post(
            "/run", json={"prompt": "x", "check": "pytest", "max_attempts": 2}
        ).json()["id"]
        _wait_done(rid)
        view = client.get(f"/jobs/{rid}").json()

    assert view["success"] is False
    assert view["status"] == "failed"
    assert len(view["attempts"]) == 2
