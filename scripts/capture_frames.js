const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

(async () => {
  const [chromePath, htmlPath, outDir, fpsArg, durationArg] = process.argv.slice(2);
  const fps = Number(fpsArg);
  const duration = Number(durationArg);
  if (!chromePath || !htmlPath || !outDir || !fps || !duration) {
    console.error("usage: capture_frames.js <chrome> <html> <outDir> <fps> <seconds>");
    process.exit(2);
  }
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1"],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
    await page.goto("file:///" + htmlPath.replace(/\\/g, "/"), { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready.then(() => true));
    await new Promise((resolve) => setTimeout(resolve, 150));

    const total = Math.max(1, Math.round(duration * fps));
    for (let i = 0; i < total; i += 1) {
      const ms = Math.min(duration * 1000, (i / fps) * 1000);
      await page.evaluate((t) => {
        for (const animation of document.getAnimations()) {
          try {
            animation.pause();
            animation.currentTime = t;
          } catch (error) {
            /* ignore non-seekable animations */
          }
        }
      }, ms);
      await page.screenshot({
        path: path.join(outDir, String(i).padStart(4, "0") + ".jpg"),
        type: "jpeg",
        quality: 88,
      });
    }
  } finally {
    await browser.close();
  }
})();
