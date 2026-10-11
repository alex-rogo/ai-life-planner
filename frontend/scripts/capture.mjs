import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const directory = fileURLToPath(new URL("../../docs/screenshots", import.meta.url));
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1120 } });
  // CAPTURE_DATE=YYYY-MM-DD shows a fuller day than late-evening "today".
  const query = process.env.CAPTURE_DATE ? `?date=${process.env.CAPTURE_DATE}` : "";
  for (const [route, name] of [[`/${query}`, "day"], [`/week${query}`, "week"]]) {
    await page.goto(`http://127.0.0.1:3000${route}`);
    await page.locator(".block").first().waitFor();
    await page.screenshot({ path: path.join(directory, `${name}.png`) });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`http://127.0.0.1:3000/${query}`);
  await page.locator(".block").first().waitFor();
  await page.screenshot({ path: path.join(directory, "mobile.png"), fullPage: true });
  console.log("Captured current persisted sample data. No display or clock data was fabricated.");
} finally {
  await browser.close();
}
