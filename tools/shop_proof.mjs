// Proof for step 2: three recall pages side by side (one shop, several shops, no shop), each with a verdict
// from a product list on the same page, in light and dark mode. Also the receipt result card with the receipt's shop.
//   node tools/shop_proof.mjs http://127.0.0.1:8001 <out folder>
// The product lists are made up for the picture and live only in this headless browser's storage.
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";
import { browserPath } from "./browser.mjs";

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const CASES = [
  { id: "260909_04_BW_Erdbeeren", title: "One shop with a declared colour: band and chip",
    product: { name: "Deluxe Erdbeeren in weißer Schokolade", brand: "Deluxe", best_before: "16.04.2027" } },
  { id: "260725_27_BY_Beeren", title: "Several shops: one chip each, no band",
    product: { name: "Bio Beerenmischung", brand: "", best_before: "01.01.2030" } },
  { id: "261020_22_HE_Sumach", title: "No shop named: neutral",
    product: { name: "Sumach gemahlen", brand: "Ikleel Algabal" } },
];
const browser = await puppeteer.launch({ executablePath: browserPath(), headless: true });
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) process.exitCode = 1; };
for (const scheme of ["light", "dark"]) {
  const shots = [];
  for (const c of CASES) {
    const page = await browser.newPage();
    await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
    await page.setViewport({ width: 500, height: 1100, deviceScaleFactor: 2 });
    await page.goto(`${base}/index.html`, { waitUntil: "networkidle0" });
    await page.evaluate((p) => localStorage.setItem("recall-monitor:products:v1", JSON.stringify([{ ean: "", batch: "", best_before: "", ...p }])), c.product);
    await page.goto(`${base}/recall/${c.id}.html`, { waitUntil: "networkidle0" });
    await page.waitForSelector("#my-verdicts .verdict", { timeout: 10000 }).catch(() => {});
    const verdict = await page.$eval("#my-verdicts", (e) => e.textContent.trim()).catch(() => "");
    const mode = await page.$eval(".shops", (e) => e.className);
    check(Boolean(verdict), `${scheme}, ${c.id}: ${mode}; verdict “${verdict}”`);
    const box = await page.evaluate(() => {
      const top = document.querySelector(".notice__head").getBoundingClientRect().top + scrollY - 12;
      const end = document.querySelector(".notice__pack").getBoundingClientRect().bottom + scrollY + 12;
      return { x: 0, y: top, width: 500, height: end - top };
    });
    shots.push({ title: c.title, png: (await page.screenshot({ clip: box, encoding: "base64" })) });
    await page.close();
  }
  const sheet = await browser.newPage();
  await sheet.setViewport({ width: 1600, height: 900, deviceScaleFactor: 1 });
  await sheet.setContent(`<!doctype html><meta charset="utf-8"><body style="margin:0;padding:24px;background:${scheme === "dark" ? "#0e1829" : "#e9e7e0"};
    font:16px system-ui;color:${scheme === "dark" ? "#e8edf5" : "#13294b"}"><div style="display:flex;gap:20px;align-items:flex-start">
    ${shots.map((s) => `<figure style="margin:0;width:500px"><figcaption style="font-weight:700;margin-bottom:8px">${s.title}</figcaption>
    <img style="width:500px;display:block;box-shadow:0 1px 6px rgb(0 0 0/25%)" src="data:image/png;base64,${s.png}"></figure>`).join("")}</div></body>`);
  await sheet.screenshot({ path: join(out, `shops-side-by-side-${scheme}.png`), fullPage: true });
  await sheet.close();
}
// receipt result: the receipt's own shop picks the colour
const page = await browser.newPage();
await page.setViewport({ width: 900, height: 1000 });
await page.goto(`${base}/receipt.html`, { waitUntil: "networkidle0" });
await page.click("#example"); await page.waitForSelector("#step-review:not([hidden])");
await page.click("#check"); await page.waitForSelector("#step-results:not([hidden])");
const mine = await page.$eval("#results .alert__mine", (e) => e.textContent.trim());
check(/^Your Lidl purchase/.test(mine), `receipt result: “${mine}”`);
check(await page.$eval("#results .alert", (e) => e.classList.contains("shop--lidl")), "receipt result card carries the Lidl accent");
await (await page.$("#results .alert")).screenshot({ path: join(out, "receipt-result-lidl.png") });
await browser.close();
