// Job status polling (spec 13.3): every 2 s with ETag, exponential backoff while the job
// is idle (unchanged revision / HTTP 304), reset on any change, stop at a terminal state.
export const POLL_BASE_MS = 2000;
export const POLL_MAX_MS = 15000;
export const ACTIVE_STATES = ["queued", "running", "validating"];

export function nextPollDelay(idlePolls: number): number {
  return Math.min(POLL_BASE_MS * 2 ** Math.max(0, idlePolls), POLL_MAX_MS);
}

/** Tracks consecutive unchanged polls for one job. Counts once per completed fetch:
 * callers pass the fetch timestamp, because TanStack Query evaluates refetchInterval
 * on every observer update, not only after a fetch. */
export class IdleTracker {
  private lastRevision: number | undefined;
  private lastFetchAt: number | undefined;
  idlePolls = 0;

  observe(revision: number | undefined, fetchedAt?: number): number {
    if (fetchedAt !== undefined && fetchedAt === this.lastFetchAt) return this.idlePolls;
    this.lastFetchAt = fetchedAt;
    if (revision !== undefined && revision === this.lastRevision) this.idlePolls += 1;
    else this.idlePolls = 0;
    this.lastRevision = revision;
    return this.idlePolls;
  }
}
