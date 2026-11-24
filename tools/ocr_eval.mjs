// Compares ways of reading a receipt PICTURE on the device. SYNTHETIC pictures: the text of real receipts is
// typeset by tools/render_receipt.mjs at three levels (clean / mild / hard: skew, blur, grain, low contrast).
// Cleaner than a photo of a crumpled slip, so every number here is optimistic. No real photos exist yet.
//
//   python -m http.server -d public 8001 &
//   node tools/ocr_eval.mjs http://127.0.0.1:8001 [--receipts ~/receipts-lidl/clean] [--n 12] [--out data/receipt_eval/ocr]
//                           [--ollama gemma4:e2b-it-qat] [--ollama-n 4]
//
// Engines: Tesseract.js (WebAssembly, the files the site ships, run inside the built site in a real browser) with two
// page layouts, and optionally a local vision model through Ollama (cannot run on a public website; local app only).
// Score: the OCR text goes through the same parser as pasted text and is compared with the parse of the true text.
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import puppeteer from "puppeteer-core";
import { browserPath } from "./browser.mjs";
import { renderReceipt, LEVELS } from "./render_receipt.mjs";
import { runInNewContext } from "node:vm";

const args = process.argv.slice(2);
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const base = args[0].replace(/\/$/, "");
const folder = option("--receipts", join(homedir(), "receipts-lidl", "clean"));
const out = option("--out", "data/receipt_eval/ocr");
const count = +option("--n", 12), ollama = option("--ollama", null), ollamaCount = +option("--ollama-n", 4);
mkdirSync(out, { recursive: true });

// a fixed sample of receipts of ordinary length
let seed = 20261118;
const random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const files = readdirSync(folder).filter((f) => f.endsWith(".txt")).sort()
  .filter((f) => { const n = readFileSync(join(folder, f), "utf8").split("\n").length; return n >= 15 && n <= 70; });
const sample = [];
while (sample.length < Math.min(count, files.length)) { const f = files[Math.floor(random() * files.length)]; if (!sample.includes(f)) sample.push(f); }

// the site's own reader, loaded into Node for scoring (the same files the browser runs)
const lexicon = await (await fetch(`${base}/data/lexicon.json`)).json();
const reader = {}; reader.globalThis = reader;
for (const file of ["match.js", "receipt.js"]) runInNewContext(await (await fetch(`${base}/static/${file}`)).text(), reader);
reader.RecallMatch.init(lexicon); reader.RecallReceipt.init(lexicon);

const browser = await puppeteer.launch({ executablePath: browserPath(), headless: true });
let page = null;
async function openPage() {
  if (page) await page.close().catch(() => {});
  page = await browser.newPage();
  await page.goto(`${base}/receipt.html`, { waitUntil: "networkidle0" });
  await page.addScriptTag({ url: `${base}/static/vendor/tesseract/tesseract.min.js` });
}
await openPage();

const tesseract = (psm) => async (png) => page.evaluate(async (b64, mode) => {
  const dir = new URL("static/vendor/tesseract/", location.href).href;
  window.ocrWorkers ||= {};
  if (!window.ocrWorkers[mode]) {
    const worker = await Tesseract.createWorker("deu", 1, { workerPath: `${dir}worker.min.js`, corePath: `${dir}core`, langPath: `${dir}lang`, gzip: true, workerBlobURL: false });
    await worker.setParameters({ tessedit_pageseg_mode: mode, preserve_interword_spaces: "1" });
    window.ocrWorkers[mode] = worker;
  }
  return (await window.ocrWorkers[mode].recognize(`data:image/png;base64,${b64}`)).data.text;
}, png.toString("base64"), psm);

const vision = (model) => async (png) => {
  const response = await fetch("http://localhost:11434/api/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, stream: false, think: false, options: { temperature: 0, num_predict: 1500 }, images: [png.toString("base64")],
      prompt: "Transcribe all text on this shop receipt exactly as printed, one printed line per output line, top to bottom. Keep the numbers and the letter at the end of each line. Output only the transcription." }),
  });
  return (await response.json()).response || "";
};

