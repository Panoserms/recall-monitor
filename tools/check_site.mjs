// Checks the built public site in headless Edge or Chrome: the receipt page end to end, at desktop width and at 500 px,
// and that every request goes to the site's own host.
//   python -m http.server -d public 8001 &
//   node tools/check_site.mjs http://127.0.0.1:8001 [--receipt <text file>] [--pdf <file>] [--picture <file>] [--shots <folder>]
// Receipt files are private: pass them by path, they are only read into the page, never copied.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";
import { browserPath } from "./browser.mjs";

const args = process.argv.slice(2);
const base = args[0].replace(/\/$/, "");
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : null);
const shots = option("--shots");
const browser = await puppeteer.launch({ executablePath: browserPath(), headless: true });
const page = await browser.newPage();
const hosts = new Set(), errors = [], failed = [];
page.on("request", (r) => { if (!r.url().startsWith("data:") && !r.url().startsWith("blob:")) hosts.add(new URL(r.url()).host); });
// a video or picture download the browser cancels itself (leaving the page, pausing) is not a failure
page.on("requestfailed", (r) => { const why = r.failure() ? r.failure().errorText : ""; if (!(why === "net::ERR_ABORTED" && ["media", "image"].includes(r.resourceType()))) failed.push(`${why} ${r.url()}`); });
page.on("response", (r) => { if (r.status() >= 400 && !r.url().endsWith(".map")) failed.push(`${r.status()} ${r.url()}`); });
page.on("pageerror", (e) => errors.push(String(e)));
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) process.exitCode = 1; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (selector) => page.$eval(selector, (e) => e.textContent.trim());
const count = (selector) => page.$$eval(selector, (e) => e.length);
const shot = async (name) => { if (shots) await page.screenshot({ path: join(shots, name), fullPage: true }); };
const noOverflow = async (what) => {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(over <= 0, `${what}: no sideways scrolling (overflow ${over}px)`);
};

// ---- the made-up example, desktop
await page.setViewport({ width: 1280, height: 900 });
await page.goto(`${base}/receipt.html`, { waitUntil: "networkidle0" });
check(await page.$eval("#step-review", (e) => e.hidden), "review step is hidden before a receipt is added");
await page.click("#example");
await page.waitForSelector("#step-review:not([hidden])");
check(!(await page.$eval("#example-note", (e) => e.hidden)), "the example is labelled as made up");
const lines = await count("#lines .slip-line");
check(lines >= 4, `example: ${lines} lines in the review list`);
check((await text("#receipt-sum")).includes("add up to the printed total"), `example: ${await text("#receipt-sum")}`);
check(await page.$eval("#receipt-store", (e) => e.value === "Lidl"), "example: shop read as Lidl");
check(await page.$eval("#receipt-date", (e) => /^\d{4}-\d\d-\d\d$/.test(e.value)), "example: purchase date read");
await shot("receipt-review-desktop.png");
await page.click("#check");
await page.waitForSelector("#step-results:not([hidden])");
const likely = await count("#results > .alerts .alert"), less = await count("#results details .alert");
check(likely >= 1, `example: ${likely} possible match(es), ${less} less likely`);
check((await count("#results .verdict--affected")) === 0, "a receipt result never says 'affected'");
check((await text("#results .verdict")) === "Possible match: check your pack", "verdict reads 'Possible match: check your pack'");
check((await text("#results .alert__basis")).startsWith("Matched by name"), "the card says what the match rests on");
await shot("receipt-results-desktop.png");

// ---- correcting a line changes the result live
const before = await text("#result-lead");
await page.$eval("#lines .slip-line [data-text]", (e) => { e.value = "Etwas ganz anderes"; e.dispatchEvent(new Event("input", { bubbles: true })); });
await wait(500);
check((await text("#lines .slip-line [data-flag]")) === "Changed by you", "an edited line is marked 'Changed by you'");
check((await text("#result-lead")) !== before || likely > 1, `the result follows the correction: “${await text("#result-lead")}”`);
await page.click("#add-line");
await page.keyboard.type("Spinat gehackt");
await wait(500);
check((await count("#lines .slip-line")) === lines + 1, "a line can be added");
await page.click("#lines .slip-line:last-child [data-remove]"); await wait(400);
check((await count("#lines .slip-line")) === lines, "a line can be removed");
await page.click("#results [data-save]").catch(() => {});
await wait(200);
await page.click("#forget"); await wait(200);
check(await page.$eval("#step-review", (e) => e.hidden) && (await page.$eval("#receipt-text", (e) => e.value)) === "", "'Forget this receipt' clears the page");
check(await page.evaluate(() => !Object.keys(localStorage).some((k) => /receipt/i.test(k)) && sessionStorage.length === 0), "the receipt is not kept in browser storage");

// ---- a real receipt, pasted (private file, passed by path)
if (option("--receipt")) {
  const real = readFileSync(option("--receipt"), "utf8");
  await page.$eval("#receipt-text", (e, value) => { e.value = value; }, real);
  await page.click('#paste-form button[type="submit"]');
  await page.waitForSelector("#step-review:not([hidden])");
  check((await text("#receipt-sum")).includes("add up to the printed total"), `real receipt pasted: ${await count("#lines .slip-line")} lines, ${await text("#receipt-sum")}`);
  await page.click("#check"); await page.waitForSelector("#step-results:not([hidden])");
  check(true, `real receipt result: “${await text("#result-lead")}”`);
  await page.click("#forget");
}
for (const [flag, what] of [["--pdf", "PDF"], ["--picture", "picture"]]) {
  if (!option(flag)) continue;
  const started = Date.now();
  const input = await page.$("#receipt-file");
  await input.uploadFile(option(flag));
  await page.waitForFunction(() => !document.getElementById("step-review").hidden || document.getElementById("read-status").classList.contains("receipt-status--failed"), { timeout: 180000 });
  const ok = !(await page.$eval("#step-review", (e) => e.hidden));
  check(ok, `${what}: ${ok ? `${await count("#lines .slip-line")} lines in ${((Date.now() - started) / 1000).toFixed(1)} s; ${await text("#receipt-sum")}` : await text("#read-status")}`);
  if (ok && flag === "--picture") check(!(await page.$eval("#ocr-note", (e) => e.hidden)), "picture: the page warns that text recognition makes mistakes");
  if (ok) await page.click("#forget");
}

// ---- 500 px
await page.setViewport({ width: 500, height: 900 });
await page.goto(`${base}/receipt.html`, { waitUntil: "networkidle0" });
await noOverflow("receipt page at 500 px");
await page.click("#example"); await page.waitForSelector("#step-review:not([hidden])");
await page.click("#check"); await page.waitForSelector("#step-results:not([hidden])");
await noOverflow("review list and results at 500 px");
await shot("receipt-500.png");
for (const path of ["index.html", "products.html", "about.html"]) {
  await page.goto(`${base}/${path}`, { waitUntil: "networkidle0" });
  await noOverflow(`${path} at 500 px`);
}
const firstRecall = await page.evaluate(async (b) => (await (await fetch(`${b}/data/recalls.json`)).json()).recalls[0].id, base);
await page.goto(`${base}/recall/${firstRecall}.html`, { waitUntil: "networkidle0" });
await noOverflow("a recall page at 500 px");

check([...hosts].every((h) => h === new URL(base).host), `only the site's own host was requested: ${[...hosts].join(", ")}`);
check(failed.length === 0, `no failed requests${failed.length ? ": " + failed.join(" | ") : ""}`);
check(errors.length === 0, `no script errors${errors.length ? ": " + errors.join(" | ") : ""}`);
await browser.close();
