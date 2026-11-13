# Polymonitor Agent Guidance

## Keep implementation and deliverables small

The user's standing preference is: do not add tests or persist intermediate
artifacts by default. Prefer direct changes to existing owners; remove unused
code instead of adding compatibility wrappers, speculative abstractions or
repeated validation of already validated internal data. Keep validation at real
input boundaries and necessary network recovery and data-identity checks.
Verify changes with builds, reference checks and actual runtime reads. Existing
CI remains available; do not create tests merely to mirror an implementation.
Use in-memory inspection, and delete task-created scratch/build outputs after
use. When a file deliverable is requested, keep one final format unless the user
explicitly asks for several. Reuse the existing feature document instead of
adding a new audit/report/manifest stack. Preserve live data and unrelated work.
For code cleanup, use the installed `code-simplification` skill and trace
frontend, API, worker and CLI consumers before calling code unused. A missing
route registration does not make a still-used product service disposable.

Before adding or upgrading any Panel, read
`document/开发/Panel开发统一指南.md`, `docs/panel-data-pipeline.md`, and
`docs/panel-data-cadence.md`. For data requests, shared resources or caching,
also read `docs/panel-resource-contract.md` and `docs/panel-runtime-lifecycle.md`.
Apply these contracts to the existing data owner, acquisition, storage, API and
shared Runtime before implementing the view. Record the chosen chain, storage
identity, independent clocks, resource budgets and acceptance evidence in the
Panel's existing feature index or domain document; pure views link the reused
owner instead of creating another collector or cache. Dated audits and incident
records are supporting evidence, not current-health claims or default deployment
configuration. WorldMonitor storage products are references, not assumed local
infrastructure. If the ignored local guide is absent in a clean checkout, use
the public `docs/panel-modules.md` together with these data contracts and report
that the local guide was unavailable.

For any task that changes the 2D map, its controls, its data adapters, its
runtime APIs, its fallback renderer, or its deployment behavior, read
`document/地图/WorldEventMap实施指导.md` in full before editing.

Treat that document as the product, architecture, robustness, testing, and
release contract for World Event Map work. Do not expand
`webpage/src/components/WeatherDeckMap.tsx`, fabricate geographic coordinates,
or add visible map controls without real behavior.

Preserve unrelated user changes in a dirty worktree. Keep implementation and
verification scoped to the requested task, and report unverified production
states explicitly.

Newly developed Panels must be enabled by default and appear directly in the
existing workspace unless the user explicitly requests otherwise. Use the
shared default-panel reconciliation for local and account layouts. Do not add
special navigation or require manual activation, layout resets, or cache
clearing. Verify discovery from the ordinary homepage with an existing layout,
and preserve its order, sizes, and subsequent explicit panel hides.

For frontend changes, the user has authorized committing and pushing the task's
own changes, deploying that exact commit to GCP, and verifying the real
`https://polymonitor.club` UI. Preserve unrelated work, stage only owned paths or
hunks, and build the release from a clean checkout of the pushed commit. Local
tests are preflight checks, not production acceptance. Capture desktop and
mobile screenshots from the real production URL without substituted APIs or
tiles, verify the deployed release identity, and report remaining failures.

Work in the original project checkout on `main`. Do not create task branches or
additional Git worktrees unless the user explicitly requests them. For clean
release builds, export the pushed commit with `git archive` into a temporary
build directory instead of creating a worktree.

Commit only changes owned by the current task. If a file also contains unrelated
user or task changes, stage only the owned hunks; never stage the whole mixed
file. Preserve all other staged, unstaged, and untracked work.
