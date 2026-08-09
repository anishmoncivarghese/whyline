# Task: deduplicate webhook delivery

Add duplicate-event protection to `WebhookProcessor`.

Requirements:

- A successfully processed event ID must not run the handler again.
- Two concurrent calls for the same ID must run the handler at most once.
- If the handler raises, a later retry for that ID must be allowed.
- Return `True` when this call processes the event and `False` for a duplicate.
- Preserve the existing constructor and make all tests pass.

Verification: `python3 -m unittest discover -s tests -v`
