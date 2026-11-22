// Deterministic frame renderer for the #220 video pilot.
// Usage: node render_frames.js <scene.html> <outDir> [fps=30] [width=1280] [height=720] [data.json] [stills=t1,t2,...]
// Loads the scene, optionally injects window.DATA, calls window.render(t) for every frame and writes JPEG frames.
// Needs only the preinstalled Playwright + Chromium (no network, no paid service).
const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
const [scene, outDir, fpsArg, wArg, hArg, dataPath, stillsArg] = process.argv.slice(2);
const fps = +fpsArg || 30, W = +wArg || 1280, H = +hArg || 720;
(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  const errors = []; page.on('pageerror', e => errors.push(String(e)));
  if (dataPath && dataPath !== '-') await page.addInitScript(d => { window.DATA = d; }, JSON.parse(fs.readFileSync(dataPath, 'utf8')));
  await page.goto('file://' + path.resolve(scene) + `?w=${W}&h=${H}`);
  await page.waitForFunction(() => typeof window.render === 'function');
  const duration = await page.evaluate(() => window.DURATION);
  const times = stillsArg ? stillsArg.split(',').map(Number) : Array.from({ length: Math.round(duration * fps) }, (_, i) => i / fps);
  for (let i = 0; i < times.length; i++) {
    await page.evaluate(t => window.render(t), times[i]);
    const name = stillsArg ? `still_${times[i].toFixed(2)}.jpg` : `f_${String(i).padStart(5, '0')}.jpg`;
    await page.screenshot({ path: path.join(outDir, name), type: 'jpeg', quality: 92 });
  }
  await browser.close();
  if (errors.length) { console.error('page errors:', errors); process.exit(1); }
  console.log(`rendered ${times.length} frame(s) of ${duration}s at ${fps} fps, ${W}x${H}`);
})();
