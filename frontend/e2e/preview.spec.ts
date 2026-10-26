import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const theme of ["light", "dark"]) {
  test(`${theme} theme renders without layout overflow`, async ({
    page,
    isMobile,
  }, testInfo) => {
    if (isMobile) await page.setViewportSize({ width: 360, height: 800 });
    await page.addInitScript(
      (value) => localStorage.setItem("sp-theme", value),
      theme,
    );
    await page.goto("/preview");
    await expect(
      page.getByRole("heading", { name: "Your support, on autopilot." }),
    ).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    );
    expect(overflow).toBe(false);
    await page.screenshot({
      path: testInfo.outputPath(`${theme}-overview.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", {
        name: theme === "dark" ? "Try light theme" : "Try dark theme",
      })
      .click();
    await expect(page.locator("html")).toHaveAttribute(
      "data-theme",
      theme === "dark" ? "light" : "dark",
    );
  });
}

test("navigation, editable approvals, and preview safety", async ({
  page,
  isMobile,
}) => {
  await page.goto("/preview");
  if (isMobile)
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Approvals", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Ready for your go-ahead." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review & edit" }).first().click();
  await page
    .getByRole("textbox", { name: "body", exact: true })
    .fill("Thanks for your question. Here is your reviewed response.");
  await page.getByRole("button", { name: "Save revised draft" }).click();
  await expect(
    page.getByText(
      "Thanks for your question. Here is your reviewed response.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Approve", exact: true })
    .first()
    .click();
  await expect(page.getByRole("status")).toContainText(
    "No external action was performed",
  );
});

test("agent chat and knowledge search are interactive", async ({
  page,
  isMobile,
}) => {
  await page.goto("/preview/chat");
  await page
    .getByRole("textbox", { name: "Message your agent" })
    .fill("Find our refund policy");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByText(/This is the interactive frontend preview/),
  ).toBeVisible();
  if (isMobile)
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Knowledge base", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search your knowledge" })
    .fill("password reset");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(
    page.getByText(/Team members can reset their password/),
  ).toBeVisible();
});

test("reduced motion preserves a complete static scene", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/preview");
  await expect(
    page.getByRole("img", { name: /3D agent core connecting/ }),
  ).toBeVisible();
  await expect(page.locator(".static-core")).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("execution history exposes inspectable node traces", async ({ page }) => {
  await page.goto("/preview/runs/run-2");
  await expect(
    page.getByRole("heading", { name: "Execution timeline" }),
  ).toBeVisible();
  await page.getByRole("button", { name: /plan completed/ }).click();
  await expect(page.locator("pre")).toContainText("Understand the ticket");
});

test("dashboard has no serious accessibility violations", async ({ page }) => {
  for (const theme of ["light", "dark"]) {
    await page.addInitScript(
      (value) => localStorage.setItem("sp-theme", value),
      theme,
    );
    await page.goto("/preview");
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      result.violations
        .filter((v) => ["serious", "critical"].includes(v.impact || ""))
        .map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => ({
            target: n.target,
            reason: n.failureSummary,
          })),
        })),
    ).toEqual([]);
  }
});

test("disabled WebGL and graphics preference retain an accessible fallback", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("sp-graphics", "false");
    HTMLCanvasElement.prototype.getContext = (() =>
      null) as typeof HTMLCanvasElement.prototype.getContext;
  });
  await page.goto("/preview");
  await expect(page.locator(".static-core")).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
});

test("desktop loads the real WebGL scene", async ({
  page,
  isMobile,
}, testInfo) => {
  test.skip(isMobile, "Mobile deliberately uses the static fallback");
  await page.addInitScript(() => localStorage.setItem("sp-theme", "dark"));
  await page.goto("/preview");
  await expect(page.locator(".scene-canvas canvas")).toBeVisible({
    timeout: 15000,
  });
  await page.screenshot({
    path: testInfo.outputPath("dark-3d.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Try light theme", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({
    path: testInfo.outputPath("light-3d.png"),
    fullPage: true,
  });
});
