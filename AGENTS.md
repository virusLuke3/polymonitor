# Polymonitor Agent Guidance

For any task that changes the 2D map, its controls, its data adapters, its
runtime APIs, its fallback renderer, or its deployment behavior, read
`docs/world-event-map-implementation-guide.md` in full before editing.

Treat that document as the product, architecture, robustness, testing, and
release contract for World Event Map work. Do not expand
`webpage/src/components/WeatherDeckMap.tsx`, fabricate geographic coordinates,
or add visible map controls without real behavior.

Preserve unrelated user changes in a dirty worktree. Keep implementation and
verification scoped to the requested task, and report unverified production
states explicitly.
