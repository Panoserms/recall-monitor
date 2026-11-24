// Renders the story into the website's media folder: MP4 (H.264) for the README and old browsers,
// looping WebM (VP9) for the site, and a poster frame. Run from motion/: npm run render
// The site build never runs this; the rendered files are committed, so the site builds without Node.
import { execFileSync } from "node:child_process";
import { mkdirSync, statSync } from "node:fs";

const out = "../recall/site/static/media";
mkdirSync(out, { recursive: true });
const run = (...args) => execFileSync("npx", ["remotion", ...args], { stdio: "inherit" });
run("render", "src/index.ts", "ReceiptStory", `${out}/receipt-story.mp4`, "--codec=h264", "--crf=26");
run("render", "src/index.ts", "ReceiptStory", `${out}/receipt-story.webm`, "--codec=vp9", "--crf=36");
run("still", "src/index.ts", "ReceiptStory", `${out}/receipt-story-poster.png`, "--frame=250");
for (const f of ["receipt-story.mp4", "receipt-story.webm", "receipt-story-poster.png"]) {
  console.log(`${f}: ${(statSync(`${out}/${f}`).size / 1024).toFixed(0)} KB`);
}
