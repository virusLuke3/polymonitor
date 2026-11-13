# Big Tech Market Cap source contract

Reuse `TechPanelsWatcher`, `runtime:tech:big-tech-market-cap` / `v1`, and the
existing runtime API and browser owner. Yahoo owns quotes and their exchange
timestamps; Nasdaq owns published market caps with independent receipt times.
Never derive missing caps from hardcoded share counts or update either source's
clock because the other succeeded.

The watcher injects cache reads and confirmed writes from its existing
`SeedMetaStore`; it does not maintain a second cache adapter or an unused
snapshot-builder callback. Finance and tech API projections share item limiting
in `seed_recovery.limit_snapshot_items`, preserving row order and total counts.

The existing three-worker pool completes the 24-symbol quote batch before
reading market caps. Both batches share the same 180-second collection deadline;
there is no new executor, acquisition frequency or request-time collection.
A stalled cap source therefore cannot consume the quote batch's budget first.
Provider routes are configured in the private `.env` and must be verified with
inherited environment proxies disabled. Successful caps have a five-minute
worker cache; failed caps can retain at most 30 minutes with original receipt
time and explicit stale status. Missing/expired caps remain unavailable.

`tests/test_tech_panels.py` covers independent source failure, deadline ordering,
original clocks, expiration and rejection of legacy estimated caps. Acceptance
requires fresh provider reads for each of the 24 symbols, not only 16 visible
rows or a nonempty previous snapshot.
