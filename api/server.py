"""Thin REST harness in front of Bob Shell.

Bob Shell has no native server mode, so this drives its non-interactive
`bob -p "<prompt>"` invocation. Requests shell out to `bob`, which
authenticates with the BOBSHELL_API_KEY present in the container env.

Two levels of use:

  * A plain wrapper — run one prompt, get the output (`/invoke`, `/jobs`).
  * An orchestration harness — run a prompt, VERIFY the result with a check
    command, and RETRY (feeding the failure back to Bob) until it passes or
    the attempt budget is exhausted (`/run`).

Endpoints:
  GET  /health              -> liveness + resolved config
  POST /invoke              -> run a prompt synchronously, return full output
  POST /jobs                -> start a prompt as a background job -> {id}
  POST /run                 -> start an orchestrated run (verify + retry) -> {id}
  GET  /jobs                -> list runs/jobs
  GET  /jobs/{id}           -> status + output (+ attempts for /run)
  GET  /jobs/{id}/stream    -> Server-Sent Events, streaming output live
  POST /stream              -> start a job AND stream it in one request (SSE)
  POST /schedules           -> register a recurring run (cron) -> schedule
  GET  /schedules           -> list schedules
  GET  /schedules/{id}      -> one schedule
  DELETE /schedules/{id}    -> remove a schedule
  POST /schedules/{id}/run  -> fire a schedule now (curled by cron on each tick)
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import threading
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import schedules


@asynccontextmanager
async def _lifespan(app: "FastAPI"):
    # Regenerate root's crontab from the persisted registry when the API boots,
    # so schedules created before a restart are re-armed.
    schedules.sync()
    yield


app = FastAPI(title="IBM Bob Shell REST Harness", version="1.3.0", lifespan=_lifespan)

# Defaults come from the container env (see Dockerfile / .env).
DEFAULT_MODE = os.environ.get("BOB_MODE", "unrestricted-dev")
DEFAULT_WORKDIR = os.environ.get("BOB_WORKDIR", "/")
BOB_BIN = os.environ.get("BOB_BIN", "bob")
MAX_JOBS = int(os.environ.get("BOB_MAX_JOBS", "100"))
# Fallback Slack channel for scheduled runs that don't specify one.
DEFAULT_SLACK_CHANNEL = os.environ.get("SLACK_DEFAULT_CHANNEL")


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #
class InvokeRequest(BaseModel):
    prompt: str = Field(..., description="The task / prompt for Bob.")
    yolo: bool = Field(True, description="Auto-approve all tool calls.")
    mode: Optional[str] = Field(None, description="Custom mode slug (--chat-mode).")
    workdir: Optional[str] = Field(None, description="Working directory for the run.")
    timeout: int = Field(600, ge=1, le=3600, description="Max seconds per Bob attempt.")


class RunRequest(InvokeRequest):
    check: Optional[str] = Field(
        None,
        description="Shell command that verifies success. Exit 0 => pass. "
        "If omitted, Bob's own exit code is the success signal.",
    )
    max_attempts: int = Field(3, ge=1, le=10, description="Max verify/retry attempts.")
    check_timeout: int = Field(300, ge=1, le=3600, description="Max seconds per check.")


class InvokeResponse(BaseModel):
    ok: bool
    exit_code: int
    output: str
    error: str = ""
    command: list[str]


class RunRef(BaseModel):
    id: str
    status: str


class ScheduleRequest(BaseModel):
    cron: str = Field(..., description="5-field cron expression: m h dom mon dow.")
    prompt: str = Field(..., description="The task Bob runs each time it fires.")
    name: Optional[str] = Field(None, description="Human-readable label.")
    mode: Optional[str] = Field(None, description="Custom mode slug (--chat-mode).")
    check: Optional[str] = Field(None, description="Verify command (exit 0 = pass).")
    workdir: Optional[str] = Field(None, description="Working directory for the run.")
    channel: Optional[str] = Field(
        None, description="Slack channel id to post the result to (falls back to "
        "SLACK_DEFAULT_CHANNEL). Empty = don't post to Slack.")
    max_attempts: int = Field(3, ge=1, le=10, description="Max verify/retry attempts.")
    timeout: int = Field(600, ge=1, le=3600, description="Max seconds per Bob attempt.")


# --------------------------------------------------------------------------- #
# Command construction (shared)
# --------------------------------------------------------------------------- #
def _require_key() -> None:
    if not os.environ.get("BOBSHELL_API_KEY"):
        raise HTTPException(status_code=500, detail="BOBSHELL_API_KEY not set in container")


def _resolve(req: InvokeRequest) -> tuple[str, str]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    workdir = req.workdir or DEFAULT_WORKDIR
    os.makedirs(workdir, exist_ok=True)
    return (req.mode or DEFAULT_MODE), workdir


def _bob_cmd(prompt: str, mode: str, yolo: bool) -> list[str]:
    # bob 2.x: 'run' subcommand replaces top-level --chat-mode; headless auto-approves
    return [BOB_BIN, "run", "--accept-license", "--mode", mode, prompt]


# --------------------------------------------------------------------------- #
# Background runs — a common base with live, line-buffered output
# --------------------------------------------------------------------------- #
class BaseRun:
    def __init__(self, cwd: str, timeout: int):
        self.id = uuid.uuid4().hex[:12]
        self.cwd = cwd
        self.timeout = timeout
        self.status = "pending"  # pending|running|completed|failed|timeout
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self.done = threading.Event()

    @property
    def output(self) -> str:
        with self._lock:
            return "".join(self._lines)

    def lines_from(self, idx: int) -> tuple[list[str], int]:
        with self._lock:
            return self._lines[idx:], len(self._lines)

    def _append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def view(self) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError


def _stream_exec(sink: BaseRun, cmd: list[str], cwd: str, timeout: int) -> tuple[str, Optional[int], bool]:
    """Run `cmd`, stream stdout (with stderr merged in) into `sink`.

    Returns (output, returncode, timed_out). A watchdog kills the process if it
    overruns `timeout`, so the deadline is real even if the child keeps writing.

    The child starts in its own session (``start_new_session=True``) so the
    watchdog can SIGKILL the whole process *group* — not just the direct child.
    If we killed only the direct PID, any grandchild that inherited the stdout
    pipe would keep it open, the ``for line in proc.stdout`` loop below would
    never see EOF, and the run would hang forever in "running" instead of
    reaching a terminal "timeout" state.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=dict(os.environ),
            start_new_session=True,
        )
    except FileNotFoundError:
        msg = f"'{cmd[0]}' not found on PATH\n"
        sink._append(msg)
        return msg, 127, False

    killed = {"v": False}

    def _kill() -> None:
        killed["v"] = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # Group already gone, or we can't signal it: at least kill the
            # direct child so we don't leave the watchdog a no-op.
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    timer = threading.Timer(timeout, _kill)
    timer.start()
    buf: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sink._append(line)
            buf.append(line)
        proc.wait()
    finally:
        timer.cancel()

    if killed["v"]:
        return "".join(buf), None, True
    return "".join(buf), proc.returncode, False


