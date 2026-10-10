import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const directory = fileURLToPath(new URL("../../docs/screenshots", import.meta.url));
await mkdir(directory, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:3000");
  await page.getByRole("heading", { name: "Today’s rhythm" }).waitFor();
  await page.screenshot({ path: path.join(directory, "dashboard.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(directory, "mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:3000/calendar");
  await page.getByRole("button", { name: "Plan schedule" }).waitFor();
  await page.locator(".calendar-day").first().waitFor();
  await page.screenshot({ path: path.join(directory, "calendar.png"), fullPage: true });
  console.log("Captured current persisted sample data. No display or clock data was fabricated.");
} finally {
  await browser.close();
}
