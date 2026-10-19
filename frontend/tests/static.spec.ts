import { expect, test } from "@playwright/test";

for (const path of ["/evidence/", "/sandbox/"]) {
  test(`${path} uses authored fixture data without API requests`, async ({
    page,
  }) => {
    const apiRequests: string[] = [];
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.startsWith("/api"))
        apiRequests.push(request.url());
    });
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: "Late delivery queue" }),
    ).toBeVisible();
    await expect(page.getByText("Authored", { exact: true })).toBeVisible();
    await page.getByLabel("Scenario").selectOption("base-v1");
    await page.getByRole("button", { name: "Apply context" }).click();
    await page
      .getByRole("button", { name: /^Investigate / })
      .first()
      .click();
    await expect(
      page.getByRole("heading", { name: /Evidence around order/ }),
    ).toBeVisible();
    await expect(
      page.getByText("Synthetic scenario", { exact: true }).first(),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "order_line", exact: true })
      .first()
      .click();
    await expect(page.locator(".meaning")).toContainText(/seller|Seller/);
    await page
      .getByRole("button", { name: "Simulate assisted investigation" })
      .click();
    await page
      .getByRole("button", { name: "Save internal proposal for review" })
      .click();
    await page
      .getByRole("navigation")
      .getByRole("button", { name: /Action review/ })
      .click();
    await expect(page.getByText("pending", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Approve internal case" }).click();
    await expect(page.getByText("executed", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /Evidence/ }).click();
    await expect(
      page.getByRole("heading", { name: "Performance & decision" }),
    ).toBeVisible();
    expect(apiRequests).toEqual([]);
    await page.screenshot({
      path: test.info().outputPath("evidence.png"),
      fullPage: true,
    });
  });
}
