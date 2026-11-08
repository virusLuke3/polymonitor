# Total Monitor

Production module `sports-total-monitor` is enabled through the standard registry and default-layout reconciliation. It owns only `index.tsx` and its body stylesheet; it imports no sibling Panel implementation.

## Data contract

Owner: **NBA game summary**, implemented in `scripts/api/services/sports_expansion/`. NBA event discovery reuses the existing `snapshot:sports:nba / {"limit": 10}` owner. No new scoreboard requests or GRID copies are made for these views. Acquisition, raw evidence archive, retry state, last-good retention and projections are shared at family level. See [domain contract](../../../../../scripts/api/services/sports_expansion/README.md).

Read-only API `/runtime/external/sports-total-monitor` → shared `externalPanel` Runtime resource `external:sports-total-monitor:v1` → validated body. Public GET, tab changes and manual refresh do not acquire upstream data. Complete resource identity includes the Panel projection/schema; selected source-native event/tournament/athlete IDs remain in the payload. Local tabs filter the bounded acquired result, not all worldwide events.

Source data remains in the existing SnapshotStore, namespace `source:external-panels:v1`, with family keys listed in the domain contract. Raw source revisions are archived by the common evidence store. Source event time, unknown publication time, successful acquisition, attempted acquisition and browser checks are distinct. Successful empty lists clear old data; failures retain original times within the family retention window.

## Visual contract

The approved sports and market-domain previews are design references; their fictional fixtures are not imported. Body design: **white total + purple reference line + cyan/orange stacked quarter bars**. This preserves the common 11px mono header, 12px body, 10px metadata and 20–28px focal numerals, with existing semantic/category tokens. The parent workspace owns borders, five columns, dimensions, scrolling and refresh.

Interactions are selectors, data tabs and evidence details backed by actual acquired content. Empty/failed responses use the real source state instead of invented zeros.

## Scope and acceptance

No model projects a final score; unknown quarters and quote times remain unknown.

2026-11-08: actual source requests, archival write and this read projection were exercised against the installed snapshot database; source acquisition was successful. Tests in `tests/test_sports_expansion.py` cover identity, zero versus missing, DNP, source order, retention and failure preservation. Global registry/layout, deployed release identity, desktop/mobile screenshots and complete-cycle observation are verified by the integration task; this document does not itself claim production acceptance.
