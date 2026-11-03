"""Offline regressions for Drive ingestion, durable queue and HTTP auth."""
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

import drive
import server


def metadata(file_id="document-1", version="1", **overrides):
    return {
        "id": file_id, "name": "Task from Gemini", "version": version,
        "mimeType": drive.DOC_MIME, "parents": ["input-folder"],
        "modifiedTime": "2026-01-01T00:00:00Z", "trashed": False,
        **overrides,
    }


def finished_run(status="completed"):
    done = threading.Event()
    done.set()
    return SimpleNamespace(id="run-1", status=status, done=done,
                           output="Task complete", cancel=Mock())


@pytest.fixture
def service(tmp_path):
    config = drive.DriveConfig(
        folder_id="input-folder",
        webhook_url="https://bob.example.com/integrations/drive/webhook",
        admin_token="a" * 64, state_dir=tmp_path / "drive", settle_seconds=0,
    )
    client = Mock()
    client.start_token.return_value = "cursor-0"
    client.metadata.return_value = metadata()
    client.download.return_value = "Build a web page."
    client.changes.return_value = {"newStartPageToken": "cursor-1", "changes": []}

    def watch(token, channel):
        return {"id": channel["id"], "resourceId": "resource-1",
                "expiration": str(int((time.time() + 6 * 86400) * 1000))}

    client.watch.side_effect = watch
    return drive.DriveService(config, Mock(return_value=finished_run()), client)


def enqueue(service, meta=None):
    with service._db() as db:
        service._enqueue(db, meta or metadata())


def channel_headers(service, state="change"):
    with service._db() as db:
        row = db.execute("SELECT * FROM channels ORDER BY expiration DESC LIMIT 1").fetchone()
    return {
        "x-goog-channel-id": row["id"], "x-goog-channel-token": row["token"],
        "x-goog-resource-id": "resource-1", "x-goog-resource-state": state,
        "x-goog-message-number": "1",
    }


def test_disabled_config_does_not_require_credentials(monkeypatch):
    monkeypatch.delenv("DRIVE_ENABLED", raising=False)
    assert drive.DriveConfig.from_env() is None


@pytest.mark.parametrize("setting,value", [
    ("DRIVE_FOLDER_ID", "https://drive.google.com/folders/folder"),
    ("DRIVE_WEBHOOK_URL", "http://bob.example.com/integrations/drive/webhook"),
    ("DRIVE_WEBHOOK_URL", "https://bob.example.com/jobs"),
    ("DRIVE_WEBHOOK_URL", "https://bob.example.com/integrations/drive/webhook?token=secret"),
    ("DRIVE_ADMIN_TOKEN", "short"), ("DRIVE_POLL_SECONDS", "0"),
    ("DRIVE_SETTLE_SECONDS", "-1"), ("DRIVE_MAX_FILE_BYTES", "0"),
    ("DRIVE_JOB_TIMEOUT", "3601"),
])
def test_invalid_config_rejected(monkeypatch, setting, value):
    monkeypatch.setenv("DRIVE_ENABLED", "true")
    monkeypatch.setenv("DRIVE_FOLDER_ID", "input-folder")
    monkeypatch.setenv("DRIVE_WEBHOOK_URL", "https://bob.example.com/integrations/drive/webhook")
    monkeypatch.setenv("DRIVE_ADMIN_TOKEN", "a" * 64)
    monkeypatch.setenv(setting, value)
    with pytest.raises(drive.DriveError):
        drive.DriveConfig.from_env()


def test_watch_bootstrap_renewal_and_early_sync(service):
    original = service.client.watch.side_effect

    def early_sync(token, channel):
        service.notify(channel_headers(service, "sync"))
        return original(token, channel)

    service.client.watch.side_effect = early_sync
    service._ensure_watch()
    assert service._get_setting("cursor") == "cursor-0"
    assert service._get_setting("dirty") == "1"
    assert service.status()["channel_expiration"] > time.time() + 86400
    service._ensure_watch()
    assert service.client.watch.call_count == 1
    with service._db() as db:
        db.execute("UPDATE channels SET expiration=?", (time.time() + 100,))
    service._ensure_watch()
    assert service.client.watch.call_count == 2
    service.client.stop_channel.assert_called_once()