class Job(BaseRun):
    """One `bob` run, no verification."""

    def __init__(self, cmd: list[str], cwd: str, timeout: int):
        super().__init__(cwd, timeout)
        self.cmd = cmd
        self.exit_code: Optional[int] = None

    def run(self) -> None:
        self.status = "running"
        _out, rc, timed_out = _stream_exec(self, self.cmd, self.cwd, self.timeout)
        if timed_out:
            self._append(f"\n[harness] timed out after {self.timeout}s\n")
            self.status = "timeout"
            self.done.set()
            return
        self.exit_code = rc
        self.status = "completed" if rc == 0 else "failed"
        self.done.set()

    def view(self) -> dict:
        return {
            "id": self.id,
            "type": "job",
            "status": self.status,
            "exit_code": self.exit_code,
            "output": self.output,
            "command": self.cmd,
        }


class HarnessRun(BaseRun):
    """Orchestrated run: execute -> verify -> retry until pass or budget spent."""

    def __init__(self, req: RunRequest, mode: str, cwd: str):
        super().__init__(cwd, req.timeout)
        self.base_prompt = req.prompt
        self.mode = mode
        self.yolo = req.yolo
        self.check = req.check
        self.max_attempts = req.max_attempts
        self.check_timeout = req.check_timeout
        self.attempts: list[dict] = []
        self.success: Optional[bool] = None

    def _retry_prompt(self, check_output: str) -> str:
        tail = check_output[-4000:]
        return (
            f"{self.base_prompt}\n\n"
            f"--- HARNESS FEEDBACK ---\n"
            f"Your previous attempt did NOT pass the verification command:\n"
            f"  $ {self.check}\n\n"
            f"Command output (may be truncated):\n{tail}\n\n"
            f"Fix the problem so that command exits successfully. Edit files as "
            f"needed and do not ask for confirmation."
        )

    def run(self) -> None:
        self.status = "running"
        prompt = self.base_prompt

        for attempt in range(1, self.max_attempts + 1):
            self._append(f"\n[harness] ===== attempt {attempt}/{self.max_attempts} =====\n")
            bob_out, bob_rc, timed_out = _stream_exec(
                self, _bob_cmd(prompt, self.mode, self.yolo), self.cwd, self.timeout
            )
            record: dict = {"attempt": attempt, "bob_exit_code": bob_rc}
            if timed_out:
                record["timed_out"] = True
                self.attempts.append(record)
                self._append(f"\n[harness] Bob timed out after {self.timeout}s\n")
                self.success = False
                self.status = "timeout"
                self.done.set()
                return

            # No check => Bob's own exit code decides success.
            if not self.check:
                self.attempts.append(record)
                self.success = bob_rc == 0
                self.status = "completed" if self.success else "failed"
                self.done.set()
                return

            self._append(f"\n[harness] running check: {self.check}\n")
            chk_out, chk_rc, chk_timeout = _stream_exec(
                self, ["bash", "-lc", self.check], self.cwd, self.check_timeout
            )
            record["check_exit_code"] = None if chk_timeout else chk_rc
            record["check_timed_out"] = chk_timeout
            self.attempts.append(record)

            if not chk_timeout and chk_rc == 0:
                self._append(f"\n[harness] check passed on attempt {attempt} ✓\n")
                self.success = True
                self.status = "completed"
                self.done.set()
                return

            self._append(f"\n[harness] check failed (exit {chk_rc}) ✗ — retrying\n")
            prompt = self._retry_prompt(chk_out)

        self._append(f"\n[harness] exhausted {self.max_attempts} attempts without passing ✗\n")
        self.success = False
        self.status = "failed"
        self.done.set()

    def view(self) -> dict:
        return {
            "id": self.id,
            "type": "harness",
            "status": self.status,
            "success": self.success,
            "check": self.check,
            "max_attempts": self.max_attempts,
            "attempts": self.attempts,
            "output": self.output,
        }


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_runs: "OrderedDict[str, BaseRun]" = OrderedDict()
_runs_lock = threading.Lock()


