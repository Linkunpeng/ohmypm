// Browser smoke test against a running `ohmypm web` (seeded with scripts/seed_demo.py).
// Usage: node scripts/ui-smoke.mjs <login-url> <out-dir> [chromium-path]
import { chromium } from "playwright-core";

const [loginUrl, outDir, exe = "/usr/bin/chromium"] = process.argv.slice(2);
const base = new URL(loginUrl).origin;
const browser = await chromium.launch({ executablePath: exe, headless: true });
const errors = [];

async function session(colorScheme, viewport = { width: 1360, height: 900 }) {
  const context = await browser.newContext({ viewport, colorScheme });
  const page = await context.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`${colorScheme} console: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`${colorScheme} pageerror: ${e.message}`));
  await page.goto(loginUrl);
  await page.waitForSelector("text=Latest records");
  return page;
}

const page = await session("light");
await page.screenshot({ path: `${outDir}/dashboard.png`, fullPage: true });
const projects = await (await page.request.get(`${base}/api/projects`)).json();
const robot = projects.find((p) => p.name === "Robot_WS");
await page.goto(`${base}/projects/${robot.id}`);
await page.waitForSelector("text=Timeline");
await page.screenshot({ path: `${outDir}/project.png`, fullPage: true });

const entries = await (await page.request.get(`${base}/api/entries?project_id=${robot.id}`)).json();
const rich = entries.items.find((e) => e.title === "完成相机驱动");
await page.goto(`${base}/projects/${robot.id}/entries/${rich.id}`);
await page.waitForSelector("[data-testid=mermaid] svg", { timeout: 15000 });
await page.waitForSelector(".katex-display");
await page.screenshot({ path: `${outDir}/entry.png`, fullPage: true });
const checks = {
  mermaidSvg: await page.locator("[data-testid=mermaid] svg").count(),
  katex: await page.locator(".katex").count(),
  table: await page.locator(".md-prose table").count(),
  highlighted: await page.locator(".md-prose pre code.hljs").count(),
  imageLoaded: await page.locator(".md-prose img").first().evaluate((img) => img.complete && img.naturalWidth > 0),
  taskList: await page.locator(".md-prose input[type=checkbox]").count(),
};

await page.goto(`${base}/projects/${robot.id}/entries/${rich.id}/edit`);
await page.waitForSelector("text=Rich text");
await page.waitForTimeout(1500);
checks.editorMode = await page.locator('[aria-label="Editor mode"] [data-state=on]').innerText();
await page.screenshot({ path: `${outDir}/editor.png`, fullPage: true });

await page.goto(`${base}/projects/${robot.id}/summary`);
await page.waitForSelector("text=Project summary");
await page.screenshot({ path: `${outDir}/summary.png`, fullPage: true });

await page.goto(`${base}/search?q=${encodeURIComponent("链接")}`);
await page.waitForSelector("mark");
await page.screenshot({ path: `${outDir}/search.png`, fullPage: true });

const dark = await session("dark");
await dark.goto(`${base}/projects/${robot.id}/entries/${rich.id}`);
await dark.waitForSelector("[data-testid=mermaid] svg", { timeout: 15000 });
await dark.screenshot({ path: `${outDir}/entry-dark.png`, fullPage: true });
await dark.goto(`${base}/projects/${robot.id}`);
await dark.waitForSelector("text=Timeline");
await dark.screenshot({ path: `${outDir}/project-dark.png`, fullPage: true });

const mobile = await session("light", { width: 390, height: 844 });
await mobile.goto(`${base}/projects/${robot.id}`);
await mobile.waitForSelector("text=Timeline");
await mobile.screenshot({ path: `${outDir}/project-mobile.png` });

console.log(JSON.stringify({ checks, errors }, null, 2));
await browser.close();
