// Renders receipt TEXT as a PDF or as a picture, for testing the PDF and the photo path.
// The pictures are SYNTHETIC: real text typeset here, with optional skew, blur, noise and low contrast.
// They are cleaner than a photo of a crumpled till slip, so results on them are optimistic.
//   import { renderReceipt } from "./render_receipt.mjs"
//   node tools/render_receipt.mjs <text file> <out.pdf|out.png> [clean|mild|hard]
import { readFileSync } from "node:fs";
import puppeteer from "puppeteer-core";
import { browserPath } from "./browser.mjs";

export const LEVELS = {
  clean: { rotate: 0, blur: 0, noise: 0, contrast: 1, paper: "#ffffff" },
  mild: { rotate: 1.5, blur: 0.5, noise: 0.25, contrast: 0.9, paper: "#f4f2ec" },
  hard: { rotate: 3, blur: 1.0, noise: 0.45, contrast: 0.75, paper: "#e9e6dd" },
};

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

function html(text, level) {
  const l = LEVELS[level];
  return `<!doctype html><meta charset="utf-8"><style>
    body { margin: 0; background: ${level === "clean" ? "#fff" : "#8b8b86"}; }
    .desk { display: inline-block; padding: ${level === "clean" ? 0 : 60}px; }
    .slip { position: relative; display: inline-block; background: ${l.paper}; padding: 28px 22px; transform: rotate(${l.rotate}deg);
      filter: blur(${l.blur}px) contrast(${l.contrast}); }
    pre { margin: 0; font: 600 17px/1.32 "Courier New", Courier, monospace; color: #1b1b1b; }
    .noise { position: absolute; inset: 0; opacity: ${l.noise}; filter: url(#grain); background: #fff; mix-blend-mode: multiply; }
  </style>
  <svg width="0" height="0"><filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7"/>
    <feColorMatrix type="saturate" values="0"/></filter></svg>
  <div class="desk"><div class="slip"><pre>${esc(text)}</pre>${l.noise ? '<div class="noise"></div>' : ""}</div></div>`;
}

export async function renderReceipt(browser, text, path, level = "clean") {
  const page = await browser.newPage();
  await page.setViewport({ width: 700, height: 900, deviceScaleFactor: 2 });
  await page.setContent(html(text, level));
  if (path.endsWith(".pdf")) await page.pdf({ path, width: "100mm", printBackground: true, preferCSSPageSize: false });
  else await (await page.$(".desk")).screenshot({ path });
  await page.close();
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [source, out, level] = process.argv.slice(2);
  const browser = await puppeteer.launch({ executablePath: browserPath(), headless: true });
  await renderReceipt(browser, readFileSync(source, "utf8"), out, level || "clean");
  await browser.close();
}
