import { test, expect, type Page } from "@playwright/test";

// Runs against a real API and Next.js server on an isolated, seeded demo database.
async function ask(page: Page, message: string) {
  const input = page.getByLabel("Tell Tomo what changed");
  await input.fill(message);
  const response = page.waitForResponse(r => r.url().endsWith("/api/assistant"));
  await input.press("Enter");
  expect((await response).status()).toBe(200);
}

test("day view: propose, preview, apply and undo through chat", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("—");
  await expect(page.getByRole("region", { name: "Coming up" })).toContainText("Dentist cleaning");
  await expect(page.getByRole("button", { name: /Build confidence in C\+\+/ })).toBeVisible();
  for (const label of ["Focus work", "Fixed commitment", "Routine", "Personal goal", "Errand"]) {
    await expect(page.locator(".legend", { hasText: label })).toBeVisible();
  }

  await ask(page, "I want to get good at C++ by December.");
  const card = page.getByRole("group", { name: "Proposed changes" });
  await expect(card).toContainText("Proposed: a C++ goal", { timeout: 45000 });
  await expect(card.getByText("New goal")).toBeVisible();

  await card.getByRole("button", { name: /^Apply/ }).click();
  await expect(page.locator(".bubble", { hasText: "Done." }).last()).toBeVisible({ timeout: 45000 });
  await expect(page.getByRole("button", { name: /Build confidence in C\+\+/ })).toHaveCount(2);

  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".bubble", { hasText: "Undone." })).toBeVisible({ timeout: 45000 });
  await expect(page.getByRole("button", { name: /Build confidence in C\+\+/ })).toHaveCount(1);
});

test("week and month views, collapsible chat and clarification", async ({ page }) => {
  await page.goto("/week");
  await expect(page.getByRole("region", { name: "This week's schedule" })).toBeVisible();
  await expect(page.locator(".dayhead")).toHaveCount(7);
  await expect(page.getByText("Goals this week")).toBeVisible();

  await page.getByRole("button", { name: "Collapse chat" }).click();
  await page.getByRole("button", { name: "Expand chat: Plan with Tomo" }).click();
  await page.keyboard.press("Escape");
  await page.locator("h1").click();
  await page.keyboard.press("/");
  await expect(page.getByLabel("Tell Tomo what changed")).toBeFocused();

  await ask(page, "Plan a dentist visit sometime");
  await expect(page.locator(".bubble").last()).toContainText("Demo mode understands only", { timeout: 45000 });

  await page.getByRole("tab", { name: "Month" }).click();
  await expect(page.locator(".month-cell")).toHaveCount(42);
  await page.locator(".month-cell.today").click();
  await expect(page).toHaveURL(/\/(\?date=.*)?$/);
});

test("dialogs: add an appointment and review settings; no overflow on phones", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Add something important" }).click();
  const dialog = page.getByRole("dialog", { name: "Add something important" });
  await dialog.getByLabel("What is it?").fill("Physio check-up");
  await dialog.getByLabel("Starts").fill("07:00");
  await dialog.getByLabel("Ends").fill("07:30");
  const nextWeek = new Date(Date.now() + 8 * 86400000).toISOString().slice(0, 10);
  await dialog.getByLabel("Date").fill(nextWeek);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden({ timeout: 45000 });
  await expect(page.getByRole("region", { name: "Coming up" })).toContainText("Physio check-up");

  await page.getByRole("button", { name: "Profile and settings" }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await expect(settings.getByLabel("Timezone")).toHaveValue("America/Los_Angeles");
  await expect(settings.getByRole("checkbox", { name: "Enable activity monitoring" })).not.toBeChecked();
  await settings.getByRole("button", { name: "Cancel" }).click();

  await page.setViewportSize({ width: 375, height: 812 });
  for (const path of ["/", "/week", "/month"]) {
    await page.goto(path);
    await expect(page.locator(".schedule")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});
