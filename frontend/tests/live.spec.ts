import { expect, test } from "@playwright/test";
import replay from "../src/replay.json" with { type: "json" };

// Browser contract tests with explicitly mocked API responses; never live/model evidence.
test("live adapter carries context and idempotency, polls ETags, and stops on unknown", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("ops_local_token", "contract-test-token"),
  );
  const order = replay.queue.items[0].order_id;
  let jobReads = 0,
    submissions = 0;
  const reads: number[] = [];
  await page.route("**/ui-config.json", (route) =>
    route.fulfill({ json: { auth_mode: "local" } }),
  );
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    expect(req.headers().authorization).toBe("Bearer contract-test-token");
    if (url.pathname === "/api/meta")
      return route.fulfill({
        json: {
          batches: [
            {
              batch_id: "fixtures-v1",
              demo_as_of: replay.queue.as_of,
              provenance: "authored",
            },
          ],
          scenarios: [],
        },
      });
    if (url.pathname === "/api/me") return route.fulfill({ json: replay.me });
    if (url.pathname === "/api/queue") {
      expect(url.searchParams.get("batch")).toBe("fixtures-v1");
      expect(url.searchParams.get("as_of")).toBe(replay.queue.as_of);
      return route.fulfill({ json: replay.queue });
    }
    if (url.pathname === "/api/graph")
      return route.fulfill({ json: (replay.graphs as any)[`${order}|`] });
    if (url.pathname.startsWith("/api/orders/"))
      return route.fulfill({ json: (replay.snapshots as any)[order] });
    if (url.pathname === "/api/jobs") {
      submissions++;
      expect(req.headers()["idempotency-key"]).toMatch(/^[a-f0-9-]{36}$/);
      expect(req.postDataJSON()).toMatchObject({
        target_id: order,
        target_type: "Order",
        scenario_id: null,
        as_of: replay.queue.as_of,
      });
      return route.fulfill({ status: 202, json: { job_id: "contract-job" } });
    }
    if (url.pathname === "/api/jobs/contract-job") {
      jobReads++;
      reads.push(Date.now());
      if (jobReads > 1)
        expect(req.headers()["if-none-match"]).toBe('"revision-1"');
      if (jobReads === 2)
        return route.fulfill({
          status: 304,
          headers: { ETag: '"revision-1"' },
        });
      return route.fulfill({
        headers: { ETag: '"revision-1"' },
        json: {
          job_id: "contract-job",
          state: jobReads > 2 ? "unknown" : "running",
          revision: 1,
          result: jobReads > 2 ? { reason: "RECONCILE_REQUIRED" } : null,
        },
      });
    }
    throw new Error(`Unexpected API route ${url.pathname}`);
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: /^Investigate / })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Generate proposal evidence" })
    .click();
  await expect(page.getByRole("status")).toContainText("RECONCILE_REQUIRED", {
    timeout: 10000,
  });
  await page.waitForTimeout(2300);
  expect(submissions).toBe(1);
  expect(jobReads).toBe(3);
  expect(reads[1] - reads[0]).toBeGreaterThanOrEqual(1800);
  await expect(
    page.getByRole("button", { name: "Save internal proposal for review" }),
  ).toHaveCount(0);
});

test("viewer gets an empty scoped queue and cannot submit", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("ops_local_token", "viewer-contract-token"),
  );
  await page.route("**/ui-config.json", (route) =>
    route.fulfill({ json: { auth_mode: "local" } }),
  );
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/meta")
      return route.fulfill({
        json: {
          batches: [
            { batch_id: "fixtures-v1", demo_as_of: replay.queue.as_of },
          ],
          scenarios: [],
        },
      });
    if (url.pathname === "/api/me")
      return route.fulfill({
        json: { ...replay.me, role: "viewer", granted_sellers: 0 },
      });
    if (url.pathname === "/api/queue")
      return route.fulfill({
        json: {
          ...replay.queue,
          items: [],
          aggregates: {
            late_open_orders: 0,
            distinct_sellers: 0,
            multi_seller_orders: 0,
            line_value_centavos: 0,
          },
        },
      });
    throw new Error("Viewer triggered an unexpected API request");
  });
  await page.goto("/");
  await expect(
    page.getByText(
      "No late open orders are visible within your granted scope.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /^Investigate / })).toHaveCount(
    0,
  );
});

test("OAuth callback rejects mismatched state before token exchange", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem(
      "ops_oauth",
      JSON.stringify({
        state: "expected",
        nonce: "nonce",
        verifier: "verifier",
        created: Date.now(),
      }),
    ),
  );
  await page.route("**/ui-config.json", (route) =>
    route.fulfill({
      json: {
        auth_mode: "cognito",
        domain: "https://sign-in.example.invalid",
        client_id: "public-client",
        issuer: "https://issuer.example.invalid",
      },
    }),
  );
  let tokenRequests = 0;
  await page.route("**/oauth2/token", (route) => {
    tokenRequests++;
    return route.abort();
  });
  await page.goto("/auth/callback?code=untrusted&state=wrong");
  await expect(
    page.getByText("Sign-in state is invalid or expired."),
  ).toBeVisible();
  expect(tokenRequests).toBe(0);
  expect(new URL(page.url()).search).toBe("");
});