const engines = args.includes("--only-ollama") ? {} : { "Tesseract.js, one block (psm 6)": tesseract("6"), "Tesseract.js, one column (psm 4)": tesseract("4") };
if (ollama) engines[`Ollama ${ollama} (vision; local only)`] = vision(ollama);

const score = (truthText, ocrText, raw) => ((useRepair) => {
  const R = reader.RecallReceipt, M = reader.RecallMatch;
  const want = R.parse(truthText).items.filter((i) => i.kind === "product");
  const parsed = R.parse(useRepair && R.repairOcr ? R.repairOcr(ocrText) : ocrText);
  const got = parsed.layout === "lidl" ? parsed.items.filter((i) => i.kind === "product") : [];
  const left = [...got];
  let exact = 0, close = 0;
  for (const w of want) {
    let i = left.findIndex((g) => g.description === w.description && g.line_total === w.line_total);
    if (i >= 0) { exact++; close++; left.splice(i, 1); continue; }
    i = left.findIndex((g) => g.line_total === w.line_total && M.ratio(g.description.toLowerCase(), w.description.toLowerCase()) >= 85);
    if (i >= 0) { close++; left.splice(i, 1); }
  }
  return { lines: want.length, exact, close, extra: left.length, sums: parsed.sums_match === true };
})(!raw);

const results = {};
for (const [index, file] of sample.entries()) {
  const truth = readFileSync(join(folder, file), "utf8");
  for (const level of Object.keys(LEVELS)) {
    const path = join(out, `${file.replace(".txt", "")}_${level}.png`);
    await renderReceipt(browser, truth, path, level);
    const png = readFileSync(path);
    for (const [name, read] of Object.entries(engines)) {
      if (name.startsWith("Ollama") && index >= ollamaCount) continue;
      const started = Date.now();
      let text = "";
      try { text = await read(png); }
      catch (error) {  // a lost page (memory) counts as nothing read, and the next picture gets a fresh page
        process.stderr.write(`  ${name} failed on ${file} ${level}: ${String(error).slice(0, 120)}\n`);
        text = "";
        if (!name.startsWith("Ollama")) await openPage();
      }
      const seconds = (Date.now() - started) / 1000;
      writeFileSync(join(out, `${file.replace(".txt", "")}_${level}_${name.replace(/[^a-z0-9]+/gi, "-")}.txt`), text);
      for (const variant of ["as read", "after repair rules"]) {
        const s = await score(truth, text, variant === "as read");
        const key = `${name} | ${level} | ${variant}`;
        const r = (results[key] ||= { engine: name, level, variant, receipts: 0, lines: 0, exact: 0, close: 0, extra: 0, sums: 0, seconds: 0 });
        r.receipts++; r.lines += s.lines; r.exact += s.exact; r.close += s.close; r.extra += s.extra; r.sums += s.sums; r.seconds += seconds;
      }
    }
  }
  process.stderr.write(`  ${index + 1}/${sample.length} receipts\n`);
}
await browser.close();

const rows = Object.values(results).map((r) => ({ ...r, seconds_per_receipt: +(r.seconds / r.receipts).toFixed(1) }));
writeFileSync(join(out, args.includes("--only-ollama") ? "ocr_report_ollama.json" : "ocr_report.json"), JSON.stringify({ SYNTHETIC_PICTURES: true, sample: sample.length, rows }, null, 2));
console.log("OCR on SYNTHETIC pictures (real receipt text, typeset and degraded; optimistic). Product lines read with the right price:");
console.log("engine".padEnd(40), "level".padEnd(6), "variant".padEnd(19), "receipts", "exact".padStart(12), "close".padStart(12), "extra", "sum ok", "s/receipt");
for (const r of rows) {
  const pct = (n) => `${n}/${r.lines} ${(100 * n / r.lines).toFixed(0)}%`.padStart(12);
  console.log(r.engine.padEnd(40), r.level.padEnd(6), r.variant.padEnd(19), String(r.receipts).padStart(8), pct(r.exact), pct(r.close), String(r.extra).padStart(5), `${r.sums}/${r.receipts}`.padStart(6), String(r.seconds_per_receipt).padStart(9));
}
