Deduplicate on event ID, including concurrent deliveries. Reserve an ID before calling the handler, but remove that reservation if the handler fails so the vendor can retry. A lock around the shared set should be enough; do not hold it while the handler runs.

