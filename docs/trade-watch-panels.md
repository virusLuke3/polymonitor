# Whale Tracker and Flow Watch

Both panels show a bounded global sample of canonical OrderFilled fills, independent of the selected market. Selecting a market title opens that market through the workspace callback. Each panel owns its resource declaration and view. The existing explicit registry and shared runtime own scheduling, cancellation, request deduplication, retry, visibility and cache lifecycle. Neither panel imports the other's implementation.

## Refresh and recovery

- Frontend checks its same-origin seed endpoint every 30 seconds while visible, without HTTP cache reuse. Each resource requests independently, outside the sequential all-panel batch.
- The existing background watchers regenerate snapshots every 120 seconds. GET requests never start collectors or signal builders.
- Freshness is 300 seconds. Source failure is shown immediately even when the previous snapshot is younger than that window.
- Validated public browser snapshots speed repeat visits. Old snapshots can be displayed with a stale warning for at most 15 minutes; overdue, malformed or incompatible caches are rejected. Failed assessments cannot overwrite the saved successful snapshot.
- Checked time is the most recent successful frontend response; snapshot time remains the producer's actual generation time. A failed producer records its attempt and error without advancing snapshot time.
- Hidden pages pause requests and cancel pending work. Returning to visibility resumes the shared scheduler. Network timeouts cover response-body parsing; automatic retry uses bounded backoff.

## Whale Tracker

The existing large-fill selection uses recent-window notional quantiles, absolute minimum thresholds and relative market share. Near-resolved prices and repeated market/counterparty routes are screened to keep the small sample diverse. The panel is not a wallet qualification, profitability or insider-trading detector.

All/Buy/Sell filters actually filter the received sample. Maker and taker are identified separately using actual addresses. Transaction hashes are explicitly labeled and link to their transaction. Market title, canonical token, fill time, USD notional and token fill price are retained; unknown side or labels are never guessed.

## Flow Watch

Oracle-linked observations require the same market and a fill in the six-hour window before the Oracle event. Only events in the past 24 hours and a bounded recent-fill sample are examined. The panel does not claim historical completeness or causation.

When capacity remains, large fills are shown as a separate observation type. The producer reuses a fresh, compatible Whale seed through an explicit snapshot dependency, otherwise it reads the shared canonical large-fill source. It does not execute another fact scan when no recent Oracle events need matching.

All/Oracle-linked/Large trades filters display counts for the returned sample. Oracle source failure is partial coverage, not a successful finding of no Oracle-linked fills. Large trades alone are an available observation mode, not an anomaly verdict.

A size tier such as CRITICAL classifies trade size. It is not a probability of misconduct. A token price of 0.64 is displayed as 64.0 cents, not 64% confidence. Verified outcome labels are rechecked at the public API boundary; missing or failed projection leaves an explicitly unclassified token observation.

## Backend boundaries

`scripts/api/services/trade_watch/whales.py` owns large-fill selection; `flow.py` owns Oracle matching and fallback policy; `common.py` owns canonical fill formatting and the explicit snapshot dependency. `signal_service.py` preserves public API/cache entrypoints and read-time label validation. `signals_watcher.py` remains the sole snapshot publisher.

Validation covers scheduled DOM updates, failure preservation and recovery, hidden-page resume, stale-source signaling, real filter behavior, market navigation, exact token/fill identities, unknown values, Oracle failures and avoiding duplicate fact scans. Production acceptance must additionally observe an actual producer generation change being applied to the real page without a manual refresh.
