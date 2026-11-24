// Step 3 checks in headless Edge or Chrome, on the built site:
//   node tools/check_motion.mjs http://127.0.0.1:8001 [--cpu 4]
// 1 with motion: every animation moves only transform/opacity; frame timing, long tasks and layout shifts while the
//   receipt flow runs (made-up example: read, check, correct a line, add and remove lines, re-check);
// 2 with prefers-reduced-motion: no animation runs at all, the video does not play;
// 3 the story video plays only on screen and has a working pause button; results are announced in words;
//   removing a line with the keyboard keeps the focus in the list.
import puppeteer from "puppeteer-core";
import { browserPath } from "./browser.mjs";

const args = process.argv.slice(2);
const base = args[0].replace(/\/$/, "");
const cpu = args.includes("--cpu") ? +args[args.indexOf("--cpu") + 1] : 1;
const browser = await puppeteer.launch({ executablePath: browserPath(), headless: true });
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) process.exitCode = 1; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const PROBE = () => {
  window.__motion = { props: new Set(), count: 0, frames: [], longtasks: [], shifts: 0 };
  const original = Element.prototype.animate;
  Element.prototype.animate = function (keyframes, options) {
    const list = Array.isArray(keyframes) ? keyframes : [keyframes];
    for (const k of list) for (const p of Object.keys(k)) if (!["offset", "easing", "composite"].includes(p)) window.__motion.props.add(p);
    window.__motion.count++;
    return original.call(this, keyframes, options);
  };
  new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__motion.longtasks.push(e.duration))).observe({ type: "longtask", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (!e.hadRecentInput) window.__motion.shifts += e.value; })).observe({ type: "layout-shift", buffered: true });
  let last = performance.now();
  window.__motion.slowAt = [];
  const tick = (now) => {
    const gap = now - last;
    window.__motion.frames.push(gap);
    if (gap > 34) {
      const step = performance.getEntriesByType("mark").filter((m) => m.startTime <= now).pop();
      window.__motion.slowAt.push(`${gap.toFixed(0)} ms at ${now.toFixed(0)} (after mark: ${step ? step.name : "page load"})`);
    }
    last = now; requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  // CSS animations and transitions that run during the flow
  window.__motion.css = new Set();
  const sample = () => { for (const a of document.getAnimations()) { if (a.effect && a.effect.getKeyframes) for (const k of a.effect.getKeyframes()) for (const p of Object.keys(k)) if (!["offset", "easing", "composite", "computedOffset"].includes(p)) window.__motion.css.add(`${a.constructor.name}:${p}`); } };
  setInterval(sample, 30);
};

const mark = (page, name) => page.evaluate((n) => performance.mark(n), name);
async function flow(page) {
  await mark(page, "example");
  await page.click("#example"); await page.waitForSelector("#step-review:not([hidden])"); await wait(500);
  await mark(page, "check");
  await page.click("#check"); await page.waitForSelector("#step-results:not([hidden])"); await wait(700);
  await mark(page, "correct");
  const announced1 = await page.$eval("#result-status", (e) => e.textContent);
  await page.$eval("#lines .slip-line [data-text]", (e) => { e.value = "Etwas anderes"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  await wait(700);
  const announced2 = await page.$eval("#result-status", (e) => e.textContent);
  await mark(page, "add");
  await page.click("#add-line"); await page.keyboard.type("Spinat gehackt"); await wait(600);
  await mark(page, "remove");
  // remove a line with the keyboard
  await page.focus("#lines .slip-line:nth-child(2) [data-remove]");
  await page.keyboard.press("Enter"); await wait(400);
  const focus = await page.evaluate(() => ({ inList: Boolean(document.activeElement.closest("#lines")), tag: document.activeElement.tagName }));
  return { announced1, announced2, focus };
}

for (const reduce of [false, true]) {
  const page = await browser.newPage();
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: reduce ? "reduce" : "no-preference" }]);
  if (cpu > 1) { const s = await page.createCDPSession(); await s.send("Emulation.setCPUThrottlingRate", { rate: cpu }); }
  await page.setViewport({ width: 1280, height: 900 });
  await page.evaluateOnNewDocument(PROBE);
  await page.goto(`${base}/receipt.html`, { waitUntil: "networkidle0" });
  await wait(1500);
  const playing = await page.$eval("[data-story] video", (v) => !v.paused);
  const label = reduce ? "reduced motion" : "with motion";
  const result = await flow(page);
  const m = await page.evaluate(() => ({ props: [...window.__motion.props], css: [...window.__motion.css], count: window.__motion.count,
    frames: window.__motion.frames, slowAt: window.__motion.slowAt, longtasks: window.__motion.longtasks, shifts: window.__motion.shifts, running: document.getAnimations().length }));
  if (!reduce) {
    check(playing, `${label}: the story video plays while it is on screen`);
    check(m.count > 5, `${label}: ${m.count} script animations ran during the flow`);
    check(m.props.every((p) => p === "opacity" || p === "transform"), `${label}: script animations move only ${m.props.join(", ") || "-"}`);
    const moving = m.css.filter((p) => !/:(opacity|transform)$/.test(p));
    console.log(`     CSS animations/transitions seen: ${m.css.join(", ") || "none"}`);
    check(moving.every((p) => /:(backgroundColor|borderBottomColor|boxShadow|color)$/.test(p)), `${label}: CSS animations change only opacity/transform (or colour, which does not move)`);
    const frames = m.frames.slice(5), slow = frames.filter((d) => d > 34).length, worst = Math.max(...frames);
    console.log(`     frames: ${frames.length}, longer than 34 ms (two frames at 60 Hz): ${slow} (${(100 * slow / frames.length).toFixed(1)} %), worst ${worst.toFixed(0)} ms`);
    console.log(`     slow frames: ${m.slowAt.join(" | ")}`);
    console.log(`     long tasks (>50 ms): ${m.longtasks.length}${m.longtasks.length ? `, longest ${Math.max(...m.longtasks).toFixed(0)} ms` : ""}; layout shift (CLS, no input): ${m.shifts.toFixed(3)}`);
    globalThis.perf = { frames: frames.length, slow, worst, longtasks: m.longtasks, cls: m.shifts };
  } else {
    check(!playing, `${label}: the story video does not play by itself`);
    check(m.count === 0, `${label}: no script animation ran (${m.count})`);
    check(m.css.length === 0, `${label}: no CSS animation or transition ran (${m.css.join(", ") || "none"})`);
  }
  check(/may be a recalled product|matches a current recall/.test(result.announced1), `${label}: result announced: “${result.announced1}”`);
  check(result.announced2 !== "" , `${label}: corrected line, result announced again: “${result.announced2}”`);
  check(result.focus.inList, `${label}: after removing a line with the keyboard the focus stays in the list (${result.focus.tag})`);
  await page.close();
}

// video: pause button, and pausing off-screen
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
await page.goto(`${base}/receipt.html`, { waitUntil: "networkidle0" });
await wait(1200);
await page.click("[data-story-toggle]"); await wait(200);
check(await page.$eval("[data-story] video", (v) => v.paused), "the pause button pauses the video");
check(await page.$eval("[data-story-toggle]", (b) => b.textContent === "Play the example"), "the button then offers to play it");
await page.click("[data-story-toggle]"); await wait(300);
check(!(await page.$eval("[data-story] video", (v) => v.paused)), "and plays it again");
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await page.click("#example"); await page.click("#check");
await page.evaluate(() => document.getElementById("step-results").scrollIntoView()); await wait(600);
check(await page.$eval("[data-story] video", (v) => v.paused), "scrolled off screen, the video pauses");
await browser.close();
