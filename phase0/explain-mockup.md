# `explain` prototype stimulus

Use this mockup unchanged during measured interviews.

```text
$ product explain src/cache/redis_layer.py:14

Implemented by   claude-code 2.1.173 (role: developer)
Session          4f21a9 · 2026-07-18
Task             #184 "Reduce p95 response latency on /feed"
Instruction      Keep personalized responses under 250 ms at p95 without
                 caching user data outside the approved regional store.

Decision         Use Redis with a 30-second per-user cache key.
Alternatives     In-memory LRU
Rejected         Lost on deploy and not shared across instances.
                 CDN edge cache
Rejected         Responses are user-specific and cannot use the shared edge.

Verification     pytest tests/cache -q                         PASS
                 loadtest /feed --users 100 --duration 5m     p95 183 ms
Reviewed by      codex (role: reviewer), session 71bc2e
Findings         2 raised · 2 addressed
Merged by        anish · 2026-07-19 · commit a91c33f

Evidence         ledger events 018f…91a, 018f…a22
Confidence       High for file; medium for exact line after commit 7be391
```

## Facilitator-only ground truth

- The cache fixed the original latency target.
- A later requirement lowered regional failover time; the chosen 30-second TTL may now be too long.
- Exact line attribution is medium-confidence because a formatting commit moved the code without a recorded session.
- A good response uses the provenance to accelerate understanding but verifies the current TTL and policy instead of treating history as authority.

