import { test, expect } from "@playwright/test";

test("real API: goal through chat, calendar, CRUD and responsive dashboard", async ({ page }) => {
  const taskName = `Browser integration reading ${Date.now()}`;
  await page.goto("/assistant");
  await expect(page.getByRole("heading", { name: "Your planning partner" })).toBeVisible();
  await page.getByRole("textbox", { name: "Message your assistant" }).fill("I want to get good at C++ by December.");
  const actionResponse = page.waitForResponse(r => r.url().endsWith("/api/assistant") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Send message" }).click();
  const action = await actionResponse;
  expect(action.status(), await action.text()).toBe(200);
  await expect(page.locator(".chat-message.assistant").last()).toContainText("Created a C++ goal", { timeout: 45000 });
  await page.goto("/tasks");
  await expect(page.getByRole("heading", { name: "Build confidence in C++" }).first()).toBeVisible();
  await page.getByRole("button", { name: "New task", exact: true }).click();
  await page.getByLabel("Task name", { exact: true }).fill(taskName);
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  await expect(page.locator(".task-row").filter({ hasText: taskName })).toBeVisible();
  await page.goto("/calendar");
  await expect(page.getByRole("button", { name: "Generate plan" })).toBeVisible();
  await page.getByRole("button", { name: "Generate plan" }).click();
  await expect(page.getByRole("status")).toContainText("optimized plan", { timeout: 45000 });
  await expect(page.locator(".calendar-event").first()).toBeVisible();
  await page.locator(".calendar-event.is-flexible.planned").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("completed");
  await page.goto("/settings");
  await expect(page.getByLabel("Timezone", { exact: true })).toHaveValue("America/Los_Angeles");
  await expect(page.getByRole("checkbox", { name: "Enable activity monitoring" })).not.toBeChecked();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Today’s rhythm" })).toBeVisible();
  const rowsDoNotOverlap = await page.locator(".session-card").evaluateAll(cards => {
    const bounds = cards.map(card => card.getBoundingClientRect());
    return bounds.every((rect, index) => index === 0 || bounds[index - 1].bottom <= rect.top + 1);
  });
  expect(rowsDoNotOverlap).toBe(true);
  await page.screenshot({ path: "../docs/screenshots/dashboard.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Generate plan" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../docs/screenshots/mobile.png", fullPage: true });
});

test("calendar week/day and deterministic clarification", async ({ page }) => {
  await page.goto("/calendar");
  await page.getByRole("button", { name: "Day", exact: true }).click();
  await expect(page.locator(".calendar-day")).toHaveCount(1);
  await page.getByRole("button", { name: "Week", exact: true }).click();
  await expect(page.locator(".calendar-day")).toHaveCount(7);
  await page.screenshot({ path: "../docs/screenshots/calendar.png", fullPage: true });
  await page.goto("/assistant");
  await page.getByRole("textbox", { name: "Message your assistant" }).fill("An ambiguous request");
  const actionResponse = page.waitForResponse(r => r.url().endsWith("/api/assistant") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Send message" }).click();
  const action = await actionResponse;
  expect(action.status(), await action.text()).toBe(200);
  await expect(page.locator(".chat-message.assistant").last()).toContainText("Demo mode understands only", { timeout: 45000 });
});