def _register(run: BaseRun) -> None:
    with _runs_lock:
        _runs[run.id] = run
        while len(_runs) > MAX_JOBS:
            _runs.popitem(last=False)  # evict oldest


def _get(run_id: str) -> BaseRun:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _spawn(run: BaseRun) -> BaseRun:
    _register(run)
    threading.Thread(target=run.run, daemon=True).start()
    return run


async def _sse(run: BaseRun):
    """Yield Server-Sent Events for a run's output until it finishes."""
    idx = 0
    while True:
        new, idx = run.lines_from(idx)
        for line in new:
            yield f"data: {line.rstrip(chr(10))}\n\n"
        if run.done.is_set():
            new, idx = run.lines_from(idx)
            for line in new:
                yield f"data: {line.rstrip(chr(10))}\n\n"
            payload = {"status": run.status, "success": getattr(run, "success", None)}
            yield f"event: done\ndata: {json.dumps(payload)}\n\n"
            return
        await asyncio.sleep(0.25)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "bob_present": _bob_available(),
        "default_mode": DEFAULT_MODE,
        "default_workdir": DEFAULT_WORKDIR,
        "api_key_set": bool(os.environ.get("BOBSHELL_API_KEY")),
    }


@app.post("/invoke", response_model=InvokeResponse)
def invoke(req: InvokeRequest) -> InvokeResponse:
    _require_key()
    mode, workdir = _resolve(req)
    cmd = _bob_cmd(req.prompt, mode, req.yolo)
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True,
            timeout=req.timeout, env=dict(os.environ),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"'{BOB_BIN}' not found on PATH")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"bob timed out after {req.timeout}s")
    return InvokeResponse(
        ok=proc.returncode == 0, exit_code=proc.returncode,
        output=proc.stdout, error=proc.stderr, command=cmd,
    )


@app.post("/jobs", response_model=RunRef, status_code=202)
def create_job(req: InvokeRequest) -> RunRef:
    _require_key()
    mode, workdir = _resolve(req)
    job = _spawn(Job(_bob_cmd(req.prompt, mode, req.yolo), workdir, req.timeout))
    return RunRef(id=job.id, status=job.status)