def test_failed_watch_registration_preserves_cursor_and_retries(service):
    service.client.watch.side_effect = RuntimeError("registration failed")
    with pytest.raises(RuntimeError):
        service._ensure_watch()
    assert service._get_setting("cursor") == "cursor-0"
    with service._db() as db:
        assert db.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 0


@pytest.mark.parametrize("header,value,exception", [
    ("x-goog-channel-id", "unknown", PermissionError),
    ("x-goog-channel-token", "wrong", PermissionError),
    ("x-goog-resource-id", "wrong", PermissionError),
    ("x-goog-message-number", "invalid", drive.DriveError),
    ("x-goog-resource-state", "update", drive.DriveError),
])
def test_invalid_notifications_rejected(service, header, value, exception):
    service._ensure_watch()
    headers = channel_headers(service)
    headers[header] = value
    with pytest.raises(exception):
        service.notify(headers)
    service.execute.assert_not_called()


def test_expired_channel_rejected(service):
    service._ensure_watch()
    headers = channel_headers(service)
    with service._db() as db:
        db.execute("UPDATE channels SET expiration=0")
    with pytest.raises(PermissionError):
        service.notify(headers)


def test_notifications_are_fast_durable_wakeups_without_network(service):
    service._ensure_watch()
    headers = channel_headers(service)
    service.client.reset_mock()
    service.notify(headers)
    service.notify(headers)  # Retransmission and non-contiguous numbers are safe.
    assert service._get_setting("dirty") == "1"
    service.client.changes.assert_not_called()
    service.execute.assert_not_called()


def test_paginated_changes_scope_and_cursor_are_persisted(service):
    service._setting("cursor", "cursor-0")
    service.client.changes.side_effect = [
        {"nextPageToken": "page-2", "changes": [
            {"fileId": "document-1", "file": metadata()},
            {"fileId": "outside", "file": metadata("outside", parents=["other"])},
            {"fileId": "pdf", "file": metadata("pdf", mimeType="application/pdf")},
            {"fileId": "trashed", "file": metadata("trashed", trashed=True)},
            {"fileId": "removed", "removed": True},
        ]},
        {"newStartPageToken": "cursor-2", "changes": [
            {"fileId": "text", "file": metadata("text", mimeType="text/plain")},
        ]},
    ]
    service._sync()
    assert {doc["file_id"] for doc in service.documents()} == {"document-1", "text"}
    assert service._get_setting("cursor") == "cursor-2"
    assert [call.args[0] for call in service.client.changes.call_args_list] == ["cursor-0", "page-2"]


def test_changes_and_cursor_rollback_together_on_bad_page(service):
    service._setting("cursor", "cursor-0")
    bad = metadata("bad", modifiedTime="bad timestamp")
    service.client.changes.return_value = {
        "newStartPageToken": "cursor-1", "changes": [
            {"fileId": "document-1", "file": metadata()}, {"fileId": "bad", "file": bad},
        ],
    }
    with pytest.raises(ValueError):
        service._sync()
    assert service.documents() == []
    assert service._get_setting("cursor") == "cursor-0"


def test_duplicate_and_reordered_webhooks_do_not_repeat_bob(service):
    enqueue(service)
    service._process_one()
    enqueue(service)
    assert not service._process_one()
    service.execute.assert_called_once()
    doc = service.documents()[0]
    assert doc["status"] == "completed" and doc["run_id"] == "run-1"
    assert (service.config.state_dir / "documents/document-1/1/input.txt").read_text() == "Build a web page."
    assert "input.txt" in service.execute.call_args.args[0]
    assert "Build a web page." not in service.execute.call_args.args[0]
    assert "web-builder-service" in service.execute.call_args.args[0]
    assert (service.config.state_dir / "documents/document-1/1/output.txt").read_text() == "Task complete"


