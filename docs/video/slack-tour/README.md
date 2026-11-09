# Remote Bob Slack Tour

Editable HyperFrames source for the English-only, 110-second visual tutorial.
The Slack interface is an **illustrative reconstruction**, not a recording of
a live workspace. Outputs, timestamps, files and schedule IDs are examples.
No Slack or IBM API requests are made by this video.

## Reproduce

Requires Node.js 22+, FFmpeg and a Chromium browser. HyperFrames is pinned in
`package.json`; GSAP, Inter and Lucide assets are bundled locally.

```bash
npm run check:copy
npm run check
npx --yes hyperframes@0.9.26 preview --background
npm run render -- --quality delivery --fps 30 --strict \
  -o renders/remote-bob-slack-en.mp4
npm run verify -- renders/remote-bob-slack-en.mp4
```

On a machine with an existing Chromium installation, set
`HYPERFRAMES_BROWSER_PATH` to its executable if auto-detection cannot find it.
For a software-only Linux renderer, `PRODUCER_FORCE_SCREENSHOT=true` and
`PRODUCER_BROWSER_GPU_MODE=software` avoid unsupported GPU/BeginFrame probes;
`--workers 1` allows safe reuse of static reading frames.

The tutorial intentionally works without audio. All instructions are visible
in English, including example messages, filenames, channel names and safety
notices. Status text matches the bot's current English messages.
The root README plays the complete tutorial inline as
`docs/media/remote-bob-slack-en.gif` (960 x 540, 8 fps), linked to the full
1080p MP4 with playback controls. The separate 9-second preview remains
available for release links.
`npm run check:copy` checks the English HTML language declaration and guards
against Spanish text from the earlier draft returning to the compositions.
The verification script checks duration, codec, resolution, frame count and
frame rate, decodes the file with FFmpeg, and samples every second for blank
frames. It does not establish the semantic correctness of the illustrated
responses; those are reviewed against the feature sources below.

To reproduce the complete inline animation from the rendered MP4:

```bash
ffmpeg -i renders/remote-bob-slack-en.mp4 \
  -filter_complex '[0:v]fps=8,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=128[p];[b][p]paletteuse=dither=sierra2_4a' \
  -loop 0 renders/remote-bob-slack-en.gif
```

## Chapters

| Time | Topic |
| --- | --- |
| 00:00 | Remote Bob in Slack |
| 00:10 | App, tokens, container and invitation |
| 00:24 | Request a task without a mention |
| 00:37 | Continue in the same thread |
| 00:48 | Images and documents |
| 01:01 | Cancel a running job |
| 01:12 | Recurring reports and UTC |
| 01:27 | `/jobs` versus `/run` |
| 01:39 | Security and persistent files |

## Feature Sources

The tutorial is scoped to Remote Bob **v1.0.4**, commit `6fc785c`:

- `api/slack_bot.py`: event handling, thread history, rotating thinking
  placeholder, attachments, cancellation and multi-message replies.
- `api/server.py`: asynchronous jobs, terminal states, SSE and verification.
- `api/schedules.py` and `.bob/rules-unrestricted-dev/AGENT.md`: persistent
  cron schedules, autonomous prompts and Slack result delivery.
- `slack/manifest.yaml`, `.env.example`, `SLACK_SETUP.md` and root `README.md`:
  installation, configuration defaults and security warnings.

Chat uses `/jobs`, **not** the `/run` verify/retry loop. Scheduled runs can use
that verification machinery. Schedules run on the container clock (UTC);
they do not inherit the original thread's history.

## Assets

- HyperFrames: https://github.com/heygen-com/hyperframes (Apache-2.0).
- GSAP 3.15.0: https://gsap.com/standard-license/ (see `assets/gsap.min.js`).
- Inter: https://github.com/rsms/inter (SIL Open Font License 1.1, bundled
  under `assets/fonts/OFL.txt`).
- Lucide 0.468.0: https://lucide.dev/license (ISC, bundled under
  `assets/icons/LICENSE`).

Slack is a trademark of its owner. This independent project is not presented
as an official Slack or IBM product tutorial.

_Last updated: 2026-11-09_
