# Project: IBM Bob Harness

A container that runs Bob Shell (IBM) autonomously, with a REST API
(FastAPI) and a Slack bot (Socket Mode) on top.

## Context

- You are inside the `bob-harness` container, in `unrestricted-dev` + `--yolo` mode.
- Your working directory is the container root `/`, so you govern the whole
  container, not just `/workspace`.
- You have full freedom: create, edit, and run whatever you need, anywhere.

## Instructions

- Act autonomously: do what is asked without requesting confirmation.
- Follow the existing code style when editing files in the repo.
- **Whenever you edit README.md**, always update the `Last updated:` date line at
  the bottom (or wherever it appears) to today's date in `YYYY-MM-DD` format
  using `date +%F`. If there is no such line yet, append one before the final
  newline in the format: `_Last updated: YYYY-MM-DD_`.

## Scheduling recurring tasks (cron)

When the user asks you to do something *on a schedule* ("every day at 9",
"cada hora", "todos los lunes", "run X periodically"), DO NOT try to write the
crontab by hand. Instead register the task through the harness's own scheduler
API, which persists it and installs the cron entry for you:

```bash
curl -fsS -X POST http://localhost:8080/schedules \
  -H 'Content-Type: application/json' \
  -d '{"cron": "0 9 * * *", "prompt": "<what to do each time>", "name": "<label>"}'
```

- `cron` is a standard 5-field expression: `minute hour day-of-month month day-of-week`.
  Examples: `0 9 * * *` (daily 09:00), `*/15 * * * *` (every 15 min),
  `0 8 * * 1-5` (weekdays 08:00). Times are the container's clock (UTC).
- `prompt` is the task YOU will be given when it fires — write it as a clear,
  self-contained instruction, since there is no conversation context at run time.
- Optional: `name` (label), `check` (a shell command that must exit 0 for the
  run to count as success — enables verify+retry), `max_attempts`.
- **Delivering the result to Slack:** add `"channel": "<id>"` to post each run's
  output back to a Slack channel. If the user asks for it to be sent "here" /
  "a este canal", use the channel id given in the Slack context above. Without a
  `channel` (and no `SLACK_DEFAULT_CHANNEL`), the run still executes but its
  output only lands in `/jobs` and `/workspace/cron.log` — NOT in Slack.
- To list schedules: `GET /schedules`. To cancel one: `DELETE /schedules/{id}`.

After creating a schedule, confirm to the user what you scheduled and when it
will next run, and include the schedule `id` so they can cancel it later.

## Output format (IMPORTANT: replies are shown in Slack)

Your answers are posted to Slack, which uses "mrkdwn", NOT standard Markdown.
Standard Markdown symbols show up literally (e.g. `**`, `##`), which looks
broken. Always format replies using Slack mrkdwn:

- Bold: wrap in single asterisks -> `*bold*` (NEVER `**bold**`).
- Italic: wrap in underscores -> `_italic_`.
- Strikethrough: `~text~`.
- NO Markdown headings. Do not use `#`, `##`, `###`. For a section title, write
  a bold line instead, e.g. `*Why it matters*`.
- Bullet lists: start each line with `•` (or `-`). Do not rely on `*` for bullets
  (Slack reads a leading `*` as bold).
- Numbered lists: `1.`, `2.`, ... are fine.
- Inline code with single backticks and code blocks with triple backticks both
  work in Slack — use them for commands and code.
- Links: `<https://example.com|link text>`.
- No Markdown tables (Slack does not render them); use aligned text in a code
  block or a simple bulleted list instead.
- Keep replies concise and readable in a chat window.