def test_metadata_only_update_skips_bob_but_new_content_runs(service):
    enqueue(service)
    service._process_one()
    service.client.metadata.return_value = metadata(version="2")
    enqueue(service, metadata(version="2"))
    service._process_one()
    assert service.execute.call_count == 1
    service.client.metadata.return_value = metadata(version="3")
    service.client.download.return_value = "A different task"
    enqueue(service, metadata(version="3"))
    service._process_one()
    assert service.execute.call_count == 2


def test_settling_document_is_not_run_early(service):
    meta = metadata(modifiedTime="2099-01-01T00:00:00Z")
    enqueue(service, meta)
    assert not service._process_one()
    service.client.metadata.assert_not_called()


@pytest.mark.parametrize("during_download", [False, True])
def test_changed_document_is_requeued_before_execution(service, during_download):
    enqueue(service)
    newer = metadata(version="2")
    if during_download:
        service.client.metadata.side_effect = [metadata(), newer]
    else:
        service.client.metadata.return_value = newer
    service._process_one()
    service.execute.assert_not_called()
    doc = service.documents()[0]
    assert doc["status"] == "pending" and doc["version"] == "2"


def test_document_moved_out_before_execution_is_ignored(service):
    enqueue(service)
    service.client.metadata.return_value = metadata(parents=["other-folder"])
    service._process_one()
    service.execute.assert_not_called()
    assert service.documents()[0]["status"] == "ignored"


def test_download_errors_backoff_then_fail_without_launching_bob(service):
    enqueue(service)
    service.client.download.side_effect = RuntimeError("secret-token must not be stored")
    for attempt in range(3):
        with service._db() as db:
            db.execute("UPDATE documents SET due=0")
        service._process_one()
        doc = service.documents()[0]
        assert doc["attempts"] == attempt + 1
        assert "secret-token" not in doc["error"]
    assert doc["status"] == "failed"
    service.execute.assert_not_called()
    assert service.retry("document-1")
    assert service.documents()[0]["status"] == "pending"


def test_failed_bob_does_not_automatically_repeat_side_effects(service):
    enqueue(service)
    service.execute.return_value = finished_run("failed")
    service._process_one()
    assert service.documents()[0]["status"] == "failed"
    assert not service._process_one()
    assert service.retry("document-1")
    assert not service.retry("document-1")


def test_queue_survives_restart_and_interrupted_bob_requires_review(service):
    enqueue(service)
    enqueue(service, metadata("document-2"))
    with service._db() as db:
        db.execute("UPDATE documents SET status='running', run_id='old-run' WHERE file_id='document-1'")
    restarted = drive.DriveService(service.config, service.execute, service.client)
    docs = {doc["file_id"]: doc for doc in restarted.documents()}
    assert docs["document-1"]["status"] == "needs_review"
    assert docs["document-2"]["status"] == "pending"
    enqueue(restarted, metadata(version="2"))
    assert next(doc for doc in restarted.documents() if doc["file_id"] == "document-1")["status"] == "needs_review"
    assert restarted.retry("document-1")


def test_changing_folder_does_not_reuse_cursor(service):
    with pytest.raises(drive.DriveError, match="folder changed"):
        drive.DriveService(replace(service.config, folder_id="other"), service.execute)


def test_workspace_agent_folder_is_resolved_once_and_persisted(service, tmp_path):
    config = replace(service.config, folder_id="", state_dir=tmp_path / "by-name")
    service.client.find_folder.return_value = "resolved-folder"
    discovered = drive.DriveService(config, service.execute, service.client)
    discovered._ensure_watch()
    service.client.find_folder.assert_called_once_with("Workspace_agent")
    assert discovered.status()["folder_id"] == "resolved-folder"
    restarted = drive.DriveService(config, service.execute, service.client)
    restarted._ensure_watch()
    assert service.client.find_folder.call_count == 1
    assert restarted._eligible(metadata(parents=["resolved-folder"]))
    assert not restarted._eligible(metadata())


