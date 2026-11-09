"""Cron-based scheduler for Remote Bob.

Bob Shell is stateless — each `bob -p` is a one-shot process, so recurring work
needs a scheduler that *fires* Bob on a clock. That scheduler is the container's
own `cron` daemon: this module is the bridge between a REST/JSON view of
schedules and root's crontab.

Design:

  * The **source of truth** is a JSON registry persisted on the mounted volume
    (``/workspace/schedules.json`` by default), so schedules survive container
    recreation.
  * Root's crontab is **regenerated from that registry** on every change and on
    API startup (:func:`sync`) — never hand-edited.
  * Each schedule fires by curling the harness's own
    ``POST /schedules/{id}/run`` on localhost. That endpoint runs the stored
    prompt through the ``/run`` (verify+retry) machinery, so **cron itself needs
    none of Bob's environment** (no API key, no PATH surprises) and every run
    shows up in ``/jobs``.

The registry/crontab logic here is deliberately free of FastAPI so it can be
unit-tested offline (see test_schedules.py); the HTTP layer lives in server.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from runtime_config import api_url

# Persisted on the mounted volume so schedules outlive the container.
SCHEDULES_FILE = os.environ.get("BOB_SCHEDULES_FILE", "/workspace/schedules.json")
# Where each cron invocation's curl output is appended (handy for debugging).
CRON_LOG = os.environ.get("BOB_CRON_LOG", "/workspace/cron.log")
# Keep the internal name stable; both current and legacy env vars are accepted.
HARNESS_URL = api_url()

# Serializes read-modify-write of the JSON registry + crontab install.
_lock = threading.RLock()

# A single cron field: digits, and the *, comma, slash (step) and dash (range)
# operators. Enough for standard expressions like "*/5", "0,30", "1-5". Named
# values (mon, jan, @daily) are intentionally NOT accepted — keep it strict.
_CRON_FIELD = r"[0-9*,/\-]+"
_CRON_RE = re.compile(r"^\s*" + r"\s+".join([_CRON_FIELD] * 5) + r"\s*$")


class ScheduleError(ValueError):
    """Raised for invalid schedule input (bad cron expression, missing prompt)."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def valid_cron(expr: str) -> bool:
    """True if `expr` is a well-formed 5-field cron expression (m h dom mon dow)."""
    return bool(_CRON_RE.match(expr or ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Registry persistence (JSON on the volume)
# --------------------------------------------------------------------------- #
def load() -> list[dict]:
    """Return the list of stored schedules (empty if the registry is absent)."""
    with _lock:
        if not os.path.exists(SCHEDULES_FILE):
            return []
        try:
            with open(SCHEDULES_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []
    return data if isinstance(data, list) else []


def _write(schedules: list[dict]) -> None:
    with _lock:
        os.makedirs(os.path.dirname(SCHEDULES_FILE) or ".", exist_ok=True)
        tmp = f"{SCHEDULES_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(schedules, fh, indent=2)
        os.replace(tmp, SCHEDULES_FILE)  # atomic


# --------------------------------------------------------------------------- #
# Crontab generation / install
# --------------------------------------------------------------------------- #
def _cron_line(sched: dict) -> str:
    """The crontab line that fires one schedule by curling its /run endpoint."""
    url = f"{HARNESS_URL.rstrip('/')}/schedules/{sched['id']}/run"
    # -fsS: fail on HTTP errors, silent progress, but still show errors. The
    # output is appended to CRON_LOG so a failing job leaves a trail. The
    # trailing `echo` puts each acknowledgment on its own line (curl emits no
    # newline), keeping the log newline-delimited alongside the final-status
    # entries written by log_outcome().
    return (
        f"{sched['cron']} curl -fsS -X POST {url} "
        f">> {CRON_LOG} 2>&1; echo >> {CRON_LOG}"
    )


def crontab_body(schedules: list[dict]) -> str:
    """Render the full root crontab from the registry (enabled schedules only)."""
    lines = [
        "# ===================================================================",
        "# Managed by the Remote Bob scheduler — DO NOT EDIT BY HAND.",
        "# Source of truth: " + SCHEDULES_FILE,
        "# Regenerated on every /schedules change and on API startup.",
        "# ===================================================================",
        # cron runs with a bare PATH; make sure curl is reachable.
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "",
    ]
    for s in schedules:
        if not s.get("enabled", True):
            continue
        name = s.get("name") or s["id"]
        lines.append(f"# [{s['id']}] {name}")
        lines.append(_cron_line(s))
    return "\n".join(lines) + "\n"


def install_crontab(schedules: list[dict]) -> bool:
    """Load `schedules` into root's crontab via `crontab -`.

    Returns True on success. If the `crontab` binary is absent (e.g. running the
    API outside the container during local dev/tests), it logs nothing and
    returns False instead of raising — the JSON registry is still the source of
    truth and will be reinstalled next time cron is present.
    """
    body = crontab_body(schedules)
    try:
        subprocess.run(["crontab", "-"], input=body, text=True, check=True)
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError:
        return False


def sync() -> bool:
    """Regenerate root's crontab from the persisted registry. Call on startup."""
    return install_crontab(load())


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def add(
    *,
    cron: str,
    prompt: str,
    name: Optional[str] = None,
    mode: Optional[str] = None,
    check: Optional[str] = None,
    workdir: Optional[str] = None,
    channel: Optional[str] = None,
    max_attempts: int = 3,
    timeout: int = 600,
) -> dict:
    """Create a schedule, persist it, and reinstall the crontab. Returns it."""
    if not valid_cron(cron):
        raise ScheduleError(
            f"invalid cron expression: {cron!r} (expected 5 fields: m h dom mon dow)"
        )
    if not (prompt or "").strip():
        raise ScheduleError("prompt is required")

    sched = {
        "id": uuid.uuid4().hex[:12],
        "name": name or "",
        "cron": cron.strip(),
        "prompt": prompt,
        "mode": mode,
        "check": check,
        "workdir": workdir,
        # Slack channel id to post the run result to when it finishes (optional;
        # falls back to SLACK_DEFAULT_CHANNEL in the API layer).
        "channel": channel,
        "max_attempts": max_attempts,
        "timeout": timeout,
        "enabled": True,
        "created_at": _now(),
        "last_run": None,
        "last_status": None,
        "last_run_id": None,
    }
    with _lock:
        schedules = load()
        schedules.append(sched)
        _write(schedules)
        install_crontab(schedules)
    return sched


def get(schedule_id: str) -> Optional[dict]:
    """Return one schedule by id, or None."""
    for s in load():
        if s["id"] == schedule_id:
            return s
    return None


def remove(schedule_id: str) -> bool:
    """Delete a schedule and reinstall the crontab. True if it existed."""
    with _lock:
        schedules = load()
        kept = [s for s in schedules if s["id"] != schedule_id]
        if len(kept) == len(schedules):
            return False
        _write(kept)
        install_crontab(kept)
    return True


def mark_run(schedule_id: str, *, run_id: str, status: str) -> None:
    """Record the latest fire of a schedule (timestamp, run id, status)."""
    with _lock:
        schedules = load()
        for s in schedules:
            if s["id"] == schedule_id:
                s["last_run"] = _now()
                s["last_run_id"] = run_id
                s["last_status"] = status
                _write(schedules)
                return


def log_outcome(
    schedule_id: str, *, run_id: str, status: str, name: Optional[str] = None
) -> None:
    """Append the FINAL status of a scheduled run to the cron log.

    The crontab line only captures the immediate HTTP 202 acknowledgment, whose
    body is always ``{"status": "running"}`` because the run is still starting
    when the endpoint returns. That makes the raw log misleading — every line
    reads "running" even for jobs that long since finished. This records the
    real terminal state (completed/failed/timeout) once the run is done, as a
    newline-delimited JSON entry, so the log is actually useful for spotting
    failures. Best-effort: never raises if the log is unwritable.
    """
    entry = {
        "ts": _now(),
        "event": "outcome",
        "schedule_id": schedule_id,
        "run_id": run_id,
        "status": status,
    }
    if name:
        entry["name"] = name
    try:
        with open(CRON_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
