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
      const manifest = [...document.querySelectorAll("h2")].find((h) => h.textContent.trim() === "Source Manifest");
      const priceHeat = [...document.querySelectorAll("h3, h2, b, div")]
        .find((el) => el.textContent.trim() === "Price Heat");
      const dataConfidence = [...document.querySelectorAll("h3, h2, b, div")]
        .find((el) => el.textContent.trim() === "Data Confidence");
      const rect = (el) => {
        const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, height: r.height };
      };
      return {
        ai: rect(ai),
        priceHeat: priceHeat ? rect(priceHeat.closest(".card") || priceHeat) : null,
        dataConfidence: dataConfidence ? rect(dataConfidence.closest(".card") || dataConfidence) : null,
        manifestTopInDocument: manifest ? manifest.getBoundingClientRect().top + window.scrollY : -1,
        mainBottomInDocument: document.querySelector("main").getBoundingClientRect().bottom + window.scrollY,
        aiMarginBottom: getComputedStyle(ai).marginBottom,
        chartViewBox: document.querySelector("#ai-semiconductor-direct svg").getAttribute("viewBox"),
      };
    });
    console.log(JSON.stringify(result, null, 2));
    if (result.priceHeat && result.ai.bottom > result.priceHeat.top - 8) {
      throw new Error("AI direct section overlaps or is too close to Price Heat tile");
    }
    if (!(result.manifestTopInDocument > 0 && result.mainBottomInDocument - result.manifestTopInDocument < 30000)) {
      throw new Error("Source Manifest is not near the bottom of main content");
    }
  } finally {
    await browser.close();
  }
})();