@pytest.mark.parametrize("files,next_page", [([], None), ([{"id": "a"}, {"id": "b"}], None),
                                                ([{"id": "a"}], "more")])
def test_folder_discovery_rejects_missing_or_ambiguous_names(service, files, next_page):
    client = drive.DriveClient(service.config)
    with patch.object(client, "json", return_value={"files": files, "nextPageToken": next_page}):
        with pytest.raises(drive.DriveError):
            client.find_folder("Workspace_agent")


def test_folder_discovery_uses_exact_name_query(service):
    client = drive.DriveClient(service.config)
    with patch.object(client, "json", return_value={"files": [{"id": "folder-123"}]}) as request:
        assert client.find_folder("Workspace_agent") == "folder-123"
    query = request.call_args.kwargs["params"]["q"]
    assert "name = 'Workspace_agent'" in query
    assert drive.FOLDER_MIME in query


def test_shutdown_cancels_bob_and_preserves_unknown_outcome(service):
    enqueue(service)
    running = SimpleNamespace(id="run-2", status="running", done=threading.Event(), cancel=Mock())
    service.execute.return_value = running
    service._stop.set()
    assert not service._process_one()
    running.cancel.assert_called_once()
    assert service.documents()[0]["status"] == "running"


@pytest.fixture
def api(service, monkeypatch):
    monkeypatch.setattr(server.app.state, "drive", service, raising=False)
    return TestClient(server.app)


def test_webhook_http_200_without_bob_or_google_request(api, service):
    service._ensure_watch()
    response = api.post("/integrations/drive/webhook", headers=channel_headers(service))
    assert response.status_code == 200
    assert response.content == b""
    service.client.changes.assert_not_called()
    service.execute.assert_not_called()


def test_webhook_http_rejects_spoofed_channel(api, service):
    assert api.post("/integrations/drive/webhook").status_code == 403


@pytest.mark.parametrize("path", ["status", "documents", "documents/document-1/retry"])
def test_admin_endpoints_require_dedicated_token(api, path):
    method = api.post if path.endswith("retry") else api.get
    assert method("/integrations/drive/" + path).status_code == 401


def test_admin_status_hides_channel_and_admin_tokens(api, service):
    service._ensure_watch()
    response = api.get("/integrations/drive/status", headers={
        "Authorization": "Bearer " + service.config.admin_token,
    })
    assert response.status_code == 200
    assert service.config.admin_token not in response.text
    assert channel_headers(service)["x-goog-channel-token"] not in response.text


def test_admin_retry_is_explicit_and_validated(api, service):
    enqueue(service)
    headers = {"Authorization": "Bearer " + service.config.admin_token}
    path = "/integrations/drive/documents/document-1/retry"
    assert api.post(path, headers=headers).status_code == 409
    with service._db() as db:
        db.execute("UPDATE documents SET status='needs_review'")
    assert api.post(path, headers=headers).status_code == 202
    assert service.documents()[0]["status"] == "pending"


def test_disabled_integration_http_returns_503(monkeypatch):
    monkeypatch.setattr(server.app.state, "drive", None, raising=False)
    api = TestClient(server.app)
    assert api.post("/integrations/drive/webhook").status_code == 503


def test_lifespan_starts_and_stops_drive_worker(service, monkeypatch):
    monkeypatch.setattr(drive.DriveConfig, "from_env", Mock(return_value=service.config))
    with patch.object(server.schedules, "sync"), patch.object(drive, "DriveService") as cls:
        with TestClient(server.app):
            cls.assert_called_once_with(service.config, server._execute_drive_task,
                                        notify=server._notify_drive_slack)
            cls.return_value.start.assert_called_once()
        cls.return_value.stop.assert_called_once()


@pytest.mark.parametrize("mime,path,params", [
    (drive.DOC_MIME, "files/document-1/export", {"mimeType": "text/plain"}),
    ("text/plain", "files/document-1", {"alt": "media", "supportsAllDrives": "true"}),
])
def test_download_exports_docs_and_downloads_text(service, mime, path, params):
    client = drive.DriveClient(service.config)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b"\xef\xbb\xbfhello ", "mundo".encode()]
    with patch.object(client, "request", return_value=response) as request:
        assert client.download(metadata(mimeType=mime)) == "hello mundo"
    request.assert_called_once_with("GET", path, params=params, stream=True)