@app.post("/run", response_model=RunRef, status_code=202)
def create_run(req: RunRequest) -> RunRef:
    """Orchestrated run: execute, verify with `check`, retry on failure."""
    _require_key()
    mode, workdir = _resolve(req)
    run = _spawn(HarnessRun(req, mode, workdir))
    return RunRef(id=run.id, status=run.status)


@app.get("/jobs")
def list_runs() -> dict:
    with _runs_lock:
        return {"runs": [{"id": r.id, "status": r.status} for r in _runs.values()]}


@app.get("/jobs/{run_id}")
def get_run(run_id: str) -> dict:
    return _get(run_id).view()


@app.get("/jobs/{run_id}/stream")
def stream_run(run_id: str) -> StreamingResponse:
    return StreamingResponse(_sse(_get(run_id)), media_type="text/event-stream")


@app.post("/stream")
def start_and_stream(req: InvokeRequest) -> StreamingResponse:
    _require_key()
    mode, workdir = _resolve(req)
    job = _spawn(Job(_bob_cmd(req.prompt, mode, req.yolo), workdir, req.timeout))
    return StreamingResponse(_sse(job), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Schedules — recurring runs fired by the container's cron daemon
# --------------------------------------------------------------------------- #
@app.post("/schedules", status_code=201)
def create_schedule(req: ScheduleRequest) -> dict:
    """Register a recurring task. Persists it and (re)installs root's crontab."""
    try:
        return schedules.add(
            cron=req.cron,
            prompt=req.prompt,
            name=req.name,
            mode=req.mode,
            check=req.check,
            workdir=req.workdir,
            channel=req.channel,
            max_attempts=req.max_attempts,
            timeout=req.timeout,
        )
    except schedules.ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/schedules")
def list_schedules() -> dict:
    return {"schedules": schedules.load()}


@app.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: str) -> dict:
    sched = schedules.get(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return sched


@app.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str) -> dict:
    if not schedules.remove(schedule_id):
        raise HTTPException(status_code=404, detail="schedule not found")
    return {"deleted": schedule_id}


@app.post("/schedules/{schedule_id}/run", response_model=RunRef, status_code=202)
def run_schedule(schedule_id: str) -> RunRef:
    """Fire a schedule now. This is the endpoint cron curls on each tick."""
    _require_key()
    sched = schedules.get(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")

    req = RunRequest(
        prompt=sched["prompt"],
        mode=sched.get("mode"),
        check=sched.get("check"),
        workdir=sched.get("workdir"),
        max_attempts=sched.get("max_attempts", 3),
        timeout=sched.get("timeout", 600),
    )
    mode, workdir = _resolve(req)
    run = _spawn(HarnessRun(req, mode, workdir))
    schedules.mark_run(schedule_id, run_id=run.id, status="started")
    channel = sched.get("channel") or DEFAULT_SLACK_CHANNEL

    # When the run finishes: record its status and (optionally) post the result
    # to Slack. Runs off-thread so the HTTP response returns immediately.
    def _record() -> None:
        run.done.wait()
        schedules.mark_run(schedule_id, run_id=run.id, status=run.status)
        # Write the real terminal status to the cron log. The line cron itself
        # appended only captured the "running" acknowledgment; this makes the
        # log reflect completed/failed/timeout so failures are visible there.
        schedules.log_outcome(
            schedule_id, run_id=run.id, status=run.status, name=sched.get("name")
        )
        if channel:
            _deliver_to_slack(sched, run, channel)

    threading.Thread(target=_record, daemon=True).start()
    return RunRef(id=run.id, status=run.status)


def _deliver_to_slack(sched: dict, run: "HarnessRun", channel: str) -> None:
    """Post a finished scheduled run's cleaned output to a Slack channel."""
    import slack_bot

    label = sched.get("name") or sched["id"]
    answer = slack_bot.clean_output(run.output) or "(no output)"
    if run.status != "completed":
        answer = f":warning: scheduled run `{label}` ended with status *{run.status}*\n\n{answer}"
    ok, err = slack_bot.post_message(channel, slack_bot.build_reply(answer))
    if not ok:
        print(f"[scheduler] failed to post schedule {sched['id']} to {channel}: {err}")


def _bob_available() -> bool:
    from shutil import which

    return which(BOB_BIN) is not None
