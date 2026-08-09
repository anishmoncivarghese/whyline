# Source-session truth

The prior agent chose a lock-protected set of reserved/successful IDs. It atomically checks and adds under the lock, releases the lock before calling the handler, and removes the ID under the lock if the handler raises. The exception must propagate. Unrelated IDs must not be serialized behind handler execution.

Critical miss: marking only after success, which fails the concurrent-delivery requirement.

