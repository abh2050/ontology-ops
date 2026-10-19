import { expect, test } from "@playwright/test";
import { IdleTracker, nextPollDelay, POLL_BASE_MS, POLL_MAX_MS } from "../src/polling";

test("job polling backs off exponentially while idle and resets on change", () => {
  expect([0, 1, 2, 3, 4, 9].map(nextPollDelay)).toEqual([2000, 4000, 8000, 15000, 15000, 15000]);
  const t = new IdleTracker();
  const delays = [3, 3, 3, 4, 4, 5].map((rev, i) => nextPollDelay(t.observe(rev, i)));
  // first sight resets; unchanged revisions (304s) back off; a new revision resets to 2 s
  expect(delays).toEqual([POLL_BASE_MS, 4000, 8000, POLL_BASE_MS, 4000, POLL_BASE_MS]);
  expect(Math.max(...delays)).toBeLessThanOrEqual(POLL_MAX_MS);
  // re-evaluating without a new fetch must not count as another idle poll
  expect(t.observe(5, 5)).toBe(0);
  expect(t.observe(5, 5)).toBe(0);
});