def test_streaming_download_stops_at_size_limit(service):
    client = drive.DriveClient(replace(service.config, max_file_bytes=5))
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b"123", b"456"]
    with patch.object(client, "request", return_value=response):
        with pytest.raises(drive.DriveError, match="exceeds"):
            client.download(metadata())
    response.__exit__.assert_called_once()


def test_shared_drive_parameters(service):
    client = drive.DriveClient(replace(service.config, shared_drive_id="team-drive"))
    assert client.change_params("cursor")["driveId"] == "team-drive"
    assert client.change_params("cursor")["pageToken"] == "cursor"


def test_user_adc_credentials_are_rejected(service):
    from google.oauth2.credentials import Credentials

    client = drive.DriveClient(service.config)
    with patch("google.auth.default", return_value=(Credentials("user-token"), "project")):
        with pytest.raises(drive.DriveError, match="service-account"):
            _ = client.session


def test_drive_key_preserves_adc_for_other_integrations(service):
    client = drive.DriveClient(replace(service.config, credentials_file="/private/drive-key.json"))
    with patch("google.auth.default") as adc, patch(
        "google.oauth2.service_account.Credentials.from_service_account_file"
    ) as key, patch("google.auth.transport.requests.AuthorizedSession") as session:
        assert client.session is session.return_value
    adc.assert_not_called()
    key.assert_called_once_with("/private/drive-key.json", scopes=[
        "https://www.googleapis.com/auth/drive.readonly",
    ])


def test_drive_task_uses_harness_registry_and_single_attempt(monkeypatch):
    monkeypatch.setenv("BOBSHELL_API_KEY", "test-key")
    with patch.object(server, "_spawn", side_effect=lambda run: run), patch.object(server.os, "makedirs"):
        run = server._execute_drive_task("Read input.txt", 120)
    assert isinstance(run, server.HarnessRun)
    assert run.max_attempts == 1 and run.timeout == 120
    assert run.base_prompt == "Read input.txt"


def test_worker_catches_up_without_webhook_even_when_watch_registration_fails(service):
    executed = threading.Event()
    service.client.watch.side_effect = RuntimeError("webhook temporarily unavailable")
    service.client.changes.return_value = {
        "newStartPageToken": "cursor-next",
        "changes": [{"fileId": "document-1", "file": metadata()}],
    }

    def execute(prompt, timeout):
        executed.set()
        return finished_run()

    service.execute.side_effect = execute
    service.start()
    try:
        assert executed.wait(timeout=3), "Worker did not recover changes by polling"
    finally:
        service.stop()
    assert not service._thread.is_alive()
    assert service._get_setting("cursor") == "cursor-next"
    assert service.documents()[0]["status"] == "completed"
    service.client.close.assert_called_once()


def enable_notifications(service):
    service.config = replace(service.config, slack_channel="C_PROJECTS")
    service.send_notification = Mock(return_value=(True, ""))
    return service.send_notification


def test_notifications_report_detection_completion_and_published_links(service):
    import json

    sender = enable_notifications(service)
    enqueue(service)

    def execute(prompt, timeout):
        directory = service.config.state_dir / "documents/document-1/1"
        (directory / "result.json").write_text(json.dumps({
            "repository_url": "https://github.com/BrUn3y/new-project",
            "pages_url": "https://brun3y.github.io/new-project/",
            "pages_status": "published",
        }))
        assert "result.json" in prompt and "do not send them yourself" in prompt
        return finished_run()

    service.execute.side_effect = execute
    service._process_one()
    service._deliver_notifications()
    assert sender.call_count == 2
    assert "Detecté un nuevo proyecto" in sender.call_args_list[0].args[1]
    final = sender.call_args_list[1].args[1]
    assert "Proyecto terminado" in final
    assert "https://github.com/BrUn3y/new-project" in final
    assert "https://brun3y.github.io/new-project/" in final
    enqueue(service)
    assert not service._process_one()
    service._deliver_notifications()
    assert sender.call_count == 2
    assert service.status()["pending_notifications"] == 0


