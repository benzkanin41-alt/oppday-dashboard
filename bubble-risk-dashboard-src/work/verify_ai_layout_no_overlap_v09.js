const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const htmlPath = path.resolve("outputs", "dashboard", "index.html");
  const fileUrl = "file:///" + htmlPath.replace(/\\/g, "/");
  const executablePath = process.env.CHROME_PATH || undefined;
  const browser = await chromium.launch({ headless: true, executablePath });
  try {
    const page = await browser.newPage({ viewport: { width: 1820, height: 980 } });
    await page.goto(fileUrl, { waitUntil: "load" });
    await page.locator("#ai-semiconductor-direct").scrollIntoViewIfNeeded();
    const result = await page.evaluate(() => {
      const ai = document.querySelector("#ai-semiconductor-direct");
      const heroGrid = document.querySelector(".hero-grid");
      const manifest = [...document.querySelectorAll("h2")].find((h) => h.textContent.trim() === "Source Manifest");
      const rect = (el) => {
        const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, height: r.height };
      };
      return {
        ai: rect(ai),
        heroGrid: heroGrid ? rect(heroGrid) : null,
        gap: heroGrid ? heroGrid.getBoundingClientRect().top - ai.getBoundingClientRect().bottom : null,
        spacerHeight: document.querySelector(".after-ai-spacer") ? document.querySelector(".after-ai-spacer").getBoundingClientRect().height : 0,
        aiMarginBottom: getComputedStyle(ai).marginBottom,
        chartViewBox: document.querySelector("#ai-semiconductor-direct svg").getAttribute("viewBox"),
        manifestTopInDocument: manifest ? manifest.getBoundingClientRect().top + window.scrollY : -1,
        mainBottomInDocument: document.querySelector("main").getBoundingClientRect().bottom + window.scrollY,
      };
    });
    console.log(JSON.stringify(result, null, 2));
    if (!result.heroGrid) throw new Error("Hero score grid not found");
    if (result.gap < 48) throw new Error("Gap between AI direct section and score tiles is too small");
    if (result.spacerHeight < 80) throw new Error("after-ai-spacer height is missing or too small");
    if (!(result.manifestTopInDocument > 0 && result.mainBottomInDocument - result.manifestTopInDocument < 30000)) {
      throw new Error("Source Manifest is not near the bottom of main content");
    }
  } finally {
    await browser.close();
  }
})();
