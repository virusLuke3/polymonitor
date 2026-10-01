# Polymonitor Agent Guidance

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
