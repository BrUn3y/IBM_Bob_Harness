"""Google Drive change notifications and a durable, single-consumer Bob queue.

Drive webhooks are wake-up signals, not file events. The persisted changes
cursor is authoritative; periodic catch-up also recovers missed notifications.
Only direct children of the configured input folder are accepted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
DOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id,name,mimeType,parents,trashed,modifiedTime,version,size"
TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}


class DriveError(ValueError):
    """Invalid integration configuration or unsupported document."""


@dataclass(frozen=True)
class DriveConfig:
    folder_id: str
    webhook_url: str
    admin_token: str
    state_dir: Path
    folder_name: str = "Workspace_agent"
    credentials_file: str = ""
    shared_drive_id: str = ""
    poll_seconds: int = 60
    settle_seconds: int = 20
    max_file_bytes: int = 1_048_576
    timeout: int = 600
    slack_channel: str = ""

    @classmethod
    def from_env(cls) -> Optional["DriveConfig"]:
        if os.environ.get("DRIVE_ENABLED", "false").lower() != "true":
            return None
        folder = os.environ.get("DRIVE_FOLDER_ID", "").strip()
        folder_name = os.environ.get("DRIVE_FOLDER_NAME", "Workspace_agent").strip()
        url = os.environ.get("DRIVE_WEBHOOK_URL", "").strip()
        token = os.environ.get("DRIVE_ADMIN_TOKEN", "")
        parsed = urlparse(url)
        if folder and not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
            raise DriveError("DRIVE_FOLDER_ID must be a Google Drive folder ID")
        if not folder and not folder_name:
            raise DriveError("Set DRIVE_FOLDER_NAME or DRIVE_FOLDER_ID")
        if (parsed.scheme != "https" or not parsed.hostname or parsed.query
                or parsed.fragment or parsed.username or parsed.password
                or parsed.path != "/integrations/drive/webhook"):
            raise DriveError("DRIVE_WEBHOOK_URL must be https://<host>/integrations/drive/webhook")
        if len(token) < 32:
            raise DriveError("DRIVE_ADMIN_TOKEN must contain at least 32 characters")
        config = cls(
            folder_id=folder, webhook_url=url, admin_token=token,
            folder_name=folder_name,
            credentials_file=os.environ.get("DRIVE_SERVICE_ACCOUNT_FILE", ""),
            state_dir=Path(os.environ.get("DRIVE_STATE_DIR", "/workspace/drive")),
            shared_drive_id=os.environ.get("DRIVE_SHARED_DRIVE_ID", ""),
            poll_seconds=int(os.environ.get("DRIVE_POLL_SECONDS", "60")),
            settle_seconds=int(os.environ.get("DRIVE_SETTLE_SECONDS", "20")),
            max_file_bytes=int(os.environ.get("DRIVE_MAX_FILE_BYTES", "1048576")),
            timeout=int(os.environ.get("DRIVE_JOB_TIMEOUT", "600")),
            slack_channel=(os.environ.get("DRIVE_SLACK_CHANNEL")
                           or os.environ.get("SLACK_DEFAULT_CHANNEL", "")).strip(),
        )
        if (config.poll_seconds < 1 or config.settle_seconds < 0
                or config.max_file_bytes < 1 or not 1 <= config.timeout <= 3600):
            raise DriveError("Invalid Drive polling, settling, size or timeout limit")
        return config


class DriveClient:
    """Lazy ADC/service-account auth; read-only Drive access, bounded downloads."""

    def __init__(self, config: DriveConfig):
        self.config = config
        self._session = None

    @property
    def session(self):
        if self._session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            scopes = ["https://www.googleapis.com/auth/drive.readonly"]
            if self.config.credentials_file:
                from google.oauth2.service_account import Credentials

                credentials = Credentials.from_service_account_file(
                    self.config.credentials_file, scopes=scopes,
                )
            else:
                credentials, _ = google.auth.default(scopes=scopes)
            # This integration intentionally uses service accounts, not user ADC.
            from google.oauth2.credentials import Credentials as UserCredentials

            if isinstance(credentials, UserCredentials):
                raise DriveError("Drive requires service-account credentials, not user ADC")
            self._session = AuthorizedSession(credentials)
        return self._session

    def request(self, method: str, path: str, **kwargs):
        response = self.session.request(
            method, "https://www.googleapis.com/drive/v3/" + path,
            timeout=30, **kwargs,
        )
        try:
            response.raise_for_status()
        except Exception:
            response.close()
            raise
        return response

    def json(self, method: str, path: str, **kwargs) -> dict:
        with self.request(method, path, **kwargs) as response:
            return response.json()

    def start_token(self) -> str:
        params = {"supportsAllDrives": "true"}
        if self.config.shared_drive_id:
            params["driveId"] = self.config.shared_drive_id
        return self.json("GET", "changes/startPageToken", params=params)["startPageToken"]

    def find_folder(self, name: str) -> str:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        params = {
            "q": f"trashed = false and mimeType = '{FOLDER_MIME}' and name = '{escaped}'",
            "fields": "nextPageToken,files(id)", "pageSize": 100,
            "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        }
        if self.config.shared_drive_id:
            params.update({"driveId": self.config.shared_drive_id, "corpora": "drive"})
        result = self.json("GET", "files", params=params)
        files = result.get("files", [])
        if not files:
            raise DriveError("Input folder is not accessible; share it with the service account")
        if len(files) != 1 or result.get("nextPageToken"):
            raise DriveError("Multiple input folders have this name; set DRIVE_FOLDER_ID explicitly")
        return files[0]["id"]

    def change_params(self, token: str) -> dict:
        params = {
            "pageToken": token, "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if self.config.shared_drive_id:
            params["driveId"] = self.config.shared_drive_id
        return params

    def changes(self, token: str) -> dict:
        params = self.change_params(token)
        params.update({
            "pageSize": 100,
            "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,file(" + FILE_FIELDS + "))",
        })
        return self.json("GET", "changes", params=params)

    def watch(self, token: str, channel: dict) -> dict:
        return self.json("POST", "changes/watch", params=self.change_params(token), json={
            "id": channel["id"], "type": "web_hook",
            "address": self.config.webhook_url, "token": channel["token"],
            "expiration": str(int((time.time() + 6 * 86400) * 1000)),
        })

    def stop_channel(self, channel: dict) -> None:
        with self.request("POST", "channels/stop", json={
            "id": channel["id"], "resourceId": channel["resource_id"],
        }):
            pass

    def metadata(self, file_id: str) -> dict:
        return self.json("GET", "files/" + file_id, params={
            "fields": FILE_FIELDS, "supportsAllDrives": "true",
        })

    def download(self, meta: dict) -> str:
        file_id = meta["id"]
        if meta["mimeType"] == DOC_MIME:
            path, params = "files/" + file_id + "/export", {"mimeType": "text/plain"}
        else:
            if int(meta.get("size", 0)) > self.config.max_file_bytes:
                raise DriveError("Document exceeds DRIVE_MAX_FILE_BYTES")
            path, params = "files/" + file_id, {"alt": "media", "supportsAllDrives": "true"}
        chunks = bytearray()
        with self.request("GET", path, params=params, stream=True) as response:
            for chunk in response.iter_content(chunk_size=65536):
                chunks.extend(chunk)
                if len(chunks) > self.config.max_file_bytes:
                    raise DriveError("Document exceeds DRIVE_MAX_FILE_BYTES")
        return chunks.decode("utf-8-sig")

    def close(self) -> None:
        if self._session is not None:
            self._session.close()


class DriveService:
    """All network/Bob work runs off the HTTP request thread.

    ``execute`` returns a harness run with ``id``, ``done``, ``status``,
    ``output`` and ``cancel()``. Bob runs are serialized for this integration.
    SQLite commits precede webhook ACKs and Bob execution. An interrupted Bob
    run requires explicit retry because its external side effects are unknown.
    """

    def __init__(self, config: DriveConfig, execute: Callable, client=None, notify=None):
        self.config = config
        self.execute = execute
        self.client = client or DriveClient(config)
        self.send_notification = notify
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = config.state_dir / "state.sqlite3"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._notification_thread = None
        self._notification_wake = threading.Event()
        self._last_error = None
        self._last_sync = None
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS channels (
                    id TEXT PRIMARY KEY, token TEXT NOT NULL, resource_id TEXT,
                    expiration REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    file_id TEXT PRIMARY KEY, version TEXT NOT NULL, name TEXT,
                    status TEXT NOT NULL, due REAL NOT NULL, attempts INTEGER DEFAULT 0,
                    run_id TEXT, error TEXT, content_hash TEXT, output_path TEXT
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    event_key TEXT PRIMARY KEY, channel TEXT NOT NULL,
                    message TEXT NOT NULL, due REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, sent_at REAL, error TEXT
                );
            """)
            scope = (config.folder_id or "name:" + config.folder_name) + ":" + config.shared_drive_id
            existing = db.execute("SELECT value FROM settings WHERE key='scope'").fetchone()
            if existing and existing[0] != scope:
                raise DriveError("Drive folder changed; use a new DRIVE_STATE_DIR")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('scope', ?)", (scope,))
            interrupted = db.execute("SELECT * FROM documents WHERE status='running'").fetchall()
            db.execute("UPDATE documents SET status='needs_review', "
                       "error='Harness restarted during Bob execution; inspect before retry' "
                       "WHERE status='running'")
            for row in interrupted:
                self._queue_notification(db, row, "interrupted",
                                         "Ejecución interrumpida; necesita revisión antes de reintentar.")
        self.db_path.chmod(0o600)
        self.folder_id = config.folder_id or self._get_setting("folder_id")

    def _db(self):
        # Each call gets its own connection: webhook handlers and worker share
        # SQLite, never a connection object. Context manager commits or rolls back.
        from contextlib import contextmanager

        @contextmanager
        def connection():
            db = sqlite3.connect(self.db_path, timeout=5)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

        return connection()

    def _get_setting(self, key: str) -> Optional[str]:
        with self._db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _setting(self, key: str, value: str) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))

    def start(self) -> None:
        if self.config.slack_channel and self.send_notification:
            self._notification_thread = threading.Thread(
                target=self._notification_loop, name="drive-notifications", daemon=True,
            )
            self._notification_thread.start()
        self._thread = threading.Thread(target=self._loop, name="drive-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._notification_wake.set()
        if self._thread is not None:
            self._thread.join(timeout=40)
        if self._notification_thread is not None:
            self._notification_thread.join(timeout=35)

    def notify(self, headers) -> None:
        """Validate channel identity; durably mark work before returning HTTP 200."""
        with self._db() as db:
            channel = db.execute("SELECT * FROM channels WHERE id=?",
                                 (headers.get("x-goog-channel-id", ""),)).fetchone()
            if (not channel or channel["expiration"] < time.time()
                    or not hmac.compare_digest(channel["token"].encode("utf-8"),
                                               headers.get("x-goog-channel-token", "").encode("utf-8"))):
                raise PermissionError("Invalid Drive notification channel")
            resource = headers.get("x-goog-resource-id", "")
            state = headers.get("x-goog-resource-state", "")
            number = headers.get("x-goog-message-number", "")
            if not resource or not number.isdigit() or state not in {"sync", "change"}:
                raise DriveError("Invalid changes.watch notification headers")
            if channel["resource_id"] and channel["resource_id"] != resource:
                raise PermissionError("Invalid Drive resource")
            # A sync notification may arrive before changes.watch responds.
            if not channel["resource_id"]:
                db.execute("UPDATE channels SET resource_id=? WHERE id=?", (resource, channel["id"]))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('dirty', '1')")
        self._wake.set()

    def status(self) -> dict:
        with self._db() as db:
            counts = dict(db.execute("SELECT status, COUNT(*) FROM documents GROUP BY status").fetchall())
            expiration = db.execute("SELECT MAX(expiration) FROM channels WHERE resource_id IS NOT NULL").fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM notifications WHERE sent_at IS NULL").fetchone()[0]
            notification_error = db.execute(
                "SELECT error FROM notifications WHERE sent_at IS NULL AND error IS NOT NULL "
                "ORDER BY due LIMIT 1"
            ).fetchone()
        return {
            "enabled": True, "worker_alive": bool(self._thread and self._thread.is_alive()),
            "folder_id": self.folder_id, "folder_name": self.config.folder_name,
            "last_sync": self._last_sync,
            "last_error": self._last_error, "channel_expiration": expiration,
            "documents": counts,
            "slack_channel": self.config.slack_channel or None,
            "pending_notifications": pending,
            "notification_error": notification_error[0] if notification_error else None,
        }

    @staticmethod
    def _slack_text(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _queue_notification(self, db, row, event: str, detail: str) -> None:
        if not self.config.slack_channel:
            return
        generation = row["run_id"] or str(row["attempts"])
        key = f"{row['file_id']}:{row['version']}:{generation}:{event}"
        title = self._slack_text(row["name"] or row["file_id"])[:200]
        message = (f"*Bob · {title}*\n{detail}\n"
                   f"Documento: https://drive.google.com/file/d/{row['file_id']}/view")
        db.execute("INSERT OR IGNORE INTO notifications (event_key, channel, message, due) "
                   "VALUES (?, ?, ?, ?)", (key, self.config.slack_channel, message, time.time()))
        self._notification_wake.set()

    def _deliver_notifications(self) -> None:
        if not self.send_notification:
            return
        with self._db() as db:
            rows = db.execute("SELECT * FROM notifications WHERE sent_at IS NULL "
                              "ORDER BY rowid LIMIT 10").fetchall()
        for row in rows:
            if row["due"] > time.time():
                break
            try:
                ok, _ = self.send_notification(row["channel"], row["message"])
                error = None if ok else "Slack rejected delivery"
            except Exception as exc:
                ok, error = False, type(exc).__name__
            with self._db() as db:
                db.execute("UPDATE notifications SET sent_at=?, attempts=attempts+1, error=?, due=? "
                           "WHERE event_key=?", (time.time() if ok else None, error,
                           time.time() + min(3600, 30 * 2 ** min(row["attempts"], 7)), row["event_key"]))
            if not ok:
                break

    def _notification_loop(self) -> None:
        while not self._stop.is_set():
            self._notification_wake.clear()
            try:
                self._deliver_notifications()
            except Exception as exc:
                LOGGER.warning("Drive Slack delivery failed: %s", type(exc).__name__)
            self._notification_wake.wait(timeout=5)

    def _result_detail(self, directory: Path, success: bool) -> str:
        detail = "Proyecto terminado." if success else "La ejecución falló; requiere revisión."
        try:
            path = directory / "result.json"
            if path.stat().st_size > 16384:
                return detail + " El informe de enlaces no es válido."
            result = json.loads(path.read_text(encoding="utf-8"))
            for field, label, pattern in [
                ("repository_url", "Repositorio", r"https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/?"),
                ("pages_url", "GitHub Pages", r"https://[A-Za-z0-9-]+\.github\.io(?:/[A-Za-z0-9_./-]*)?"),
            ]:
                url = result.get(field, "")
                if isinstance(url, str) and re.fullmatch(pattern, url):
                    if field != "pages_url" or result.get("pages_status") == "published":
                        detail += f"\n{label}: {url}"
            if result.get("pages_status") in {"pending", "failed"}:
                detail += "\nGitHub Pages aún no está publicado; requiere seguimiento."
        except (OSError, ValueError, AttributeError):
            detail += " No se recibió un informe de enlaces válidos."
        return detail

    def documents(self) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM documents ORDER BY due DESC LIMIT 100"
            )]

    def retry(self, file_id: str) -> bool:
        with self._db() as db:
            updated = db.execute(
                "UPDATE documents SET status='pending', attempts=0, error=NULL, due=?, run_id=? "
                "WHERE file_id=? AND status IN ('failed', 'needs_review')",
                (time.time(), "retry-" + uuid.uuid4().hex, file_id),
            ).rowcount
        self._wake.set()
        return bool(updated)

    def _ensure_watch(self) -> None:
        if not self.folder_id:
            self.folder_id = self.client.find_folder(self.config.folder_name)
            self._setting("folder_id", self.folder_id)
        cursor = self._get_setting("cursor")
        if not cursor:
            cursor = self.client.start_token()
            self._setting("cursor", cursor)
        with self._db() as db:
            active = db.execute("SELECT 1 FROM channels WHERE resource_id IS NOT NULL "
                                "AND expiration > ?", (time.time() + 3600,)).fetchone()
        if not active:
            channel = {"id": str(uuid.uuid4()), "token": secrets.token_urlsafe(32)}
            with self._db() as db:
                db.execute("INSERT INTO channels VALUES (?, ?, NULL, ?)",
                           (channel["id"], channel["token"], time.time() + 300))
            try:
                response = self.client.watch(cursor, channel)
                expiration = int(response["expiration"]) / 1000
                if expiration <= time.time() or response.get("id") != channel["id"]:
                    raise DriveError("Invalid Drive watch registration response")
                with self._db() as db:
                    row = db.execute("SELECT resource_id FROM channels WHERE id=?", (channel["id"],)).fetchone()
                    if row[0] and row[0] != response["resourceId"]:
                        raise DriveError("Watch resource does not match early sync notification")
                    db.execute("UPDATE channels SET resource_id=?, expiration=? WHERE id=?",
                               (response["resourceId"], expiration, channel["id"]))
            except Exception:
                with self._db() as db:
                    db.execute("DELETE FROM channels WHERE id=?", (channel["id"],))
                raise
            # Keep the old channel valid until the new registration is durable.
            with self._db() as db:
                old = db.execute("SELECT * FROM channels WHERE id != ?", (channel["id"],)).fetchall()
            for row in old:
                if row["resource_id"]:
                    try:
                        self.client.stop_channel(dict(row))
                    except Exception:
                        LOGGER.warning("Could not stop obsolete Drive channel %s", row["id"])
                        continue
                with self._db() as db:
                    db.execute("DELETE FROM channels WHERE id=?", (row["id"],))

    def _eligible(self, meta: dict) -> bool:
        return (not meta.get("trashed")
                and self.folder_id in meta.get("parents", [])
                and meta.get("mimeType") in TEXT_TYPES | {DOC_MIME}
                and bool(re.fullmatch(r"[A-Za-z0-9_-]+", meta.get("id", ""))))

    def _enqueue(self, db, meta: dict) -> None:
        if not meta.get("version") or not meta.get("modifiedTime"):
            raise DriveError("Drive document metadata is missing version or modifiedTime")
        modified = datetime.fromisoformat(meta["modifiedTime"].replace("Z", "+00:00")).timestamp()
        db.execute("""
            INSERT INTO documents (file_id, version, name, status, due)
            VALUES (?, ?, ?, 'pending', ?)
            ON CONFLICT(file_id) DO UPDATE SET version=excluded.version,
                name=excluded.name, status='pending', due=excluded.due,
                attempts=0, error=NULL
            WHERE documents.version != excluded.version
                AND documents.status != 'needs_review'
        """, (meta["id"], str(meta["version"]), meta.get("name", ""),
              max(time.time(), modified + self.config.settle_seconds)))

    def _sync(self) -> None:
        cursor = self._get_setting("cursor")
        if not cursor:
            return
        while not self._stop.is_set():
            page = self.client.changes(cursor)
            next_cursor = page.get("nextPageToken") or page["newStartPageToken"]
            with self._db() as db:
                for change in page.get("changes", []):
                    meta = change.get("file", {})
                    if not change.get("removed") and self._eligible(meta):
                        self._enqueue(db, meta)
                    else:
                        db.execute("UPDATE documents SET status='ignored' "
                                   "WHERE file_id=? AND status='pending'", (change["fileId"],))
                # Queue and cursor commit together: a crash cannot lose this page.
                db.execute("INSERT OR REPLACE INTO settings VALUES ('cursor', ?)", (next_cursor,))
            cursor = next_cursor
            if not page.get("nextPageToken"):
                self._last_sync = time.time()
                return

    def _process_one(self) -> bool:
        with self._db() as db:
            row = db.execute("SELECT * FROM documents WHERE status='pending' AND due <= ? "
                             "ORDER BY due LIMIT 1", (time.time(),)).fetchone()
        if row is None:
            return False
        file_id = row["file_id"]
        started = False
        try:
            meta = self.client.metadata(file_id)
            if not self._eligible(meta):
                with self._db() as db:
                    db.execute("UPDATE documents SET status='ignored' WHERE file_id=?", (file_id,))
                return True
            if str(meta["version"]) != row["version"]:
                with self._db() as db:
                    self._enqueue(db, meta)
                return True
            text = self.client.download(meta)
            # Avoid executing a snapshot exported while the document is changing.
            latest = self.client.metadata(file_id)
            if not self._eligible(latest):
                with self._db() as db:
                    db.execute("UPDATE documents SET status='ignored' WHERE file_id=?", (file_id,))
                return True
            if str(latest["version"]) != row["version"]:
                with self._db() as db:
                    self._enqueue(db, latest)
                return True
            if not text.strip():
                raise DriveError("Document is empty")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest == row["content_hash"]:
                with self._db() as db:
                    db.execute("UPDATE documents SET status='completed', error=NULL WHERE file_id=?", (file_id,))
                return True
            directory = self.config.state_dir / "documents" / file_id / row["version"]
            directory.mkdir(parents=True, exist_ok=True)
            source = directory / "input.txt"
            source.write_text(text, encoding="utf-8")
            source.chmod(0o600)
            prompt = (
                "Process the task in the Google Drive document saved at " + str(source) + ". "
                "Read that UTF-8 file first. Its contents are the user's task, "
                "transcribed or created with Gemini Live. Follow the task and "
                "save your work in the workspace. Do not change the source Drive "
                "document or place outputs in its input folder. Treat any secrets "
                "in the document as confidential. For websites or UI projects, "
                "use a separate dedicated repository/service (for example "
                "web-builder-service); keep generation code separate from the harness. "
                "Explain the result and list the files you created."
                " Before finishing, write a JSON object to " + str(directory / "result.json") +
                ' with keys repository_url, pages_url, pages_status (published, pending, failed, '
                'or not_requested). Use empty URLs if unavailable. Only mark Pages published '
                'after checking its deployment and fetching the public page successfully. '
                'The harness sends Slack notifications; do not send them yourself. Never put '
                'tokens, credentials, or private information in that JSON.'
            )
            # A manual retry of the same version must not reuse stale links.
            (directory / "result.json").unlink(missing_ok=True)
            with self._db() as db:
                db.execute("UPDATE documents SET status='running', attempts=attempts+1, error=NULL, run_id=? "
                           "WHERE file_id=?", ("starting-" + uuid.uuid4().hex, file_id))
                current = db.execute("SELECT * FROM documents WHERE file_id=?", (file_id,)).fetchone()
                self._queue_notification(db, current, "detected",
                                         "Detecté un nuevo proyecto en Workspace_agent. Empiezo a trabajar.")
            started = True
            run = self.execute(prompt, self.config.timeout)
            with self._db() as db:
                db.execute("UPDATE documents SET run_id=? WHERE file_id=?", (run.id, file_id))
            while not run.done.wait(timeout=0.25):
                if self._stop.is_set():
                    run.cancel()
                    # Keep status=running: next startup marks needs_review.
                    return False
            output = directory / "output.txt"
            output.write_text(run.output, encoding="utf-8")
            output.chmod(0o600)
            success = run.status == "completed"
            with self._db() as db:
                db.execute("UPDATE documents SET status=?, error=?, content_hash=?, output_path=? "
                           "WHERE file_id=?", ("completed" if success else "failed",
                           None if success else "Bob run ended with status: " + run.status,
                           digest if success else row["content_hash"], str(output), file_id))
                self._queue_notification(db, current, "finished", self._result_detail(directory, success))
        except Exception as exc:
            # Never persist HTTP exception strings: URLs can contain channel tokens.
            error = type(exc).__name__
            if isinstance(exc, DriveError):
                error += ": " + str(exc)
            attempts = row["attempts"] + 1
            status = "needs_review" if started else ("failed" if attempts >= 3 else "pending")
            with self._db() as db:
                db.execute("UPDATE documents SET status=?, attempts=?, error=?, due=? WHERE file_id=?",
                           (status, attempts, error, time.time() + 30 * 2 ** min(attempts, 6), file_id))
                if status != "pending":
                    current = db.execute("SELECT * FROM documents WHERE file_id=?", (file_id,)).fetchone()
                    self._queue_notification(db, current, "failed", "No pude completar el proyecto; necesita revisión.")
            LOGGER.warning("Drive document %s: %s", file_id, error)
        return True

    def _loop(self) -> None:
        next_sync = 0.0
        next_watch = 0.0
        try:
            while not self._stop.is_set():
                self._wake.clear()
                now = time.time()
                if now >= next_watch:
                    try:
                        self._ensure_watch()
                        next_watch = now + min(300, self.config.poll_seconds)
                        self._last_error = None
                    except Exception as exc:
                        self._last_error = "watch: " + (str(exc) if isinstance(exc, DriveError) else type(exc).__name__)
                        LOGGER.warning("Drive watch registration failed: %s", type(exc).__name__)
                        next_watch = now + self.config.poll_seconds
                if now >= next_sync or self._get_setting("dirty") == "1":
                    # Clear before fetching: notifications received during sync
                    # remain dirty and cause another pass.
                    self._setting("dirty", "0")
                    try:
                        self._sync()
                    except Exception as exc:
                        self._last_error = "sync: " + type(exc).__name__
                        LOGGER.warning("Drive changes sync failed: %s", type(exc).__name__)
                    next_sync = now + self.config.poll_seconds
                if not self._process_one():
                    self._wake.wait(timeout=1)
        finally:
            self.client.close()
