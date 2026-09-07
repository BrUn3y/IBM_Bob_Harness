# IBM Bob Harness

<p align="center">
  <img src="https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExendtcTVyMmRhejk3MngzNTMxdnk1NWxkd3dhcnJzYnFhb3N3enl4dSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/V5Zao1FEKouvd4p2Wd/giphy.gif" alt="Bob Harness" width="480">
</p>

A container that runs **Bob Shell** (IBM) autonomously, with a
**custom unrestricted mode**, a **REST API** to consume it programmatically, an
**orchestration loop** that verifies results and retries until they pass, and a
**bidirectional Slack bot**.

> Bob Shell has **no** native server mode. This project wraps its headless
> `bob run --accept-license --mode unrestricted-dev "<prompt>"` invocation and adds a
> verify/retry loop on top (API version `1.4.0`).

## What's included

| File | Role |
|---|---|
| `Dockerfile` | Ubuntu 24.04 + Node 22 + pinned Bob Shell + REST wrapper + `HEALTHCHECK` |
| `docker-compose.yml` | Orchestration: single container (`serve-all` = API + Slack bot), port 8080, `workspace/` volume, `.env`, healthcheck |
| `entrypoint.sh` | Validates the env, accepts the license, starts the API / bot / CLI |
| `.bob/custom_modes.yaml` | `unrestricted-dev` mode: full access (read/edit/command/browser/mcp) |
| `.bob/rules-unrestricted-dev/AGENT.md` | Persistent context/rules for the mode (loaded by Bob at runtime) |
| `api/server.py` | FastAPI app that shells out to `bob` (invoke / jobs / run / stream) |
| `api/slack_bot.py` | Bidirectional Slack bot (Socket Mode) that manages cancellable `/jobs` |
| `api/schedules.py` | Cron scheduler: persisted registry + root crontab generation |
| `slack/manifest.yaml` | Slack App manifest (scopes + `message.channels` + Socket Mode) |
| `api/test_server.py` / `test_slack_bot.py` | Unit tests (mock `subprocess`/network, offline) |
| `api/requirements.txt` / `requirements-dev.txt` | Runtime / test dependencies |
| `.env` | Holds `BOBSHELL_API_KEY` + Slack tokens (**gitignored, never committed**) |

### Where the `.bob` config lives

There is a single source of truth for Bob's config — the `.bob/` directory in
this repo:

```
.bob/
├── custom_modes.yaml              # the unrestricted-dev mode ("settings")
└── rules-unrestricted-dev/
    └── AGENT.md                   # persistent context/rules for that mode
```

The `Dockerfile` copies it verbatim to the **container root**: `/.bob/`. Bob runs
with its working directory set to `/` (see `BOB_WORKDIR` below), so `/.bob/` is
the **project-level** config for the *whole* container — that's why Bob governs
the entire filesystem, not just `/workspace`. This has been verified end to end:
Bob reads `/.bob/rules-unrestricted-dev/AGENT.md` at runtime.

> **Not the same as `/root/.bob/`.** At startup Bob auto-creates its own
> runtime state under `/root/.bob/` (`settings.json` with the license/auth,
> `installation_id`, `trustedFolders.json`, `tmp/`). That directory is managed
> by Bob itself and holds **none** of our config — edit `.bob/` in the repo, not
> `/root/.bob/`. To pick up changes, rebuild the image.

## Endpoints at a glance

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + resolved config |
| `POST` | `/invoke` | Run one prompt synchronously, return full output |
| `POST` | `/jobs` | Start a prompt as a background job → `{id}` |
| `POST` | `/run` | **Orchestrated** run: execute → verify → retry → `{id}` |
| `GET` | `/jobs` | List runs/jobs |
| `GET` | `/jobs/{id}` | Status + output (+ `attempts` for `/run`) |
| `DELETE` | `/jobs/{id}` | Cancel an active job or orchestrated run |
| `GET` | `/jobs/{id}/stream` | Stream a run's output live (SSE) |
| `POST` | `/stream` | Start a job **and** stream it in one request (SSE) |
| `POST` | `/schedules` | Register a recurring run (cron) → `{schedule}` |
| `GET` | `/schedules` | List schedules |
| `GET` | `/schedules/{id}` | One schedule (+ last run info) |
| `DELETE` | `/schedules/{id}` | Remove a schedule |
| `POST` | `/schedules/{id}/run` | Fire a schedule now (curled by cron each tick) |
| `GET` | `/docs` | Swagger UI (auto-generated) |

