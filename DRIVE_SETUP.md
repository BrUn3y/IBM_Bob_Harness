# Gemini Live → Workspace_agent → IBM Bob

The optional Drive worker watches changes accessible to a service account and
processes Google Docs and UTF-8 `.txt`/Markdown files directly inside
**Workspace_agent**. A document contains the task Bob should perform. Website
and UI generation belongs in its own repository/service (for example
`web-builder-service`), keeping the harness focused on execution.

## Behavior

1. Resolve the exact folder name `Workspace_agent` to one accessible folder ID.
   If there are duplicates, set `DRIVE_FOLDER_ID` explicitly. The resolved ID
   is persisted, so renaming the folder does not switch the input source.
2. Get and persist a Drive changes cursor, then register `changes.watch`.
   This starts with **future changes**, not a bulk execution of existing files.
   Edit an existing document after activation to submit it.
3. Validate the webhook's channel ID, random channel token, resource ID and
   expiration; commit a wake-up signal to SQLite and return HTTP 200 immediately.
4. Read all pages of `changes.list`, filtering by the folder's direct parent ID
   and supported MIME types. Queue writes and cursor advancement commit together.
5. Wait for the settling interval, fetch the current version, download/export
   plain text, recheck its version, and start one Bob harness run.
6. Save the input and result under
   `/workspace/drive/documents/<file-id>/<version>/input.txt` and `output.txt`.
   The Bob run also appears under `/jobs` while retained by the in-memory registry.

The worker handles one document at a time. Duplicate notifications and unchanged
content do not create additional runs. Changes to document text create new work.
The settling interval is a quiet period, **not** a Gemini completion signal; save
or move a finished document into the folder when you want a reliable handoff.
Subfolders, PDFs, Word files, shortcuts and non-UTF-8 files are not processed.
Outputs are local artifacts; the integration does not modify the source in Drive.

The worker renews six-day channels at least one hour before expiry and polls
every 60 seconds to recover missed notifications. It resumes the saved cursor
after restarts. Run one API process/replica per state directory (the supplied
entrypoint already does this); do not use multiple Uvicorn workers with it.

## Service account and Drive

1. Enable **Google Drive API** in the Google Cloud project.
2. Create a dedicated service account for Drive ingestion. It does not need
   project Owner/Editor roles to read a shared folder in Drive.
3. Share **Workspace_agent** with its `...iam.gserviceaccount.com` email as
   **Viewer**. Anyone allowed to write into that folder can submit work to Bob;
   keep its writers limited to the intended Gemini/user workflow.
4. Authenticate with either:
   - A service-account JSON key mounted read-only using the optional compose
     override below and `DRIVE_SERVICE_ACCOUNT_FILE`; never put the key inside
     the image or commit it. This setting is specific to Drive and preserves
     the ADC identity used by other integrations, such as Cloud Storage.
   - The VM's attached service account via Application Default Credentials,
     provided the VM's OAuth access scopes allow `drive.readonly` and the
     metadata server is reachable from the container. A `cloud-platform` scope
     alone is not a substitute for Drive API scopes.
5. If the folder belongs to a **Shared Drive**, also set `DRIVE_SHARED_DRIVE_ID`.
   An ordinary folder in My Drive does not need that setting.

User OAuth ADC is deliberately rejected. Google Docs are exported with
`files.export` (`text/plain`); ordinary text files use `files.get?alt=media`.
Both downloads are bounded by `DRIVE_MAX_FILE_BYTES` (1 MiB by default).

## Environment and HTTPS

Add these settings to the deployment's `.env`:

```dotenv
DRIVE_ENABLED=true
DRIVE_FOLDER_NAME=Workspace_agent
DRIVE_FOLDER_ID=
DRIVE_WEBHOOK_URL=https://YOUR-HTTPS-DOMAIN/integrations/drive/webhook
DRIVE_ADMIN_TOKEN=REPLACE-WITH-A-RANDOM-SECRET
DRIVE_CREDENTIALS_FILE=./secrets/drive-service-account.json
```

Generate the admin token locally on the VM with `openssl rand -hex 32`. It is
separate from Bob's IBM key and the per-channel token sent by Google.

Expose **only** `POST /integrations/drive/webhook` on that HTTPS domain with a
publicly trusted certificate. Forward it to port 8080, preserving the
`X-Goog-*` headers. The existing harness execution endpoints have no general
authentication: keep port 8080 private/firewalled and use SSH for administration.
An Nginx server with TLS already configured can use:

```nginx
location = /integrations/drive/webhook {
    limit_except POST { deny all; }
    proxy_pass http://127.0.0.1:8080;
}
location / { return 404; }
```

For a JSON-key deployment, place the key in `secrets/drive-service-account.json`
with restrictive file permissions and run:

