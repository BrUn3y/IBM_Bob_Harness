import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("./", import.meta.url);
const scenes = readdirSync(new URL("compositions/", root))
  .filter((name) => name.endsWith(".html"));
assert.equal(scenes.length, 9);
assert.match(readFileSync(new URL("index.html", root), "utf8"), /<html lang="en"/);
const files = ["index.html", ...scenes.map((name) => `compositions/${name}`)];
for (const file of files) {
  const html = readFileSync(new URL(file, root), "utf8");
  assert.doesNotMatch(html, /[¿¡áéíóúüñ]/iu, `Non-English copy in ${file}`);
  assert.doesNotMatch(
    html,
    /\b(?:desarrollo|reportes|canales|hilo|requisitos|cancelar|detener|ilustrativa|ejemplo|agrega|pruebas)\b/iu,
    `Untranslated Spanish copy in ${file}`,
  );
}
console.log(JSON.stringify({ ok: true, language: "en", sourceFilesChecked: files.length }));
