"""Warm authenticated read latency at N concurrent readers (M2 check 7, M5 check 4).

Usage:
  uv run python scripts/loadtest.py --base-url http://127.0.0.1:8000 --readers 20 \
      --requests 2000 --out docs/evidence/latency/local-m2.json
Local mode mints local test tokens. Against a deployed stack pass --token-file with
one "subject<TAB>access_token" line per user instead (tokens are never written out).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import statistics
import time
from pathlib import Path

import httpx

SUBJECTS = ["reviewer", "operator_a", "operator_b"]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


async def discover(client: httpx.AsyncClient, tokens: dict[str, str]) -> dict[str, list]:
    """Build a request mix from what each principal can actually see."""
    plan: dict[str, list] = {}
    for subject, token in tokens.items():
        h = {"Authorization": f"Bearer {token}"}
        page = (await client.get("/api/queue", params={"limit": 50}, headers=h)).json()
        items = page["items"]
        cursor = page["next_cursor"]
        orders = [i["order_id"] for i in items]
        sellers = sorted({s for i in items for s in i["seller_ids"]})
        reqs = [("queue", "/api/queue", {"limit": 25})]
        if cursor:
            reqs.append(("queue_page2", "/api/queue", {"limit": 25, "cursor": cursor}))
        reqs += [("order", f"/api/orders/{o}", {}) for o in orders[:20]]
        reqs += [("seller_scope", f"/api/sellers/{s}/scope", {}) for s in sellers[:10]]
        reqs += [("graph", "/api/graph", {"root_type": "Order", "root_id": o,
                                          "scenario_id": "base-v1"}) for o in orders[:10]]
        reqs += [("context", "/api/context", {"target_type": "Seller", "target_id": s,
                                              "scenario_id": "base-v1"}) for s in sellers[:5]]
        plan[subject] = reqs
    return plan


async def run(args) -> dict:
    if args.token_file:
        tokens = dict(line.rstrip("\n").split("\t", 1)
                      for line in Path(args.token_file).read_text().splitlines() if line)
    else:
        from ops.auth import issue_local_token
        tokens = {s: issue_local_token(s) for s in SUBJECTS}
    limits = httpx.Limits(max_connections=args.readers, max_keepalive_connections=args.readers)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30, limits=limits) as client:
        plan = await discover(client, tokens)
        rng = random.Random(7)
        jobs = []
        for _ in range(args.warmup + args.requests):
            subject = rng.choice(list(plan))
            jobs.append((subject, rng.choice(plan[subject])))
        results: list[tuple[str, float, int]] = []
        queue: asyncio.Queue = asyncio.Queue()
        for j in jobs:
            queue.put_nowait(j)

        async def reader():
            while not queue.empty():
                subject, (kind, path, params) = queue.get_nowait()
                h = {"Authorization": f"Bearer {tokens[subject]}"}
                t0 = time.perf_counter()
                r = await client.get(path, params=params, headers=h)
                results.append((kind, (time.perf_counter() - t0) * 1000, r.status_code))

        started = time.perf_counter()
        await asyncio.gather(*(reader() for _ in range(args.readers)))
        wall = time.perf_counter() - started
    measured = results[args.warmup:]
    by_kind: dict[str, list[float]] = {}
    for kind, ms, _ in measured:
        by_kind.setdefault(kind, []).append(ms)
    all_ms = [ms for _, ms, _ in measured]
    errors = sum(1 for _, _, status in measured if status != 200)
    return {
        "base_url": args.base_url,
        "readers": args.readers,
        "requests_measured": len(measured),
        "warmup_requests": args.warmup,
        "non_200": errors,
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(len(results) / wall, 1),
        "overall_ms": {"p50": round(statistics.median(all_ms), 1),
                       "p95": round(percentile(all_ms, 95), 1),
                       "p99": round(percentile(all_ms, 99), 1),
                       "max": round(max(all_ms), 1)},
        "by_endpoint_ms": {k: {"n": len(v), "p50": round(statistics.median(v), 1),
                               "p95": round(percentile(v, 95), 1)}
                           for k, v in sorted(by_kind.items())},
        "target": "p95 < 750 ms at 20 concurrent readers",
        "host": f"{platform.system()} {platform.machine()}, single uvicorn worker",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--readers", type=int, default=20)
    ap.add_argument("--requests", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--token-file")
    ap.add_argument("--out")
    args = ap.parse_args()
    report = asyncio.run(run(args))
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")


if __name__ == "__main__":
    main()
