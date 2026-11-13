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
`document/开发/Panel开发统一指南.md` and its existing domain guide when available.
The user removed the root `docs/` directory; do not recreate it or another
audit/report directory. Keep `document/` unchanged unless explicitly requested.
If a local guide is unavailable, report that limitation and trace the existing
implementation instead of inventing a replacement guide.

Reuse the existing data owner, acquisition, storage, API and shared Runtime.
Keep keys, source endpoints and proxy routes in private `.env` configuration;
maintain placeholder declarations in `.env.example`. Preserve source identity,
original timestamps, bounded retries and retention; never renew failed data or
turn missing values into zero. Check resource budgets before requests that use
Chainstack quota. A view does not create a second collector or cache. Record
verification in the task response or an existing feature index, not new files.

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
