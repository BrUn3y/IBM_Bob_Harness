# Review

## Editorial Decisions

One illustrative development task carries the tutorial through a channel,
thread follow-up, requirements attachment, cancellation and a recurring
report. A separate API scene distinguishes chat jobs from verification/retry.
The tutorial is silent by design, with English-only instructions on screen.
No private workspace, real credential or live execution is shown.

A live-workspace recording was not used because it would require exposing
real conversations or executing demonstration tasks. A general promotional
trailer was not used because this is a practical usage guide.

## Source Verification

- Features checked against v1.0.4 (`6fc785c`), especially `api/slack_bot.py`,
  `api/server.py`, `api/schedules.py`, the Slack manifest and runtime rules.
- The initial draft completed a full HyperFrames check, including its craft
  sweep. The English revision preserves the same timing and layout.
- The English revision passed `npm run check:copy` across all 10 HTML files.
  Titles, chat messages, channel names, attachment names, code examples,
  cancellation commands and safety notices were also reviewed in English.
- The English revision passed the final HyperFrames check with
  `--no-craft --at 0,6,20,27,32,44,57,68,83,95,107`.
- Final check: 10 HTML files, 11 layout samples, 23 overlap-pass samples,
  zero lint errors, zero runtime errors, zero layout findings, 86 of 86
  sampled contrast checks passed. Motion-sidecar assertions were not enabled.
- Nine English full-frame snapshots and their contact sheet were inspected,
  one frame per chapter.
- The English check did not rerun the longer craft sweep. Reading holds and
  accessory-label sizes are unchanged from the initial draft.

## Accepted Warnings

- `duplicate_media_discovery_risk`: three intentionally repeated, untimed
  Lucide arrow images in the API diagram. Each is a separate visual arrow.
- The initial craft pass flagged accessory Slack labels and footer text
  below its 28 px recommendation. Main instructions are 30-68 px. The
  tutorial is intended for full-screen landscape viewing, not a vertical
  phone crop.
- `film_silent` / `audio_none`: deliberate. No audio track is promised.
- No artificial animation was added during reading holds solely to satisfy
  the craft classifier.

## Limitations

The API example is the densest scene; pausing helps when copying its command.
No live Slack, IBM, cron or container integration was exercised for this
documentation change. Repository Python tests were not rerun because no
runtime Python files changed. Audio was neither generated nor listened to.

## Delivered File

- HyperFrames render completed using screenshot capture, software rendering
  and one worker. Static-frame reuse remained verified, not forced.
- English MP4: H.264, 1920 x 1080, 30 fps, 3,300 frames, exactly 110 seconds,
  2,912,302 bytes, no audio stream.
- `npm run verify` passed: FFmpeg decode completed, 110 one-second samples
  were nonblank, 51 sampled images were distinct, minimum content fraction
  was 0.0583 (the empty-frame threshold is 0.002).
- A contact sheet decoded from the final MP4 was visually inspected at 6,
  20, 32, 44, 57, 68, 83, 95 and 107 seconds.
- Short English release preview: 9-second GIF, 95,700 bytes.
  Poster: JPEG at 1280 x 720.
- Complete inline README animation: GIF, 960 x 540, 880 frames at 8 fps,
  110.01 seconds (GIF delay rounding), 975,725 bytes. All nine chapters were
  checked in decoded frames. The animation links to the original MP4 for
  playback controls and 1080p resolution.
- MP4 SHA-256:
  `b1ad2582e7ad347ef3d6e8a81159f477d5c92c54fc8f8d66dddfa9905f4d9730`.

_Last updated: 2026-11-09_
