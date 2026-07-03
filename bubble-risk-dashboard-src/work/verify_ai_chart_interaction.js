const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const htmlPath = path.resolve("outputs", "dashboard", "index.html");
  const fileUrl = "file:///" + htmlPath.replace(/\\/g, "/");
  const executablePath = process.env.CHROME_PATH || undefined;
  const browser = await chromium.launch({ headless: true, executablePath });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    await page.goto(fileUrl, { waitUntil: "load" });
    await page.locator("#ai-semiconductor-direct").scrollIntoViewIfNeeded();
    await page.waitForSelector(".ai-point", { timeout: 10000 });
    const totalPoints = await page.locator(".ai-point").count();
    const capexPoint = page.locator('[data-ai-chart="hyperscaler-capex"] .ai-point').first();
    await capexPoint.click();
    const detail = await page.locator('[data-ai-detail="hyperscaler-capex"]').innerText();
    console.log("ai_points", totalPoints);
    console.log("capex_detail", detail.replace(/\s+/g, " ").slice(0, 240));
    if (!detail.includes("Date:") || !detail.includes("Value:") || !detail.includes("SEC tag:")) {
      throw new Error("Click detail panel did not show expected point metadata");
    }
  } finally {
    await browser.close();
  }
})();

