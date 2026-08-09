# Source-session truth

The prior agent found the injected monotonic clock and decided to store `(value, expires_at)` or parallel expiry state. Expiration is `now >= expires_at`. `ttl_seconds=0` must expire immediately, so the implementation cannot use a truthiness check. Negative TTL is rejected before mutating state. Tests must advance the fake clock rather than sleep.

Critical miss: losing falsy cached values or treating zero TTL as no TTL.

