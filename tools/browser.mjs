// Where a Chromium browser lives on this machine (Edge or Chrome; set BROWSER_PATH to use another one).
import { existsSync } from "node:fs";

export function browserPath() {
  const candidates = [
    process.env.BROWSER_PATH,
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/microsoft-edge",
  ].filter(Boolean);
  const found = candidates.find((path) => existsSync(path));
  if (!found) throw new Error("No Edge or Chrome found. Set BROWSER_PATH to the browser's program file.");
  return found;
}
