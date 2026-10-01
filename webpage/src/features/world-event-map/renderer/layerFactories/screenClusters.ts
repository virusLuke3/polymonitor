import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import type { EventCluster, LabelProjection } from './eventClusters';
import { clusterMarkerSize, eventRepresentativePoint, markerSize, eventColor, SEVERITY_COLORS } from './shared';
import { isMajorWorldEvent } from '../eventDisclosure';
import { mapSymbolForEvent } from '../../config/mapSymbols';

/** Screen-space stacks are presentation only: member identities and coordinates
 * remain in the source index. Bounded spans prevent transitive continent stacks. */
export function screenClusterPresentation(input: { singles: GeoEvent[]; clusters: EventCluster[] },
  project: LabelProjection | undefined, selectedId: string | null) {
  if (!project) return input;
  type Item = { id: string; point: { x: number; y: number }; radius: number; event?: GeoEvent; cluster?: EventCluster };
  type Group = { items: Item[]; count: number; point: { x: number; y: number }; radius: number; bounds: number[]; removed?: boolean };
  const items: Item[] = [];
  for (const cluster of input.clusters) { const point = project(cluster.coordinates); if (point) items.push({ id: cluster.id, point, radius: clusterMarkerSize(cluster.count) / 2, cluster }); }
  for (const event of input.singles) {
    if (event.id === selectedId) continue;
    const coord = eventRepresentativePoint(event), point = coord && project(coord);
    if (point) items.push({ id: event.id, point, radius: markerSize(event, null) / 2, event });
  }
  items.sort((a, b) => b.radius - a.radius || a.id.localeCompare(b.id));
  const grid = new Map<string, Group[]>(), groups: Group[] = [];
  const cell = 80;
  for (const item of items) {
    const cx = Math.floor(item.point.x / cell), cy = Math.floor(item.point.y / cell);
    let match: Group | undefined;
    for (let x = cx - 1; x <= cx + 1; x++) for (let y = cy - 1; y <= cy + 1; y++) {
      for (const group of grid.get(`${x}:${y}`) || []) {
        const spanX = Math.max(group.bounds[2]!, item.point.x) - Math.min(group.bounds[0]!, item.point.x);
        const spanY = Math.max(group.bounds[3]!, item.point.y) - Math.min(group.bounds[1]!, item.point.y);
        if ((Boolean(group.items[0]?.cluster?.important || (group.items[0]?.event && isMajorWorldEvent(group.items[0].event))) === Boolean(item.cluster?.important || (item.event && isMajorWorldEvent(item.event)))) && spanX <= 76 && spanY <= 76 && Math.hypot(group.point.x - item.point.x, group.point.y - item.point.y) < group.radius + item.radius + 3) {
          if (!match || group.items[0]!.id < match.items[0]!.id) match = group;
        }
      }
    }
    if (match) {
      match.items.push(item); match.count += item.cluster?.count || 1; match.radius = clusterMarkerSize(match.count) / 2;
      match.bounds = [Math.min(match.bounds[0]!, item.point.x), Math.min(match.bounds[1]!, item.point.y), Math.max(match.bounds[2]!, item.point.x), Math.max(match.bounds[3]!, item.point.y)];
    } else {
      const group: Group = { items: [item], count: item.cluster?.count || 1, point: item.point, radius: item.radius, bounds: [item.point.x, item.point.y, item.point.x, item.point.y] };
      groups.push(group); const key = `${cx}:${cy}`; const bucket = grid.get(key) || []; bucket.push(group); grid.set(key, bucket);
    }
  }
  // Growing a stack can touch an earlier neighbour. Reconcile only local
  // buckets, keeping the original anchor and the same bounded span.
  for (const group of groups) {
    if (group.removed) continue;
    const cx = Math.floor(group.point.x / cell), cy = Math.floor(group.point.y / cell);
    let changed = true;
    while (changed) {
      changed = false;
      for (let x = cx - 1; x <= cx + 1; x++) for (let y = cy - 1; y <= cy + 1; y++) {
        for (const other of grid.get(`${x}:${y}`) || []) {
          if (other === group || other.removed) continue;
          const important = (item: Item) => Boolean(item.cluster?.important || (item.event && isMajorWorldEvent(item.event)));
          if (important(group.items[0]!) !== important(other.items[0]!)) continue;
          const bounds = [Math.min(group.bounds[0]!, other.bounds[0]!), Math.min(group.bounds[1]!, other.bounds[1]!),
            Math.max(group.bounds[2]!, other.bounds[2]!), Math.max(group.bounds[3]!, other.bounds[3]!)];
          if (bounds[2]! - bounds[0]! > 76 || bounds[3]! - bounds[1]! > 76
            || Math.hypot(group.point.x - other.point.x, group.point.y - other.point.y) >= group.radius + other.radius + 3) continue;
          group.items.push(...other.items); group.count += other.count; group.bounds = bounds;
          group.radius = clusterMarkerSize(group.count) / 2; other.removed = true; changed = true;
        }
      }
    }
  }
  const projectedIds = new Set(items.flatMap(item => item.event ? [item.event.id] : []));
  const singles = input.singles.filter(event => event.id === selectedId || !projectedIds.has(event.id));
  const clusters: EventCluster[] = [];
  for (const group of groups) {
    if (group.removed) continue;
    if (group.items.length === 1) { const item = group.items[0]!; if (item.cluster) clusters.push(item.cluster); else if (item.event) singles.push(item.event); continue; }
    const severityCounts: Record<GeoEventSeverity, number> = { info: 0, watch: 0, warning: 0, critical: 0 };
    const typeCounts: Record<string, number> = {};
    const members: EventCluster['members'] = [];
    let count = 0;
    const bounds = [Infinity, Infinity, -Infinity, -Infinity] as [number, number, number, number];
    for (const item of group.items) {
      const cluster = item.cluster, event = item.event;
      count += cluster?.count || 1;
      if (cluster) {
        members.push(...cluster.members);
        for (const severity of Object.keys(severityCounts) as GeoEventSeverity[]) severityCounts[severity] += cluster.severityCounts?.[severity] || 0;
        for (const [type, n] of Object.entries(cluster.typeCounts)) typeCounts[type] = (typeCounts[type] || 0) + n;
      } else if (event) { members.push({ eventId: event.id, count: 1 }); severityCounts[event.severity]++;
        const type = 'hazardKind' in event ? String(event.hazardKind) : event.category; typeCounts[type] = (typeCounts[type] || 0) + 1; }
      const p = event && eventRepresentativePoint(event), b = cluster?.bounds || (p ? [p[0], p[1], p[0], p[1]] : bounds);
      bounds[0] = Math.min(bounds[0], b[0]!); bounds[1] = Math.min(bounds[1], b[1]!); bounds[2] = Math.max(bounds[2], b[2]!); bounds[3] = Math.max(bounds[3], b[3]!);
    }
    const anchor = group.items[0]!;
    const times = group.items.flatMap(item => item.cluster?.occurrenceRange || (item.event?.occurredAt ? [Date.parse(item.event.occurredAt)] : [])).filter(Number.isFinite);
    const mixed = Object.keys(typeCounts).length > 1;
    const severity = (['critical', 'warning', 'watch', 'info'] as const).find(level => severityCounts[level] > 0)!;
    clusters.push({ kind: 'event-cluster', mixed, important: Boolean(anchor.cluster?.important || (anchor.event && isMajorWorldEvent(anchor.event))), id: `stack:${anchor.id}`,
      coordinates: anchor.cluster?.coordinates || eventRepresentativePoint(anchor.event!)!, members, count, typeCounts, severityCounts,
      occurrenceRange: times.length ? [Math.min(...times), Math.max(...times)] : undefined,
      severity,
      color: mixed && !(anchor.cluster?.important || (anchor.event && isMajorWorldEvent(anchor.event))) ? [157, 174, 184, 245] : anchor.event ? eventColor({ ...anchor.event, severity }) : [...SEVERITY_COLORS[severity]],
      bounds, expansionZoom: 8, symbol: mixed ? 'signal' : anchor.cluster?.symbol || mapSymbolForEvent(anchor.event!),
      label: mixed ? 'mixed events' : Object.keys(typeCounts)[0]?.replace(/-/g, ' '),
      generation: input.clusters[0]?.generation ?? 0,
    });
  }
  // Draw protected stacks last; an ordinary coincident stack must not cover their center.
  clusters.sort((a,b) => Number(Boolean(a.important)) - Number(Boolean(b.important)));
  return { singles, clusters };
}
