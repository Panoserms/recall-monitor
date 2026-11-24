import { Config } from "@remotion/cli/config";
import { existsSync } from "node:fs";

// Use the Edge or Chrome already on this machine instead of downloading another browser.
const local = [
  process.env.BROWSER_PATH,
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find((p) => p && existsSync(p));
if (local) Config.setBrowserExecutable(local);
Config.setVideoImageFormat("png");
