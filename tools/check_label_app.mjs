// Drives the labelling page in headless Edge or Chrome and checks that answers reach the CSV files.
//   node tools/check_label_app.mjs <url> <folder with the label files> [screenshot folder]
// Run it against a scratch copy of data/receipt_eval/ (scripts/label_app.py --out <copy>), never the real one.
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";
import { browserPath } from "./browser.mjs";

const [url, out, shots] = process.argv.slice(2);
const browser = await puppeteer.launch({ executablePath: browserPath(), headless: true });
const page = await browser.newPage();
const hosts = new Set(), errors = [];
page.on("request", (r) => hosts.add(new URL(r.url()).host));
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) process.exitCode = 1; };
const csv = (name) => (existsSync(join(out, name)) ? readFileSync(join(out, name), "utf8") : "");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

await page.setViewport({ width: 1280, height: 900 });
await page.goto(url, { waitUntil: "networkidle0" });
const total = await page.$eval("#count-pairs", (e) => +e.textContent.split("/")[1]);
check(total > 0, `alerts tab lists ${total} pairs`);
const first = await page.$eval(".slip__line", (e) => e.textContent);
if (shots) await page.screenshot({ path: join(shots, "label-pairs-desktop.png") });

await page.keyboard.press("2"); // "same kind"
await wait(600);
check(/,kind\s*$/m.test(csv("3_alert_pairs_labels.csv")), "key 2 writes 'kind' into 3_alert_pairs_labels.csv");
check((await page.$eval("#count-pairs", (e) => e.textContent)).startsWith("1/"), "counter shows 1 answered");
check((await page.$eval(".slip__line", (e) => e.textContent)) !== first || total === 1, "page moved on to the next pair");
await page.click('[data-answer="false"]');
await wait(600);
check((csv("3_alert_pairs_labels.csv").match(/,false\s*$/gm) || []).length === 1, "click on 'Different product' writes 'false'");
await page.click("#back"); await wait(100);
check(await page.$eval('[data-answer="false"]', (e) => e.getAttribute("aria-pressed") === "true"), "going back shows the saved answer as pressed");
await page.click("#clear"); await wait(400);
check((csv("3_alert_pairs_labels.csv").match(/,false\s*$/gm) || []).length === 0, "'Remove this answer' empties the cell");

await page.click("#tab-phrases"); await wait(100);
const printed = await page.$eval(".slip__line", (e) => e.textContent);
await page.type("#phrase", "Testprodukt ausgeschrieben");
await page.keyboard.press("Enter"); await wait(500);
check(csv("2_phrase_labels.csv").includes("Testprodukt ausgeschrieben"), "Enter writes the phrase into 2_phrase_labels.csv");
check((await page.$eval(".slip__line", (e) => e.textContent)) !== printed, "page moved on to the next line");
await page.click("#copy");
check((await page.$eval("#phrase", (e) => e.value)) === (await page.$eval(".slip__line", (e) => e.textContent)), "'Start from the printed text' fills the field");
await page.click("#unknown"); await wait(500);
check(/,\?\s*$/m.test(csv("2_phrase_labels.csv")), "'I do not know this one' writes '?'");
if (shots) await page.screenshot({ path: join(shots, "label-phrases-desktop.png") });

await page.setViewport({ width: 500, height: 900 });
await page.click("#tab-pairs"); await wait(150);
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check(overflow <= 0, `no sideways scrolling at 500 px (overflow ${overflow}px)`);
if (shots) await page.screenshot({ path: join(shots, "label-pairs-500.png"), fullPage: false });

await page.reload({ waitUntil: "networkidle0" });
check((await page.$eval("#count-pairs", (e) => e.textContent)).startsWith("1/"), "answers are still there after a reload");
check([...hosts].every((h) => h === new URL(url).host), `only its own host was requested: ${[...hosts].join(", ")}`);
check(errors.length === 0, `no script errors${errors.length ? ": " + errors.join(" | ") : ""}`);
await browser.close();
