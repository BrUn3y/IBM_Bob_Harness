# Deploying the Bob Harness on a Google Cloud VM (direct Python, no container)

This directory documents and automates how the Bob Harness runs in production on
a small **Google Cloud Compute Engine** VM, **without** the Podman/Docker
container — the API and the Slack bot run directly with Python and are kept
alive by a **systemd** service.

## Why run it directly instead of the container?

On a 1 GB **e2-micro** VM (Google's Always-Free tier), *building* the container
image is the step most likely to run out of memory. Running directly skips the
build entirely and uses less RAM. On a dedicated, disposable VM the container's
main benefit — sandboxing Bob's arbitrary command execution — adds little,
because the VM itself is the sandbox. See the security note at the bottom.

## What gets installed

| Piece | How |
|---|---|
| **Node.js 22** | NodeSource apt repo (Bob is a Node app) |
| **Bob Shell** (pinned `1.0.5`) | `npm install -g` from the pinned tarball |
| **Python deps** | `pip3 install --user` from `api/requirements.txt` |
| **2 GB swap** | swapfile (memory cushion for the 1 GB VM) |
| **Always-on** | `bob-harness` **systemd** service (auto-restart, starts at boot) |

The systemd service runs [`run-harness.sh`](run-harness.sh), which starts the
REST API (`uvicorn server:app` on port 8080) **and** the Slack bot
(`slack_bot.py`) together — the direct-Python equivalent of the container's
`serve-all` entrypoint.

---

## Reference deployment

The live instance was created with these settings (Always-Free eligible):

| Setting | Value |
|---|---|
| Machine type | `e2-micro` (1 GB RAM) |
| Zone | `us-west1-b` (Always-Free zones: `us-west1`, `us-central1`, `us-east1`) |
| Image | Ubuntu 24.04 LTS (amd64) |
| Boot disk | 30 GB `pd-standard` |
| Maintenance policy | `MIGRATE` (required for E2 Standard provisioning) |
| Firewall | none opened — Slack is outbound Socket Mode; API stays on localhost |

---

## Steps

### 1. Create the VM

From your laptop (with `gcloud` installed) **or** Google Cloud Shell:

```bash
./deploy/create-vm.sh          # override PROJECT / ZONE / NAME via env vars
```

Then SSH in (Cloud Shell or `gcloud compute ssh ibm-bob --zone us-west1-b`).

### 2. Clone the repo on the VM

```bash
git clone https://github.com/BrUn3y/IBM_Bob_Harness.git
cd IBM_Bob_Harness
```

### 3. Install the runtime

```bash
./deploy/setup-vm.sh
```

Installs swap, Node 22, Bob, and the Python deps. Prints the versions at the end.

### 4. Configure secrets

```bash
cp .env.example .env
nano .env            # fill in BOBSHELL_API_KEY, SLACK_BOT_TOKEN, SLACK_APP_TOKEN
./deploy/configure-env.sh
```

`configure-env.sh` adjusts `.env` for a direct (non-container) run: it points
`BOB_WORKDIR` / `SLACK_WORKDIR` at the repo directory so Bob can find `.bob/`
(the `unrestricted-dev` custom mode), and relocates the scheduler files into
`./workspace`. **Never commit `.env`** — it holds secrets and is gitignored.

### 5. Install and start the service

```bash
./deploy/install-service.sh
```

Renders the systemd unit for the current user + repo path, enables it at boot,
and starts it. Prints the status at the end (`Active: active (running)`).

### 6. Verify

```bash
curl -s http://localhost:8080/health; echo        # expect bob_present:true, api_key_set:true
journalctl -u bob-harness -n 40 --no-pager        # expect "A new session has been established"
```

Then in Slack: `/invite @Bob` in a channel, and send it a message (no `@` needed).

---

## Managing the service

```bash
sudo systemctl status bob-harness      # is it running?
journalctl -u bob-harness -f           # live logs (Ctrl+C to exit)
sudo systemctl restart bob-harness     # apply .env changes
sudo systemctl stop bob-harness        # stop
sudo systemctl start bob-harness       # start
```

---

## Security notes

- Port 8080 is **not** exposed to the internet; keep the VM firewall closed.
  Slack works over an outbound WebSocket (Socket Mode), so no inbound port is
  needed. Test `/health` locally on the VM.
- Bob runs in `unrestricted-dev` + YOLO mode: it executes requested actions
  **without confirmation**, so anyone who can post in a channel Bob is in can
  make it run commands **on the VM host**. Limit it with `SLACK_ALLOWED_CHANNELS`
  in `.env` and only invite Bob to trusted channels.
- Treat `.env` (API key + Slack tokens) like passwords. Never commit it, never
  upload it anywhere.