---

## How to start (quickstart)

Get the container up in three steps. Requires Podman (or Docker) installed.

```bash
# 1. Configure secrets: copy the template and fill in your keys.
cp .env.example .env
#    - Paste your Bob API key into BOBSHELL_API_KEY (see §1 to create one).
#    - (Optional, for Slack) paste SLACK_BOT_TOKEN + SLACK_APP_TOKEN (see §4).

# 2. Build the image and start the container (REST API + Slack bot).
podman compose up --build
#    Add -d to run it detached in the background:
#    podman compose up --build -d

# 3. Check it's alive.
curl http://localhost:8080/health
```

The API is now at **`http://localhost:8080`** (Swagger UI at `/docs`). If you set
the Slack tokens, the bot connects automatically and replies in any channel it's
invited to.

**Managing the container**

```bash
podman compose logs -f bob   # follow logs (watch the API + Slack bot start up)
podman compose ps            # show status / health
podman compose down          # stop and remove the container
podman compose restart bob   # restart after changing .env
podman compose up --build    # rebuild after editing code or .bob/ config
```

> **API only (no Slack)?** Override the command to skip the bot:
> `podman compose run --rm --service-ports bob serve`
> (or change `command: ["serve-all"]` to `["serve"]` in `docker-compose.yml`).

> Prefer Docker? Replace `podman` with `docker` in every command above — the
> compose file and image build are identical. See the note under §2.

---

## 1. Configure the API key

### Get a Bob API key

The harness authenticates Bob in headless mode with `BOBSHELL_API_KEY`. To
create one:

