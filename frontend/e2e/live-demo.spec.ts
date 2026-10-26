import { expect, test } from "@playwright/test";

// Starts no providers. Run with a local demo API at :8000 and a proxy-enabled dev server.
test("demo session, document ingestion, and durable chat run", async ({
  page,
}) => {
  test.skip(
    !process.env.DEMO_E2E_URL,
    "Set DEMO_E2E_URL to a running full-stack demo",
  );
  await page.goto(process.env.DEMO_E2E_URL!);
  await page.getByRole("button", { name: "Open demo workspace" }).click();
  await expect(
    page.getByRole("heading", { name: /A little less busywork/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Ask your agent", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("How do team invitations work?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText(/Demo answer:/)).toBeVisible({ timeout: 30_000 });
});
