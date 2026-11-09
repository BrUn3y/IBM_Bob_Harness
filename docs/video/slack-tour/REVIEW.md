# Review

## Editorial Decisions

One illustrative development task carries the tutorial through a channel,
thread follow-up, requirements attachment, cancellation and a recurring
report. A separate API scene distinguishes chat jobs from verification/retry.
The tutorial is silent by design, with Spanish instructions on screen.
No private workspace, real credential or live execution is shown.

A live-workspace recording was not used because it would require exposing
real conversations or executing demonstration tasks. A general promotional
trailer was not used because this is a practical usage guide.

## Source Verification

- Features checked against v1.0.4 (`6fc785c`), especially `api/slack_bot.py`,
  `api/server.py`, `api/schedules.py`, the Slack manifest and runtime rules.
- Initial complete HyperFrames check passed, including its craft sweep.
- After layout and chapter-progress adjustments, the final check passed with
  `--no-craft --at 0,6,20,27,32,44,57,68,83,95,107`.
- Final check: 10 HTML files, 11 layout samples, 23 overlap-pass samples,
  zero lint errors, zero runtime errors, zero layout findings, 86 of 86
  sampled contrast checks passed. Motion-sidecar assertions were not enabled.
- Ten initial full-frame snapshots and two contact sheets were inspected,
  plus the running HyperFrames preview in Chromium.
- The final check did not rerun the longer craft sweep; the chapter-progress
  adjustment replaces continuous movement with deliberate reading holds.

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
- MP4: H.264, 1920 x 1080, 30 fps, 3,300 frames, exactly 110 seconds,
  3,057,917 bytes, no audio stream.
- `npm run verify` passed: FFmpeg decode completed, 110 one-second samples
  were nonblank, 49 sampled images were distinct, minimum content fraction
  was 0.0603 (the empty-frame threshold is 0.002).
- A contact sheet decoded from the final MP4 was visually inspected at 6,
  20, 32, 44, 57, 68, 83, 95 and 107 seconds.
- README preview: 9-second GIF, 138,252 bytes. Poster: JPEG at 1280 x 720.
- MP4 SHA-256:
  `5fcc91189d2351367fa9837592737cf7f192999c10a04a8d58c86ce1970fc031`.

_Last updated: 2026-11-09_
