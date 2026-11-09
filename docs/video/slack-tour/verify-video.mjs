import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const path = process.argv[2] || fileURLToPath(
  new URL("../../media/remote-bob-slack-es.mp4", import.meta.url),
);
const metadata = JSON.parse(execFileSync("ffprobe", [
  "-v", "error", "-show_streams", "-show_format", "-of", "json", path,
], { encoding: "utf8" }));
const video = metadata.streams.find((stream) => stream.codec_type === "video");
assert.ok(video, "The file must contain a video stream");
assert.equal(video.codec_name, "h264");
assert.equal(video.width, 1920);
assert.equal(video.height, 1080);
assert.equal(video.avg_frame_rate, "30/1");
assert.equal(Number(video.nb_frames), 3300);
assert.ok(Math.abs(Number(metadata.format.duration) - 110) < 0.04);
assert.equal(metadata.streams.filter((s) => s.codec_type === "audio").length, 0);

// Decode every frame; inspect one small RGB sample per second for empty output.
const width = 160;
const height = 90;
const frameBytes = width * height * 3;
const frames = execFileSync("ffmpeg", [
  "-v", "error", "-xerror", "-i", path,
  "-vf", `fps=1,scale=${width}:${height}`,
  "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
], { maxBuffer: 16 * 1024 * 1024 });
assert.equal(frames.length, 110 * frameBytes);
const distinct = new Set();
let minimumContentFraction = 1;
for (let second = 0; second < 110; second += 1) {
  const frame = frames.subarray(second * frameBytes, (second + 1) * frameBytes);
  let darkPixels = 0;
  for (let pixel = 0; pixel < frame.length; pixel += 3) {
    if (frame[pixel] < 225 || frame[pixel + 1] < 225 || frame[pixel + 2] < 225) {
      darkPixels += 1;
    }
  }
  const fraction = darkPixels / (width * height);
  assert.ok(fraction > 0.002, `Blank or near-blank frame at ${second}s`);
  minimumContentFraction = Math.min(minimumContentFraction, fraction);
  distinct.add(createHash("sha256").update(frame).digest("hex"));
}
assert.ok(distinct.size >= 9, "All nine chapters should produce distinct content");
console.log(JSON.stringify({
  ok: true,
  codec: video.codec_name,
  resolution: `${video.width}x${video.height}`,
  fps: video.avg_frame_rate,
  frames: Number(video.nb_frames),
  duration: Number(metadata.format.duration),
  secondsSampled: 110,
  distinctSamples: distinct.size,
  minimumContentFraction: Number(minimumContentFraction.toFixed(4)),
  bytes: Number(metadata.format.size),
  audio: false,
}, null, 2));