```bash
podman compose -f docker-compose.yml -f docker-compose.drive.yml up --build -d
```

For VM metadata credentials use the normal `podman compose up --build -d`.
Docker users can replace `podman` with `docker`. The key override is optional;
the default compose stack continues to work with Drive disabled.

### Native systemd deployments

For a harness running directly in a Python virtual environment, install the
updated requirements in that environment and set the same Drive variables in
the service's existing environment file. Set `DRIVE_SERVICE_ACCOUNT_FILE`
to the real VM path of the service-account JSON (no container mount is needed)
and `DRIVE_STATE_DIR` to a writable persistent directory, for example
`/home/brun3y/IBM_Bob_Harness/workspace/drive`.

Keep the deployment's existing Bob working directory and runtime integrations.
Point the HTTPS proxy to the actual API port (the `ibm-bob` VM uses 8000).
Run the offline tests before restarting `bob-harness.service`; verify both API
and Slack process status after the restart. Do not print the environment file,
service-account private key or OAuth tokens while diagnosing the service.

## Inspect and retry

Run these on the VM (with `DRIVE_ADMIN_TOKEN` available in the shell):

```bash
curl -fsS http://localhost:8080/integrations/drive/status \
  -H "Authorization: Bearer $DRIVE_ADMIN_TOKEN"
curl -fsS http://localhost:8080/integrations/drive/documents \
  -H "Authorization: Bearer $DRIVE_ADMIN_TOKEN"
```

Status reports worker liveness, resolved folder ID, channel expiration, sync
time, error category and document counts. Document records retain the Bob run
ID, current version, state and output path. Channel secrets are never returned.

Download failures retry up to three times with backoff. A failed/cancelled Bob
run stays `failed`, and a restart during execution becomes `needs_review`:
the task may already have caused side effects. After reviewing its saved output
and work, explicitly retry with:

```bash
curl -fsS -X POST \
  http://localhost:8080/integrations/drive/documents/FILE_ID/retry \
  -H "Authorization: Bearer $DRIVE_ADMIN_TOKEN"
```

Successful and pending documents cannot be retried through this endpoint.
An additional edit to a failed document can submit a new version; a
`needs_review` document always requires explicit review/retry first.

## Backup and rollback

Before updating a live VM, record the active container/image and copy its
deployment, `.env`, service-account credentials, schedules and workspace to a
restricted backup directory **outside the deployment directory**. Save the
current container image too. Wait for active jobs to finish before taking the
backup; a VM disk snapshot provides a stronger restore point for the whole VM.
Never commit or publish these backups because they contain secrets and user data.

Build the new image before replacing the container. Keep the old image and
deployment intact until the new health check and a Drive-to-Bob task succeed.
For rollback, stop the new container, restore the old deployment/image and use
its original compose command. Do not overwrite newer workspace files without
reviewing them. Disabling `DRIVE_ENABLED` stops further ingestion at next restart;
the saved cursor allows a later resume. Changing input folder requires a new
`DRIVE_STATE_DIR`, protecting against reusing another folder's cursor/queue.

No claim of exactly-once external side effects is made: a process may terminate
after Bob has acted but before its result is committed. `needs_review` prevents
automatic repetition of that uncertain run.

## Validation

```bash
cd api
pip install -r requirements-dev.txt
pytest -v
```

The suite mocks Drive and Bob. After deployment, check `/health`, authenticated
Drive status (`last_sync`, channel expiration and folder ID), then create a
small Google Doc in **Workspace_agent** with a harmless task such as writing
`drive-smoke-test.txt` in the workspace. Confirm a completed document record and
the saved output. This live check requires real credentials and the HTTPS route.

## Slack project notifications

Set `DRIVE_SLACK_CHANNEL` to the destination channel ID (or use
`SLACK_DEFAULT_CHANNEL`) and invite the configured Slack bot to that channel.
The harness posts a detection message when a stable, changed document starts
execution, then a completion, failure or interrupted-run message. Unchanged
content does not generate a second project notification.

Notifications are stored transactionally in SQLite and delivered in order by a
separate worker. Slack failures retry with backoff, including after restarts,
without rerunning Bob. Delivery is at least once: a crash after Slack accepts a
message but before SQLite records success can duplicate that message. Inspect
`pending_notifications` and `notification_error` on the authenticated status
endpoint. A missing channel disables notifications.

Bob writes `result.json` alongside `input.txt` and `output.txt`, containing
`repository_url`, `pages_url`, and `pages_status` (`published`, `pending`, `failed`,
or `not_requested`). The prompt requires checking deployment and fetching the
public page before reporting `published`. Only validated GitHub/Pages URLs
are included in Slack; raw transcripts and document contents are not posted.
Missing/invalid reports are stated explicitly, and pending/failed Pages are
reported as requiring follow-up. Slack delivery success is separate from Bob's
execution status.
