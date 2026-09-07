# Slack Integration — Step-by-Step Guide (for first-timers)

This guide takes you **from zero** to having **Bob** answering inside a Slack
channel. No prior experience creating Slack apps is required: every step tells
you exactly **where to click**, **what to copy**, and **where to paste it**.

> **What will you achieve?**
> Type a message in a Slack channel (e.g. *"Bob, create a test file"*) and have
> **Bob reply in the thread** — no `@`-mention needed.

---

## 🧭 How it works (in 30 seconds)

- Bob connects to Slack over **Socket Mode**: an outbound WebSocket connection.
- Because of that you **do NOT need** a public server, a domain, open ports, or a
  "Request URL". Everything flows from your container out to Slack.
- By default the container runs in `serve-all` mode: the **REST API** and the
  **Slack bot** live in the **same container**; the bot talks to the API over
  `http://localhost:8080`.

You need exactly **two Slack tokens**:

| Token | Starts with | What it's for | Variable in `.env` |
|---|---|---|---|
| **Bot User OAuth Token** | `xoxb-` | Lets the bot **read and reply** to messages | `SLACK_BOT_TOKEN` |
| **App-Level Token** | `xapp-` | Enables the **Socket Mode** connection | `SLACK_APP_TOKEN` |

---

## ✅ Before you start (prerequisites)

1. Permission to **create an app** in your Slack workspace. In many workspaces
   anyone can create apps; in others an admin must approve the installation. If
   you get blocked, ask your admin to approve the app.
2. This repository cloned (you need the `slack/manifest.yaml` file).
3. Your **Bob API key** (`BOBSHELL_API_KEY`, starts with `bob_prod_...`). Without
   it the bot connects to Slack but Bob can't execute anything. How to get it:
   see the main `README.md`, section **"1. Configure the API key"**.

---

## Step 1 — Create the Slack App from the *manifest*

The *manifest* is a file that **configures the app in one shot** (name,
permissions, events, and Socket Mode). In this repo it lives at:

```
slack/manifest.yaml
```

1. Open 👉 **https://api.slack.com/apps**
2. Click **"Create New App"** (green button, top right).
3. Choose **"From a manifest"**.
4. **Select your workspace** from the dropdown and click **"Next"**.
5. You'll see an editor with **JSON / YAML** tabs. Pick **YAML**, **delete** the
   sample content, and **paste** the contents of `slack/manifest.yaml` exactly.
   It's this:

   ```yaml
   display_information:
     name: Bob
     description: Talk to the Bob Shell harness from Slack — no @-mention needed.
     background_color: "#1f2937"

   features:
     bot_user:
       display_name: Bob
       always_online: true

   oauth_config:
     scopes:
       bot:
         - chat:write         # post replies
         - channels:history   # read messages in channels the bot is in
         - files:read         # download attached images and documents

   settings:
     event_subscriptions:
       bot_events:
         - message.channels   # every new message in a channel the bot is in
     socket_mode_enabled: true
     org_deploy_enabled: false
     token_rotation_enabled: false
   ```

6. Click **"Next"**, then **"Create"**.

> Updating an existing app? Add `files:read` under **OAuth & Permissions → Bot
> Token Scopes**, then click **Reinstall to Workspace** so the current bot token
> receives the new permission.