1. Go to **[https://bob.ibm.com/](https://bob.ibm.com/)** and sign in with your IBMid.
2. Open the **Admin** tab in the top navigation.
3. In the left sidebar, pick your **Workspace** (e.g. `IBM Internal`) and click
   **API Keys**.
4. Click **Create +**, give the key a **Name** (e.g. `mac`) and a **Scope**
   (`General` is fine), then confirm.
5. **Copy the generated key immediately** — it starts with `bob_prod_...` and is
   shown only once. You can later revoke it from the same **API Keys** table
   (each row shows Name, Scope, Date created, and Status: Active/Expired/Revoked).

### Put it in `.env`

```bash
cp .env.example .env   # then paste your key into BOBSHELL_API_KEY
```

The key already lives in `.env` in this repo; replace it with your own if needed.

## 2. Build and run

```bash
podman compose up --build
```

The API is served at `http://localhost:8080`. The Bob Shell version is pinned
via the `BOB_VERSION` build arg (default `2.0.1`) for reproducible builds — bump
it in `docker-compose.yml` to upgrade.

> **Note:** this machine has no Docker daemon, only Podman — so every command
> here uses `podman compose ...` / `podman run ...`. Docker works too: just swap
> `podman` for `docker`. (Podman ignores the image `HEALTHCHECK`, so a
> compose-level healthcheck is defined as well.)

---

## 3. How to consume it (REST API)

### `GET /health` — liveness + resolved config

```bash
curl http://localhost:8080/health
```

```json
{
  "status": "ok",
  "bob_present": true,
  "default_mode": "unrestricted-dev",
  "default_workdir": "/",
  "api_key_set": true
}
```

### `POST /invoke` — run a single task (synchronous)

Runs one Bob prompt and returns the combined output. Runs in YOLO +
`unrestricted-dev` by default, so Bob can create, edit, and execute files
anywhere in the container (the default `workdir` is `/`) without asking for
confirmation.

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | (required) | The task for Bob |
| `yolo` | bool | `true` | Auto-approve all tool calls |
| `mode` | string | `unrestricted-dev` | Custom mode slug (`--mode`) |
| `workdir` | string | `/` | Working directory for the run (`/` = whole container) |
| `timeout` | int | `600` | Max seconds before abort (1–3600) |

**Example — curl**

```bash
curl -s http://localhost:8080/invoke \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Create a file hello.py that prints \"Hello from Bob\" and run it"}'
```

**Response**

```json
{
  "ok": true,
  "exit_code": 0,
  "output": "...Hello from Bob...",
  "error": "",
  "command": ["bob", "run", "--accept-license", "--mode", "unrestricted-dev", "..."]
}
```

Bob works from `/` by default, so it can touch the whole container. Only files
written under `/workspace` show up in `./workspace` on the host (it's the mounted
volume); edits elsewhere are ephemeral and vanish when the container is recreated.

**Example — Python**

```python
import requests

r = requests.post("http://localhost:8080/invoke", json={
    "prompt": "Refactor @app.py and add tests",
    "timeout": 900,
})
data = r.json()
print(data["ok"], data["exit_code"])
print(data["output"])
```

**Example — JavaScript (fetch)**

```js
const res = await fetch("http://localhost:8080/invoke", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "List the files in the workspace" }),
});
const data = await res.json();
console.log(data.output);
```

### `POST /jobs` — run a task asynchronously

For long tasks, start a background job and poll it instead of blocking. Accepts
the same body as `/invoke`.

```bash
# Start -> returns {"id": "...", "status": "running"} (HTTP 202)
JID=$(curl -s http://localhost:8080/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Refactor @app.py and add tests"}' | jq -r .id)

# Poll status + output so far
curl http://localhost:8080/jobs/$JID

# Cancel it; status progresses through cancelling → cancelled
curl -X DELETE http://localhost:8080/jobs/$JID

# List all jobs/runs
curl http://localhost:8080/jobs
```

A job view looks like:

```json
{
  "id": "c4f3d937d1f7",
  "type": "job",
  "status": "completed",
  "exit_code": 0,
  "output": "...",
  "command": ["bob", "run", "--accept-license", "--mode", "unrestricted-dev", "..."]
}
```

`status` is one of `pending | running | completed | failed | timeout`.

### `POST /run` — orchestrated run (verify + retry)

This is what turns the wrapper into a real **harness**: run the prompt, verify
the result with a shell `check` command, and if it fails, feed the failure back
to Bob and retry — up to `max_attempts` times.

**Request body** (extends `/invoke` with):

| Field | Type | Default | Description |
|---|---|---|---|
| `check` | string | `null` | Shell command that verifies success (exit 0 = pass). If omitted, Bob's own exit code decides. |
| `max_attempts` | int | `3` | Max verify/retry attempts (1–10) |
| `check_timeout` | int | `300` | Max seconds per check |

```bash
# Ask Bob to implement something and keep retrying until the tests pass.
RID=$(curl -s http://localhost:8080/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Implement add() in calc.py", "check": "pytest -q", "max_attempts": 4}' | jq -r .id)

curl http://localhost:8080/jobs/$RID
```

**Response** (`GET /jobs/{id}` for a run)

```json
{
  "id": "98fa595b737c",
  "type": "harness",
  "status": "completed",
  "success": true,
  "check": "pytest -q",
  "max_attempts": 4,
  "attempts": [
    {"attempt": 1, "bob_exit_code": 0, "check_exit_code": 1, "check_timed_out": false},
    {"attempt": 2, "bob_exit_code": 0, "check_exit_code": 0, "check_timed_out": false}
  ],
  "output": "...full transcript across attempts..."
}
```

On each retry the harness appends a `--- HARNESS FEEDBACK ---` block (the failing
command and its output) to the prompt so Bob can fix it. Runs are streamable via
`GET /jobs/{id}/stream`; the `[harness]` markers show each attempt and the check
result.

### `GET /jobs/{id}/stream` and `POST /stream` — live output (SSE)

Stream Bob's output line by line as it happens, via Server-Sent Events.
`POST /stream` starts a job and streams it in a single request:

```bash
curl -sN http://localhost:8080/stream \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Explain @README.md"}'
```

```
data: YOLO mode is enabled. All tool calls will be automatically approved.
data: ...
event: done
data: {"status": "completed", "success": null}
```

The final `event: done` carries `status` and, for `/run`, the `success` flag
(`null` for plain jobs). `GET /jobs/{id}/stream` streams an already-created run
the same way. Consume it with any SSE client (`curl -N`, `EventSource` in the
browser, etc.).

### Interactive API docs

FastAPI ships OpenAPI docs out of the box:

- Swagger UI: `http://localhost:8080/docs`
- OpenAPI schema: `http://localhost:8080/openapi.json`

---

## 4. Talk to Bob from Slack (bidirectional bot)

The Slack bot lets you talk to Bob **in a Slack channel without @-mentioning
it**: write a message, Bob starts a cancellable `/jobs` task and replies in the
thread when it reaches a terminal state.

It connects to Slack over **Socket Mode** (an outbound WebSocket), so the
container needs **no public URL**. By default the compose command is
`serve-all`, which runs the REST API **and** the Slack bot in the **same
container** — the bot calls the API over `http://localhost:8080`. (You can still
run them apart: override the command to `serve` for API-only, or `slack` for a
bot-only container that points at a remote API via `HARNESS_URL`.)

> **New to Slack apps?** Follow the beginner-friendly, click-by-click walkthrough
> in **[`SLACK_SETUP.md`](SLACK_SETUP.md)** — it covers creating the app from the
> manifest, both tokens, every `.env` value, inviting the bot, verifying the
> connection, and troubleshooting, with all the URLs you need. The steps below are
> the condensed version.

### 4.1 Create the Slack App

1. Go to **[api.slack.com/apps](https://api.slack.com/apps)** → **Create New App**
   → **From a manifest**, pick your workspace, and paste `slack/manifest.yaml`
   from this repo. It pre-configures the scopes (`chat:write`,
   `channels:history`, `files:read`), the `message.channels` event, and Socket Mode.
2. **Install** the app to the workspace, then copy the **Bot User OAuth Token**
   (`xoxb-...`) → `SLACK_BOT_TOKEN`.
3. Under **Basic Information → App-Level Tokens**, generate a token with the
   `connections:write` scope and copy it (`xapp-...`) → `SLACK_APP_TOKEN`.
4. **Invite the bot to your channel:** `/invite @Bob`.

### 4.2 Configure and run

Paste the two tokens into `.env` (see `.env.example`), then:

```bash
podman compose up --build   # single container: REST API + Slack bot (serve-all)
podman compose logs -f bob  # watch the bot connect and handle messages
```

Now any message in a channel the bot is in (no mention needed) gets a reply
from Bob in-thread. To limit the bot to specific channels, set
`SLACK_ALLOWED_CHANNELS` to a comma-separated list of channel IDs.

### 4.3 How it works / notes

- The bot ignores messages from bots (including its own) — this is what prevents
  a reply loop — and skips message edits/joins (`subtype`) and empty messages.
- It starts an asynchronous `/jobs` task and polls it; the verify/retry `/run`
  loop is not used for chat.
- To stop the current task, reply in the same thread with `cancel`, `cancelar`,
  `stop`, or `detener`. Bob kills the complete process group and reports the
  final `cancelled` state.
- The bot pulls prior thread messages back as context, so Bob answers with
  continuity within a thread.
- Images and documents are downloaded under `/workspace/slack_uploads/`, and
  Bob receives their local paths. Files are limited to 25 MiB each by default.
- Attachments remain available to follow-up messages in the same thread. A
  background cleanup retains them for 7 days and enforces a 512 MiB total quota.
- Slack retries are deduplicated for 1 hour, and at most two Slack-triggered Bob
  requests run concurrently. Additional requests receive a short busy response.
- Long answers continue as multiple readable messages in the same thread; the
  bot does not discard the tail of Bob's response.
- **Security:** the bot runs Bob in `unrestricted-dev` + YOLO. Anyone who can
  post in a channel the bot is in can run commands inside the container — only
  add it to trusted channels (and use `SLACK_ALLOWED_CHANNELS`).

| Env var | Default | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | — | **Required.** Bot token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | — | **Required.** App-level token for Socket Mode (`xapp-...`) |
| `HARNESS_URL` | `http://localhost:8080` | REST API base URL (same container under `serve-all`; override for a remote API) |
| `SLACK_ALLOWED_CHANNELS` | — | Optional CSV of channel IDs to restrict to |
| `BOB_INVOKE_TIMEOUT` | `600` | Max seconds per Bob invocation |
| `SLACK_UPLOAD_DIR` | `/workspace/slack_uploads` | Persistent directory for Slack attachments |
| `SLACK_MAX_FILE_BYTES` | `26214400` | Maximum bytes downloaded per attachment |
| `SLACK_UPLOAD_TTL_SECONDS` | `604800` | Attachment retention; `0` disables expiry |
| `SLACK_UPLOAD_MAX_BYTES` | `536870912` | Total attachment quota; `0` disables it |
| `SLACK_UPLOAD_CLEANUP_SECONDS` | `3600` | Cleanup interval; `0` disables periodic cleanup |
| `SLACK_EVENT_TTL_SECONDS` | `3600` | Duplicate-event retention window |
| `SLACK_MAX_CONCURRENT` | `2` | Maximum simultaneous Slack-triggered runs |

---

## 5. Schedule recurring tasks (cron)

Bob is **stateless** — each `bob run` is a one-shot process — so recurring work
needs a scheduler that *fires* Bob on a clock. That scheduler is the container's
own **cron daemon**, managed through the harness API (no hand-editing crontabs).

How it fits together:

- The **source of truth** is a JSON registry persisted on the mounted volume
  (`/workspace/schedules.json`), so schedules **survive container recreation**.
- Root's crontab is **regenerated from that registry** on every change and on
  API startup — never edited by hand.
- Each schedule fires by curling the harness's own `POST /schedules/{id}/run`,
  which runs the stored prompt through the `/run` (verify+retry) machinery. So
  **cron needs none of Bob's environment**, and every scheduled run shows up in
  `/jobs` and `/workspace/cron.log`.

### Create / list / cancel via the API

```bash
# Create: run a prompt every weekday at 09:00 (container clock = UTC).
curl -s -X POST http://localhost:8080/schedules \
  -H 'Content-Type: application/json' \
  -d '{
        "cron": "0 9 * * 1-5",
        "prompt": "Summarize any new files under /workspace and write a report.md",
        "name": "weekday-summary"
      }'
# -> {"id":"a1b2c3d4e5f6","cron":"0 9 * * 1-5", ... }

curl -s http://localhost:8080/schedules            # list all
curl -s http://localhost:8080/schedules/a1b2c3d4e5f6   # one (incl. last_run/last_status)
curl -s -X DELETE http://localhost:8080/schedules/a1b2c3d4e5f6   # cancel
```

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `cron` | string | (required) | 5-field expression: `m h dom mon dow` (e.g. `*/15 * * * *`) |
| `prompt` | string | (required) | Task Bob runs each time it fires (self-contained — no chat context) |
| `name` | string | `""` | Human-readable label |
| `mode` | string | `unrestricted-dev` | Custom mode slug |
| `check` | string | `null` | Verify command (exit 0 = pass) → enables verify/retry |
| `channel` | string | `null` | Slack channel id to post the result to (falls back to `SLACK_DEFAULT_CHANNEL`) |
| `max_attempts` | int | `3` | Max verify/retry attempts |
| `timeout` | int | `600` | Max seconds per Bob attempt |

### Deliver the result to Slack

By default a scheduled run's output lands only in `/jobs` and
`/workspace/cron.log`. To have it **posted to a Slack channel** when it
finishes, add a `channel` (or set a `SLACK_DEFAULT_CHANNEL` in `.env`):

```bash
curl -s -X POST http://localhost:8080/schedules \
  -H 'Content-Type: application/json' \
  -d '{
        "cron": "*/5 * * * *",
        "prompt": "Tell a short, original joke.",
        "name": "joke-o-clock",
        "channel": "C0123ABC456"
      }'
```

Now every 5 minutes Bob posts a fresh joke to that channel. The harness uses the
same `SLACK_BOT_TOKEN` as the bot (`chat:write`), so the bot must be a member of
the target channel (`/invite @Bob`). Find a channel id in Slack via *View channel
details* (bottom of the panel) or right-click → *Copy link* (the `C...` id is at
the end of the URL). From Slack you can just ask Bob "post it here" — it's given
the current channel id and will set `channel` for you.

### Create from Slack

Just ask Bob in natural language — it's taught (via `.bob/rules-unrestricted-dev/AGENT.md`)
to register schedules through this API:

> **you:** cada día a las 8am revisa el estado del repo y publícalo aquí
> **Bob:** _Listo — programé `daily-repo-status` (`0 8 * * *`), id `a1b2c3d4e5f6`. Próxima ejecución mañana 08:00 UTC._

### Notes

- Times use the **container clock (UTC)**. Convert from your local time.
- Cron expressions accept `*`, ranges (`1-5`), lists (`0,30`), and steps
  (`*/15`). Named values (`@daily`, `mon`) are **not** supported — use numbers.
- **Security:** scheduled runs execute Bob in `unrestricted-dev` + YOLO with no
  human in the loop. Only schedule prompts you fully trust.

---

## 6. Use Bob directly (without the API)

```bash
# Interactive session
podman compose run --rm bob shell

# Single headless prompt
podman compose run --rm bob bob run --accept-license --mode unrestricted-dev "Explain @README.md"
```

## 7. Tests

Unit tests live in `api/test_server.py` (REST API), `api/test_slack_bot.py`
(Slack bot logic), and `api/test_schedules.py` (cron scheduler). They mock
`subprocess`, `crontab`, and the network, so they never call the real `bob`
binary, the IBM API, cron, or Slack — fast and offline. They cover `/health`,
`/invoke`, the async `/jobs` lifecycle, `/stream` (SSE), the `/run` orchestration
loop (verify + retry), the bot's `should_handle` / `run_prompt` / `build_reply`
helpers, and the scheduler's cron validation / crontab generation / CRUD.

Run them inside the built image (which already has the runtime deps):

```bash
podman run --rm -v "$PWD/api:/app:ro" -w /app --entrypoint bash bob-harness -lc \
  'pip install -q --break-system-packages -r requirements-dev.txt && python3 -m pytest -v'
```

Or locally, if you have Python 3.12+:

```bash
cd api
pip install -r requirements-dev.txt
pytest -v
```

## 8. Configuration reference

| Env var | Default | Where | Description |
|---|---|---|---|
| `BOBSHELL_API_KEY` | — | `.env` | **Required.** Authenticates Bob in headless mode |
| `BOB_MODE` | `unrestricted-dev` | `.env` / compose | Default custom mode slug |
| `BOB_WORKDIR` | `/` | `.env` / compose | Default working directory (`/` = whole container) |
| `BOB_MAX_JOBS` | `100` | env | Max runs kept in memory (oldest evicted) |
| `BOB_BIN` | `bob` | env | Path/name of the Bob binary |
| `BOB_VERSION` | `2.0.1` | build arg | Pinned Bob Shell version |
| `SLACK_BOT_TOKEN` | — | `.env` | Slack bot token (`xoxb-...`); required for the Slack bot |
| `SLACK_APP_TOKEN` | — | `.env` | Slack app-level token (`xapp-...`) for Socket Mode |
| `SLACK_ALLOWED_CHANNELS` | — | `.env` | Optional CSV of channel IDs the bot answers in |
| `SLACK_DEFAULT_CHANNEL` | — | `.env` | Fallback channel id where scheduled runs post their result |
| `SLACK_UPLOAD_DIR` | `/workspace/slack_uploads` | env | Where incoming Slack attachments are saved |
| `SLACK_MAX_FILE_BYTES` | `26214400` | env | Maximum bytes downloaded per Slack attachment |
| `SLACK_UPLOAD_TTL_SECONDS` | `604800` | env | Seconds to retain Slack attachments (`0` disables expiry) |
| `SLACK_UPLOAD_MAX_BYTES` | `536870912` | env | Total attachment storage quota (`0` disables it) |
| `SLACK_UPLOAD_CLEANUP_SECONDS` | `3600` | env | Background cleanup interval (`0` disables it) |
| `SLACK_EVENT_TTL_SECONDS` | `3600` | env | Window for suppressing duplicate Slack events |
| `SLACK_MAX_CONCURRENT` | `2` | env | Concurrent Slack-triggered Bob runs |
| `HARNESS_URL` | `http://localhost:8080` | compose | REST API URL the Slack bot + cron call (same container under `serve-all`) |
| `BOB_SCHEDULES_FILE` | `/workspace/schedules.json` | env | Persisted schedule registry (survives restarts) |
| `BOB_CRON_LOG` | `/workspace/cron.log` | env | Where each cron tick logs its curl output |

## 9. Security

- The `unrestricted-dev` mode grants **full** access to the container's
  filesystem and shell. Use it only inside this disposable container.
- `--yolo` limits edits to the starting directory, which here is `/` — i.e. the
  **whole container**. Keep this container disposable and never mount anything
  sensitive from the host.
- Secrets (`BOBSHELL_API_KEY`, the Slack tokens) live only in `.env`
  (gitignored) — the committed files carry placeholders. Do not publish them,
  and rotate any that leak.
- The REST API has **no authentication** yet — do not expose port 8080 beyond
  localhost until a token layer is added.

## Author

Edgar Bruney
