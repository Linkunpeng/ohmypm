// End-to-end check of the Web UI against a running `ohmypm web` (seeded with scripts/seed_demo.py).
// Usage: node scripts/e2e-web.mjs <login-url> <png-file> [chromium-path]
import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const [loginUrl, pngFile, exe = "/usr/bin/chromium"] = process.argv.slice(2);
const base = new URL(loginUrl).origin;
const browser = await chromium.launch({ executablePath: exe, headless: true });
const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("dialog", (d) => d.accept());
const results = [];
const step = async (name, fn) => {
  await fn();
  results.push(`ok  ${name}`);
};
const getJson = async (path) => (await page.request.get(`${base}${path}`)).json();

await page.goto(loginUrl);
await page.waitForSelector("text=Latest records");
const robot = (await getJson("/api/projects")).find((p) => p.name === "Robot_WS");

const BODY = [
  "## 场景五：富文本记录",
  "",
  "```python",
  "def fps(frames: int, seconds: float) -> float:",
  "    return frames / seconds",
  "```",
  "",
  "| 模块 | 状态 |",
  "|---|---|",
  "| camera | ✅ |",
  "| planner | 🚧 |",
  "",
  "```mermaid",
  "sequenceDiagram",
  "  camera->>perception: image",
  "  perception->>planner: obstacles",
  "```",
  "",
  "能量公式 $E = mc^2$，以及：",
  "",
  "$$",
  "\\int_0^1 x^2\\,dx = \\frac{1}{3}",
  "$$",
  "",
].join("\n");

let created;
await step("create a record in Markdown mode with an uploaded image", async () => {
  await page.goto(`${base}/projects/${robot.id}/entries/new`);
  await page.getByLabel("Title").fill("Web 富文本验收");
  await page.getByText("Knowledge", { exact: true }).click();
  await page.getByRole("radio", { name: "Markdown" }).click();
  await page.getByLabel("Markdown source").fill(BODY);
  await page.locator('input[type=file]').setInputFiles(pngFile);
  await page.waitForFunction(() => document.querySelector('textarea[aria-label="Markdown source"]')?.value.includes("ohmypm-asset://"));
  await page.getByRole("button", { name: "Add record" }).click();
  await page.waitForURL(/\/entries\/[0-9a-f-]{36}$/);
  created = page.url().split("/").pop();
});

await step("reload shows code, table, Mermaid, KaTeX and the image", async () => {
  await page.reload();
  await page.waitForSelector("[data-testid=mermaid] svg", { timeout: 15000 });
  assert.equal(await page.locator(".md-prose pre code.hljs.language-python").count(), 1);
  assert.equal(await page.locator(".md-prose table tbody tr").count(), 2);
  assert.ok((await page.locator(".katex").count()) >= 2);
  assert.ok(await page.locator(".md-prose img").first().evaluate((img) => img.complete && img.naturalWidth > 0));
  assert.equal(await page.getByRole("heading", { name: "Attachments" }).count(), 1);
  const entry = await getJson(`/api/entries/${created}`);
  assert.ok(entry.content.startsWith(BODY.trimEnd()));
  assert.match(entry.content, /!\[[^\]]*\]\(ohmypm-asset:\/\/[0-9a-f-]{36}\)/);
  assert.equal(entry.source, "web");
});

await step("image opens enlarged in a dialog", async () => {
  await page.getByRole("button", { name: /Enlarge image/ }).first().click();
  await page.waitForSelector("[role=dialog] img");
  await page.keyboard.press("Escape");
});

await step("editing the complex record keeps every construct intact", async () => {
  const before = (await getJson(`/api/entries/${created}`)).content;
  await page.goto(`${base}/projects/${robot.id}/entries/${created}/edit`);
  await page.waitForSelector('[aria-label="Editor mode"]');
  await page.waitForTimeout(800);
  const mode = await page.locator('[aria-label="Editor mode"] [data-state=on]').innerText();
  if (mode.includes("Markdown")) {
    const area = page.getByLabel("Markdown source");
    await area.fill(`${await area.inputValue()}\n追加一行。\n`);
  } else {
    // Click at the end of the "能量公式" paragraph and add a sentence there.
    await page.locator(".ohmypm-editor p", { hasText: "能量公式" }).click();
    await page.keyboard.press("End");
    await page.keyboard.type("追加一行。");
  }
  await page.getByRole("button", { name: "Save record" }).click();
  await page.waitForURL(new RegExp(`/entries/${created}$`));
  const after = (await getJson(`/api/entries/${created}`)).content;
  assert.ok(after.includes("追加一行。"), `appended text missing (mode ${mode}); tail: ${JSON.stringify(after.slice(-160))}`);
  for (const needle of ["```python", "```mermaid", "sequenceDiagram", "$E = mc^2$", "\\int_0^1 x^2\\,dx", "ohmypm-asset://"]) {
    assert.ok(after.includes(needle), `lost ${needle} (mode ${mode})`);
  }
  assert.ok(after.length >= before.length);
  results.push(`    (edited in ${mode.trim()} mode)`);
});

await step("write a record in rich text mode and insert a formula", async () => {
  await page.goto(`${base}/projects/${robot.id}/entries/new`);
  await page.getByLabel("Title").fill("Rich text 记录");
  const editable = page.locator(".ohmypm-editor [contenteditable=true]").first();
  await editable.click();
  await page.keyboard.type("Hello **rich** editor ");
  await page.getByRole("button", { name: "Formula" }).click();
  await page.getByRole("button", { name: "Add record" }).click();
  await page.waitForURL(/\/entries\/[0-9a-f-]{36}$/);
  const entry = await getJson(`/api/entries/${page.url().split("/").pop()}`);
  assert.match(entry.content, /Hello/);
  assert.match(entry.content, /\$\$\nE = mc\^2\n\$\$/);
  await page.waitForSelector(".katex-display");
});

await step("edit a summary section", async () => {
  await page.goto(`${base}/projects/${robot.id}/summary`);
  await page.getByRole("button", { name: "Edit Next steps" }).click();
  await page.getByRole("radio", { name: "Markdown" }).click();
  await page.getByLabel("Markdown source").fill("1. 完成标定\n2. Web 验收通过");
  await page.getByRole("button", { name: "Save section" }).click();
  await page.waitForSelector("text=Web 验收通过");
  const summary = await getJson(`/api/projects/${robot.id}/summary`);
  assert.equal(summary.next_steps, "1. 完成标定\n2. Web 验收通过");
  assert.match(summary.overview, /巡检机器人/); // other sections untouched
});

await step("filter the timeline and search", async () => {
  await page.goto(`${base}/projects/${robot.id}?type=issue`);
  await page.waitForSelector("text=matching records");
  assert.equal(await page.locator("section[aria-labelledby=timeline-heading] ol > li").count(), 1);
  await page.goto(`${base}/search?q=${encodeURIComponent("验收")}`);
  await page.waitForSelector("mark");
});

await step("delete a record with confirmation", async () => {
  await page.goto(`${base}/projects/${robot.id}/entries/${created}`);
  await page.getByRole("button", { name: "Delete record" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete record" }).click();
  await page.waitForURL(new RegExp(`/projects/${robot.id}$`));
  const res = await page.request.get(`${base}/api/entries/${created}`);
  assert.equal(res.status(), 404);
});

console.log(results.join("\n"));
if (errors.length) console.log("browser errors:\n" + errors.join("\n"));
await browser.close();
process.exit(errors.length ? 1 : 0);