> **What did the manifest just configure?**
> - A bot named **Bob**.
> - Permissions (*scopes*): `chat:write` (reply), `channels:history` (read), and
>   `files:read` (download user attachments).
> - The `message.channels` event (Bob "listens" for new messages).
> - **Socket Mode enabled** (that's why no public URL is required).

---

## Step 2 — Install the app and copy the **Bot Token** (`xoxb-`)

1. In the left menu, go to **"OAuth & Permissions"** (or **"Install App"**).
2. Click **"Install to Workspace"**, then **"Allow"**.
3. Once installed, you'll see the **"Bot User OAuth Token"** — it starts with
   **`xoxb-...`**.
4. Click **"Copy"**. 👉 This value goes into **`SLACK_BOT_TOKEN`**.

> Direct URL: `https://api.slack.com/apps` → your app → **OAuth & Permissions**.

---

## Step 3 — Generate the **App-Level Token** (`xapp-`)

This token is what enables **Socket Mode** (the real-time connection).

1. In the left menu, go to **"Basic Information"**.
2. Scroll down to the **"App-Level Tokens"** section and click
   **"Generate Token and Scopes"**.
3. Give it a **name** (e.g. `socket`).
4. Click **"Add Scope"** and add **`connections:write`**. ⚠️ This scope is
   required; without it Socket Mode won't connect.
5. Click **"Generate"**.
6. Copy the token that appears — it starts with **`xapp-...`**.
   👉 This value goes into **`SLACK_APP_TOKEN`**.

> ⚠️ **Don't mix up the two tokens:**
> - `xoxb-` = **Bot Token** → `SLACK_BOT_TOKEN`
> - `xapp-` = **App-Level Token** → `SLACK_APP_TOKEN`

---

## Step 4 — (Optional) Get a **Channel ID**

You only need this if you want to **restrict** the bot to specific channels
(`SLACK_ALLOWED_CHANNELS`) or set a default channel for scheduled tasks
(`SLACK_DEFAULT_CHANNEL`). If you leave it empty, the bot replies in **every**
channel it's invited to.

To get the **Channel ID** (starts with `C...`):

1. In Slack, **click the channel name** (at the top) to open its details.
2. Scroll to the bottom of the **"Channel details"** panel.
3. You'll see the **"Channel ID"**, something like `C0123ABCD45`. Copy it.

> To list several channels, separate them with **commas**, no spaces:
> `C0123ABCD45,C0987ZYXW65`

---

## Step 5 — Configure the `.env` file

In the repo root, create your `.env` from the template:

```bash
cp .env.example .env
```

Then edit it and fill in these values. The Slack variables are:

| Variable | Required? | Value | Example |
|---|---|---|---|
| `BOBSHELL_API_KEY` | ✅ Yes | Your Bob API key (not a Slack value, but needed for Bob to run) | `bob_prod_xxxxxxxx` |
| `SLACK_BOT_TOKEN` | ✅ Yes | The token from **Step 2** | `xoxb-1234-5678-abcd...` |
| `SLACK_APP_TOKEN` | ✅ Yes | The token from **Step 3** | `xapp-1-A0000-9999-...` |
| `SLACK_ALLOWED_CHANNELS` | ⬜ Optional | Allowed channel IDs, comma-separated. **Empty = all** | `C0123ABCD45,C0987ZYXW65` |
| `SLACK_DEFAULT_CHANNEL` | ⬜ Optional | Channel where **scheduled tasks** post their result when they don't specify one | `C0123ABCD45` |

Advanced variables (leave them as-is unless you know what you're doing):

| Variable | Default | What it does |
|---|---|---|
| `SLACK_THINKING_INTERVAL` | `5` | Seconds between each rotation of the *"Bob is thinking…"* placeholder while it works |
| `SLACK_WORKDIR` | `/` | Working directory Bob runs with when triggered from Slack |
| `BOB_INVOKE_TIMEOUT` | `600` | Maximum seconds per Bob run |
| `HARNESS_URL` | `http://localhost:8080` | Which API the bot talks to (only change it if you run the bot in a separate container) |
| `SLACK_UPLOAD_DIR` | `/workspace/slack_uploads` | Where incoming images and documents are saved |
| `SLACK_MAX_FILE_BYTES` | `26214400` | Maximum bytes downloaded per attachment (25 MiB) |
| `SLACK_UPLOAD_TTL_SECONDS` | `604800` | How long attachments remain available (7 days; `0` disables expiry) |
| `SLACK_UPLOAD_MAX_BYTES` | `536870912` | Total attachment quota (512 MiB; `0` disables it) |
| `SLACK_UPLOAD_CLEANUP_SECONDS` | `3600` | Cleanup frequency (1 hour; `0` disables periodic cleanup) |
| `SLACK_EVENT_TTL_SECONDS` | `3600` | How long duplicate Slack event IDs are remembered |
| `SLACK_MAX_CONCURRENT` | `2` | Maximum Bob requests processed from Slack simultaneously |

**Example of a minimal working `.env`:**

```dotenv
# --- Bob ---
BOBSHELL_API_KEY="bob_prod_YOUR_KEY_HERE"
BOB_MODE=unrestricted-dev
BOB_WORKDIR=/

# --- Slack ---
SLACK_BOT_TOKEN="xoxb-YOUR-BOT-TOKEN"
SLACK_APP_TOKEN="xapp-YOUR-APP-TOKEN"
SLACK_ALLOWED_CHANNELS=
SLACK_DEFAULT_CHANNEL=
```

> 🔒 **Important:** the `.env` holds secrets. **Never** commit it to git (it's
> already in `.gitignore`). If a token leaks, revoke/regenerate it at
> `https://api.slack.com/apps`.

---

## Step 6 — Invite Bob to the channel

Bob **only sees messages in channels where it's a member**. In the Slack channel
where you want to use it, type:

```
/invite @Bob
```

> Note: with the manifest's scopes, the bot works in **public channels**. (Private
> channels would require extra scopes — `groups:history` and the `message.groups`
> event.)

---

## Step 7 — Start the container and verify

From the repo root:

```bash
# Build and start the REST API + Slack bot in a single container
podman compose up --build

# In another terminal, follow the bot's logs
podman compose logs -f bob
```

> Using Docker instead of Podman? Replace `podman` with `docker` in the commands.

In the logs, the **success signal** is seeing something like:

```
Bob harness: starting REST API + Slack bot in one container
Bob Slack bot: connecting via Socket Mode (harness=http://localhost:8080)
INFO slack_bolt.App: A new session has been established
INFO slack_bolt.App: Starting to receive messages from a new connection
```

**Final test:** in the channel where you invited Bob, type (no `@`):

```
Bob, reply with the single word OK
```

You should see the **"Bob is thinking…"** placeholder (it rotates the text) and,
after a few seconds, Bob's reply **in the thread**. 🎉

Then attach an image or document with a request such as `Describe this image` or
`Summarize this PDF`. File-only messages are accepted too.

Attachments stay associated with their Slack thread, so follow-up requests such
as `compare it with the previous image` can reuse retained files. The bot cleans
expired files hourly, removes the oldest files when the quota is exceeded, and
suppresses Slack retry events so the same prompt is not executed twice.

To stop a long-running request, reply inside its thread with `cancel`,
`cancelar`, `stop`, or `detener`. The bot terminates Bob and its child processes,
acknowledges the request, and replaces the pending response with the final
`cancelled` status.

---

## 🛠️ Troubleshooting (FAQ)

| Symptom | Likely cause | Fix |
|---|---|---|
| The bot **doesn't reply** in the channel | You didn't invite it | Type `/invite @Bob` in that channel |
| No reply, and channels are configured | The channel isn't in `SLACK_ALLOWED_CHANNELS` | Add its ID, or leave the variable empty for all |
| Log: `invalid_auth` / `not_authed` | `SLACK_BOT_TOKEN` mis-copied or revoked | Reinstall the app (Step 2) and re-copy the `xoxb-` |
| The bot **won't connect** (no "session established") | Missing `xapp-`, or it lacks `connections:write` | Regenerate the App-Level Token (Step 3) |
| Startup error: `SLACK_APP_TOKEN is not set` | A variable is missing in `.env` | Ensure both `SLACK_BOT_TOKEN` **and** `SLACK_APP_TOKEN` are filled |
| Log: `not_in_channel` when replying | The bot isn't a member of the channel | `/invite @Bob` |
| Bob cannot download an attachment | The app lacks `files:read` | Add the scope under **OAuth & Permissions**, then reinstall the app |
| Bob says it is busy | The configured concurrency limit is active | Wait for a running request to finish or raise `SLACK_MAX_CONCURRENT` |
| Bob says there is no active job | The cancel command was posted outside the task's thread, or the task already ended | Post `cancel` as a reply inside the running task's thread |
| You swapped the tokens | `xoxb-` in `SLACK_APP_TOKEN` (or vice versa) | `xoxb-`→`SLACK_BOT_TOKEN`, `xapp-`→`SLACK_APP_TOKEN` |
| You changed `.env` but nothing changed | The container is still running the old values | `podman compose restart bob` (or `up --build`) |

---

## 🔐 Security note

The bot runs Bob in **`unrestricted-dev` + YOLO** mode: it auto-approves actions
and has full access inside the container. That means **anyone with access to the
channel can ask Bob to execute things.** So, in real environments:

- Use **`SLACK_ALLOWED_CHANNELS`** to limit it to trusted channels.
- Only invite it to channels with authorized people.
- Treat the tokens like passwords.

---

## 🔗 Useful links

- Slack apps dashboard: **https://api.slack.com/apps**
- Create app from a manifest (docs): **https://api.slack.com/reference/manifests**
- Socket Mode (docs): **https://api.slack.com/apis/socket-mode**
- App-Level Tokens (docs): **https://api.slack.com/authentication/token-types#app-level**
- This project's manifest: [`slack/manifest.yaml`](slack/manifest.yaml)
- General harness documentation: [`README.md`](README.md)