def test_slack_failure_retries_after_restart_without_rerunning_bob(service):
    sender = enable_notifications(service)
    sender.return_value = (False, "sensitive error must not be stored")
    enqueue(service)
    service._process_one()
    service._deliver_notifications()
    assert sender.call_count == 1
    assert service.status()["pending_notifications"] == 2
    assert service.status()["notification_error"] == "Slack rejected delivery"
    restarted = drive.DriveService(service.config, service.execute, service.client, notify=sender)
    sender.return_value = (True, "")
    with restarted._db() as db:
        db.execute("UPDATE notifications SET due=0")
    restarted._deliver_notifications()
    assert restarted.status()["pending_notifications"] == 0
    assert service.execute.call_count == 1
    assert sender.call_count == 3


def test_manual_retry_gets_distinct_slack_events(service):
    sender = enable_notifications(service)
    service.execute.return_value = finished_run("failed")
    enqueue(service)
    service._process_one()
    service._deliver_notifications()
    assert "falló" in sender.call_args.args[1]
    assert service.retry("document-1")
    service.execute.return_value = finished_run()
    service._process_one()
    service._deliver_notifications()
    assert sender.call_count == 4


@pytest.mark.parametrize("result", [
    {"repository_url": "https://github.com/u/r?token=secret",
     "pages_url": "https://evil.example/x", "pages_status": "published"},
    {"pages_url": "https://u.github.io/r/", "pages_status": "pending"},
    ["not an object"],
])
def test_result_rejects_unsafe_urls_and_does_not_claim_pending_pages_live(service, tmp_path, result):
    import json

    (tmp_path / "result.json").write_text(json.dumps(result))
    detail = service._result_detail(tmp_path, True)
    assert "secret" not in detail and "evil.example" not in detail
    assert "https://u.github.io/r/" not in detail


def test_notification_escapes_mentions_and_does_not_include_raw_bob_output(service):
    sender = enable_notifications(service)
    enqueue(service, metadata(name="<!channel> project"))
    service.execute.return_value.output = "PRIVATE_SECRET_DO_NOT_SEND"
    service._process_one()
    service._deliver_notifications()
    messages = str(sender.call_args_list)
    assert "<!channel>" not in messages and "&lt;!channel&gt;" in messages
    assert "PRIVATE_SECRET" not in messages


def test_interrupted_project_notifies_on_upgrade_and_only_once(service):
    enable_notifications(service)
    enqueue(service)
    with service._db() as db:
        db.execute("UPDATE documents SET status='running',run_id='old-run'")
    drive.DriveService(service.config, service.execute, service.client,
                      notify=service.send_notification)
    second = drive.DriveService(service.config, service.execute, service.client,
                               notify=service.send_notification)
    second._deliver_notifications()
    service.send_notification.assert_called_once()
    assert "interrumpida" in service.send_notification.call_args.args[1]


def test_detection_is_delivered_while_bob_is_still_working(service):
    sender = enable_notifications(service)
    detected = threading.Event()
    finished = threading.Event()
    done = threading.Event()
    running = SimpleNamespace(id="slow-run", status="completed", done=done,
                              output="done", cancel=Mock())
    service.execute.return_value = running
    service.client.changes.return_value = {
        "newStartPageToken": "next",
        "changes": [{"fileId": "document-1", "file": metadata()}],
    }

    def send(channel, message):
        if "Detecté" in message:
            detected.set()
        elif "Proyecto terminado" in message:
            finished.set()
        return True, ""

    sender.side_effect = send
    service.start()
    try:
        assert detected.wait(3)
        assert not done.is_set() and not finished.is_set()
        done.set()
        assert finished.wait(3)
    finally:
        done.set()
        service.stop()
    assert sender.call_count == 2
