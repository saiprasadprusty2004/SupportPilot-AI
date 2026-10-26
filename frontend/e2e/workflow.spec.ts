import { expect, test } from "@playwright/test";
import type { Action } from "../src/lib/types";

test("full-stack cited drafts, edited approvals, three actions, replay and team invitation", async ({
  page,
  browser,
  isMobile,
}) => {
  test.skip(
    !process.env.DEMO_E2E_URL || isMobile,
    "Requires a running demo API; one desktop journey",
  );
  test.setTimeout(120_000);
  const origin = process.env.DEMO_E2E_URL!;
  const suffix = Date.now().toString();
  await page.goto(origin);
  await page.getByRole("button", { name: "Open demo workspace" }).click();
  await expect(
    page.getByRole("heading", { name: /A little less busywork/ }),
  ).toBeVisible();
  await page.goto(origin + "/knowledge");
  const upload = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/documents") && r.request().method() === "POST",
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: `browser-guide-${suffix}.md`,
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "Team invitations: owners invite teammates from Settings Members. Check the spam folder. Invitations expire after 48 hours.",
    ),
  });
  const document = await (await upload).json();
  await expect
    .poll(
      async () =>
        (
          await (await page.request.get(origin + "/api/v1/documents")).json()
        ).items.find((d: { id: string }) => d.id === document.id)?.status,
      { timeout: 30_000 },
    )
    .toBe("ready");

  for (const kind of ["reply", "slack", "refund"]) {
    await page.goto(origin + "/inbox");
    await page
      .getByRole("button", { name: /Question about our latest invoice/ })
      .click();
    if (kind === "refund") {
      await page
        .getByRole("button", {
          name: /Change linked payment|Link test payment/,
        })
        .click();
      await page.getByLabel("Payment intent ID").fill("pi_demo_invoice");
      await page.getByRole("button", { name: "Confirm payment link" }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
    const created = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/runs") && r.request().method() === "POST",
    );
    await page
      .getByRole("button", {
        name:
          kind === "reply"
            ? "Prepare reply"
            : kind === "slack"
              ? "Propose Slack escalation"
              : "Propose test refund",
        exact: true,
      })
      .click();
    const run = await (await created).json();
    const status = async () =>
      (await (await page.request.get(`${origin}/api/v1/runs/${run.id}`)).json())
        .status;
    await expect.poll(status, { timeout: 30_000 }).toBe("awaiting_approval");
    let action: Action = (
      await (await page.request.get(origin + "/api/v1/approvals")).json()
    ).items.find((a: Action) => a.run_id === run.id);
    expect(action).toBeTruthy();
    await page.goto(origin + "/approvals");
    let card = page.getByTestId(`approval-${action.id}`);
    await expect(card).toBeVisible();
    if (kind === "reply") {
      expect(action.citations.length).toBeGreaterThan(0);
      const source = action.citations[0];
      expect(
        (
          await page.request.get(
            `${origin}/api/v1/documents/${source.document_id}/source?version=${source.version}`,
          )
        ).ok(),
      ).toBeTruthy();
      await card.getByRole("button", { name: "Review & edit" }).click();
      await page
        .getByRole("textbox", { name: "body", exact: true })
        .fill(
          `Reviewed reply ${suffix}: owners can manage invitations from Settings.`,
        );
      const edited = page.waitForResponse((r) =>
        r.url().endsWith(`/approvals/${action.id}/decide`),
      );
      await page.getByRole("button", { name: "Save revised draft" }).click();
      action = await (await edited).json();
      expect(action.version).toBe(2);
      card = page.getByTestId(`approval-${action.id}`);
    }
    await card.getByRole("button", { name: "Approve", exact: true }).click();
    await expect.poll(status, { timeout: 30_000 }).toBe("completed");
    const me = await (
      await page.request.get(origin + "/api/v1/auth/me")
    ).json();
    expect(
      (
        await page.request.post(
          `${origin}/api/v1/approvals/${action.id}/decide`,
          {
            headers: { "X-CSRF-Token": me.csrf_token },
            data: { decision: "approve", version: action.version },
          },
        )
      ).status(),
    ).toBe(409);
    await page.goto(`${origin}/runs/${run.id}`);
    await expect(
      page.getByText(/simulated (gmail reply|slack escalation|stripe refund)/),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Execution timeline" }),
    ).toBeVisible();
    const replay = await page.evaluate(
      async (id) =>
        new Promise<number>((resolve, reject) => {
          const source = new EventSource(
            `/api/v1/runs/${id}/events/stream?after=1`,
          );
          const timeout = setTimeout(() => {
            source.close();
            reject(new Error("SSE replay timed out"));
          }, 8000);
          source.addEventListener("trace", (event) => {
            clearTimeout(timeout);
            source.close();
            resolve(Number((event as MessageEvent).lastEventId));
          });
          source.onerror = () => {
            clearTimeout(timeout);
            source.close();
            reject(new Error("SSE unavailable"));
          };
        }),
      run.id,
    );
    expect(replay).toBeGreaterThan(1);
  }

  await page.goto(origin + "/settings");
  await page
    .getByLabel("Invite by email")
    .fill(`browser-${suffix}@example.com`);
  await page.getByRole("button", { name: "Create invite link" }).click();
  await expect(page.locator(".copy-field input").first()).toBeVisible();
  const invite = new URL(
    await page.locator(".copy-field input").first().inputValue(),
  );
  const guest = await browser.newContext();
  const member = await guest.newPage();
  try {
    await member.goto(origin + invite.pathname + invite.search);
    await member.getByLabel("Your name").fill("Browser Teammate");
    await member
      .getByLabel("Password", { exact: true })
      .fill("browser-fixture-password-2026");
    await member.getByRole("button", { name: "Join your workspace" }).click();
    await expect(
      member.getByRole("heading", { name: /A little less busywork/ }),
    ).toBeVisible();
    await member.goto(origin + "/settings");
    await expect(
      member.getByRole("button", { name: "Save changes" }),
    ).toBeDisabled();
    await guest.clearCookies();
    await member.goto(origin);
    await member
      .getByLabel("Email address")
      .fill(`browser-${suffix}@example.com`);
    await member
      .getByLabel("Password", { exact: true })
      .fill("browser-fixture-password-2026");
    await member.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      member.getByRole("heading", { name: /A little less busywork/ }),
    ).toBeVisible();
  } finally {
    await guest.close();
  }
});
