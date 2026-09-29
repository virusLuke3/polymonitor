import { screenClusterPresentation } from './screenClusters';
import type { Feature, Point } from 'geojson';
import Supercluster from 'supercluster';
import { worldEventLayerById, worldEventLayerIdForEvent } from '../../config/layerRegistry';
import { mapSymbolForEvent, type MapSymbolKey } from '../../config/mapSymbols';
import type { GeoEvent, GeoEventSeverity } from '../../domain/types';
import { disclosureTierForZoom, eventVisibleAtZoom } from '../eventDisclosure';
import { boundsIntersect, eventGeometryBounds, eventRepresentativePoint, isHazardEvent, eventColor, clusterMarkerSize, markerSize, SEVERITY_COLORS } from './shared';
export { eventDisclosureTier, eventVisibleAtZoom } from '../eventDisclosure';

export type EventCluster = {
  kind: 'event-cluster';
  id: string;
  coordinates: [number, number];
  members: ClusterMemberReference[];
  generation: number;
  mixed?: boolean;
  occurrenceRange?: [number, number];
  typeCounts: Record<string, number>;
  count: number;
  severityCounts?: Record<GeoEventSeverity, number>;
  severity: GeoEventSeverity;
  bounds: [number, number, number, number];
  expansionZoom: number;
  color: [number, number, number, number];
  symbol: MapSymbolKey;
  label?: string;
  badge?: string;
};

export type ClusterMemberReference = { eventId: string; count: number } | {
  bucketId: string; clusterId: number; generation: number; count: number; excludedId: string | null;
};
export type ClusterSelection = { id: string; count: number; readPage: (offset: number, limit?: number) => GeoEvent[] | null };

type ClusterPointProperties = {
  eventId: string; severityRank: number;
  west: number; south: number; east: number; north: number;
  representativeEventId: string;
  info: number; watch: number; warning: number; critical: number;
  earliest: number; latest: number;
};

type ClusterAggregateProperties = ClusterPointProperties;

type ClusterBucket = {
  id: string;
  layerId: string;
  index: Supercluster<ClusterPointProperties, ClusterAggregateProperties>;
  eventById: Map<string, GeoEvent>;
};

type UnclusteredBucket = { layerId: string; events: GeoEvent[] };
export type ScreenBox = [number, number, number, number];
export type LabelProjection = (position: [number, number]) => { x: number; y: number } | null;

const WORLD_VIEWPORT: [number, number, number, number] = [-180, -85, 180, 85];

const SEVERITIES: readonly GeoEventSeverity[] = ['info', 'watch', 'warning', 'critical'];
export const SEVERITY_RANK: Record<GeoEventSeverity, number> = {
  info: 0,
  watch: 1,
  warning: 2,
  critical: 3,
};

function pointFeature(event: GeoEvent, coordinates: [number, number]): Feature<Point, ClusterPointProperties> {
  const [lon, lat] = coordinates;
  const bounds = eventGeometryBounds(event) || [lon, lat, lon, lat];
  const severityRank = SEVERITY_RANK[event.severity];
  const occurred = Date.parse(event.occurredAt || '');
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates },
    properties: {
      eventId: event.id,
      severityRank,
      west: bounds[0],
      south: bounds[1],
      east: bounds[2],
      north: bounds[3],
      representativeEventId: event.id,
      info: event.severity === 'info' ? 1 : 0,
      watch: event.severity === 'watch' ? 1 : 0,
      warning: event.severity === 'warning' ? 1 : 0,
      critical: event.severity === 'critical' ? 1 : 0,
      earliest: Number.isFinite(occurred) ? occurred : Infinity,
      latest: Number.isFinite(occurred) ? occurred : -Infinity,
    },
  };
}

function eventSemanticKey(event: GeoEvent) {
  if (isHazardEvent(event)) return event.hazardKind;
  if (event.category === 'conflict' || event.category === 'unrest') {
    return `conflict-${String(event.properties.violenceType || 'unknown')}`;
  }
  return event.category;
}

function semanticLabel(event: GeoEvent) {
  if (isHazardEvent(event)) return event.hazardKind.replace(/-/g, ' ');
  if (event.category === 'conflict' || event.category === 'unrest') {
    const violenceType = String(event.properties.violenceType || '');
    if (violenceType === '1') return 'state-based conflict';
    if (violenceType === '2') return 'non-state conflict';
    if (violenceType === '3') return 'one-sided violence';
  }
  return event.category.replace(/-/g, ' ');
}

function semanticBadge(event: GeoEvent) {
  if (isHazardEvent(event)) {
    switch (event.hazardKind) {
      case 'earthquake': return 'EQ';
      case 'volcano': return 'VO';
      case 'severe-storm':
      case 'tornado': return 'ST';
      case 'tropical-cyclone': return 'CY';
      case 'flood':
      case 'tsunami': return 'FL';
      case 'wildfire':
      case 'fire-detection': return 'FI';
      case 'extreme-heat': return 'HT';
      case 'extreme-cold': return 'CL';
      case 'temperature-anomaly':
      case 'precipitation-anomaly':
      case 'other-weather-anomaly': return 'AN';
    }
  }
  if (event.category === 'conflict' || event.category === 'unrest') {
    const violenceType = String(event.properties.violenceType || '');
    if (violenceType === '1') return 'SB';
    if (violenceType === '2') return 'NS';
    if (violenceType === '3') return 'OS';
    return 'CF';
  }
  if (event.category === 'intel') return 'IN';
  return '';
}

function inViewport(event: GeoEvent, viewport: [number, number, number, number]) {
  const position = eventRepresentativePoint(event);
  if (!position) return false;
  const [lon, lat] = position;
  return lon >= viewport[0] && lon <= viewport[2] && lat >= viewport[1] && lat <= viewport[3];
}

function isClusterableMarker(event: GeoEvent) {
  if (event.geometry?.type === 'Point') return true;
  return isHazardEvent(event)
    && (event.geometry?.type === 'Polygon' || event.geometry?.type === 'MultiPolygon');
}

/** Persistent source index. Viewport/zoom queries never rebuild Supercluster. */
export class EventClusterIndex {
  private source: GeoEvent[] | null = null;
  private eventById = new Map<string, GeoEvent>();
  private unclustered: UnclusteredBucket[] = [];
  private buckets: ClusterBucket[] = [];
  private queryKey = '';
  private queryResult: { singles: GeoEvent[]; clusters: EventCluster[] } | null = null;
  buildCount = 0;
  leafReadCount = 0;
  queryCount = 0;
  private selectedKey = '';
  private selectedAncestors = new Map<string, Set<number>>();
  lastPresentation: { singles: GeoEvent[]; clusters: EventCluster[] } | null = null;
  private presentationViewport = WORLD_VIEWPORT;
  private presentationZoom = 0;

  update(events: GeoEvent[]) {
    if (events === this.source) return;
    this.source = events;
    this.eventById = new Map();
    this.unclustered = [];
    this.buckets = [];
    this.queryKey = '';
    this.queryResult = null;
    this.lastPresentation = null;
    this.selectedKey = '';
    this.selectedAncestors.clear();
    this.ordinalCache.clear();
    const grouped = new Map<string, GeoEvent[]>();
    for (const event of events) {
      if (!isClusterableMarker(event)) continue;
      if (event.properties.mapEntity === 'air-hub' || event.properties.mapEntity === 'live-aircraft') continue;
      if (!eventRepresentativePoint(event)) continue;
      const layerId = worldEventLayerIdForEvent(event);
      if (!layerId) continue;
      this.eventById.set(event.id, event);
      const bucketId = `${layerId}:${eventSemanticKey(event)}`;
      const bucket = grouped.get(bucketId) || [];
      bucket.push(event);
      grouped.set(bucketId, bucket);
    }

    for (const [id, bucketEvents] of grouped) {
      const layerId = id.split(':', 1)[0]!;
      const layer = worldEventLayerById(layerId);
      if (!layer?.cluster || layer.clusterRadius <= 0) {
        this.unclustered.push({ layerId, events: bucketEvents });
        continue;
      }
      const index = new Supercluster<ClusterPointProperties, ClusterAggregateProperties>({
        radius: layer.clusterRadius,
        minPoints: layer.clusterMinPoints,
        maxZoom: 7,
        map: (properties) => ({ ...properties }),
        reduce: (accumulated, properties) => {
          if (properties.severityRank > accumulated.severityRank) {
            accumulated.severityRank = properties.severityRank;
            accumulated.representativeEventId = properties.representativeEventId;
          }
          for (const severity of SEVERITIES) accumulated[severity] += properties[severity];
          accumulated.earliest = Math.min(accumulated.earliest, properties.earliest);
          accumulated.latest = Math.max(accumulated.latest, properties.latest);
          accumulated.west = Math.min(accumulated.west, properties.west);
          accumulated.south = Math.min(accumulated.south, properties.south);
          accumulated.east = Math.max(accumulated.east, properties.east);
          accumulated.north = Math.max(accumulated.north, properties.north);
        },
      });
      const eventById = new Map(bucketEvents.map((event) => [event.id, event]));
      index.load(bucketEvents.map((event) => pointFeature(event, eventRepresentativePoint(event)!)));
      this.buckets.push({ id, layerId, index, eventById });
    }
    this.buildCount += 1;
  }

  /** Ancestors are discovered only on selection/data changes, never per pan. */
  private select(selectedId: string | null) {
    const key = `${this.buildCount}:${selectedId || ''}`;
    if (key === this.selectedKey) return;
    this.selectedKey = key; this.selectedAncestors.clear();
    if (!selectedId) return;
    for (const bucket of this.buckets) {
      if (!bucket.eventById.has(selectedId)) continue;
      const ancestors = new Set<number>();
      const visit = (feature: ReturnType<typeof bucket.index.getClusters>[number]): boolean => {
        if (!('cluster' in feature.properties)) return feature.properties.eventId === selectedId;
        const id = Number(feature.properties.cluster_id);
        if (bucket.index.getChildren(id).some(visit)) { ancestors.add(id); return true; }
        return false;
      };
      bucket.index.getClusters(WORLD_VIEWPORT, 0).some(visit);
      this.selectedAncestors.set(bucket.id, ancestors);
    }
  }

  selection(cluster: EventCluster): ClusterSelection {
    const generation = cluster.generation;
    return { id: cluster.id, count: cluster.count, readPage: (offset, limit = 30) =>
      generation === this.buildCount ? this.readMembers(cluster, offset, limit) : null };
  }

  /** Bounded leaf access exists only at the member-list boundary. Stale index
   * references fail closed; a reused Supercluster id cannot select new data. */
  readMembers(cluster: Pick<EventCluster, 'members'> & Partial<Pick<EventCluster, 'generation'>>, offset = 0, limit = 30): GeoEvent[] | null {
    if (cluster.generation != null && cluster.generation !== this.buildCount) return null;
    const result: GeoEvent[] = [];
    let skip = Math.max(0, Math.floor(offset));
    const pageSize = Math.max(1, Math.min(30, Math.floor(limit)));
    for (const member of cluster.members) {
      if ('generation' in member && member.generation !== this.buildCount) return null;
      if (skip >= member.count) { skip -= member.count; continue; }
      if ('eventId' in member) { const event = this.eventById.get(member.eventId); if (event) result.push(event); skip = 0; }
      else {
        const bucket = this.buckets.find(b => b.id === member.bucketId);
        if (!bucket) return null;
        const ordinal = member.excludedId ? this.excludedOrdinal(bucket, member.clusterId, member.excludedId) : -1;
        const rawOffset = skip + Number(ordinal >= 0 && ordinal <= skip);
        this.leafReadCount++;
        const leaves = bucket.index.getLeaves(member.clusterId, pageSize - result.length + Number(ordinal >= rawOffset), rawOffset);
        const events = leaves.map(leaf => bucket.eventById.get(leaf.properties.eventId)!)
          .filter(event => event && event.id !== member.excludedId);
        result.push(...events.slice(0, pageSize - result.length)); skip = 0;
      }
      if (result.length >= pageSize) break;
    }
    return result;
  }

  private ordinalCache = new Map<string, number>();
  private excludedOrdinal(bucket: ClusterBucket, clusterId: number, eventId: string) {
    const key = `${this.buildCount}:${bucket.id}:${clusterId}:${eventId}`;
    const cached = this.ordinalCache.get(key); if (cached != null) return cached;
    let ordinal = 0;
    const visit = (id: number): boolean => {
      for (const child of bucket.index.getChildren(id)) {
        if ('cluster' in child.properties) {
          if (visit(Number(child.properties.cluster_id))) return true;
        } else if (child.properties.eventId === eventId) return true;
        else ordinal++;
      }
      return false;
    };
    const found = visit(clusterId) ? ordinal : -1; this.ordinalCache.set(key, found); return found;
  }

  /** Explicit opt-in diagnostic; never called by rendering or hover. */
  diagnostics(includeMembers = false) {
    const presentation = this.lastPresentation;
    const membership: Record<string, string> = {};
    if (includeMembers && presentation) {
      for (const event of presentation.singles) membership[event.id] = 'single';
      for (const cluster of presentation.clusters) {
        for (let offset = 0; offset < cluster.count; offset += 30) for (const event of this.readMembers(cluster, offset) || [])
          membership[event.id] = membership[event.id] ? 'DUPLICATE' : `${cluster.mixed ? 'mixed' : 'cluster'}:${cluster.id}`;
      }
      for (const event of this.source || []) if (!membership[event.id]) {
        const bounds = eventGeometryBounds(event);
        const layerId = worldEventLayerIdForEvent(event), layer = layerId && worldEventLayerById(layerId);
        membership[event.id] = !bounds ? 'unlocatable:no valid geometry'
          : !boundsIntersect(bounds, this.presentationViewport) ? 'offscreen:geometry outside query bounds'
          : !layer || this.presentationZoom < layer.minZoom ? 'explicitly-disabled:layer zoom requirement'
          : isHazardEvent(event) && event.hazardKind === 'fire-detection' && this.presentationZoom < 4 ? 'observation:raw satellite texture'
          : !eventVisibleAtZoom(event, this.presentationZoom, null) ? 'explicitly-disabled:zoom disclosure'
          : 'single:geometry or aviation layer';
      }
    }
    return { buildCount: this.buildCount, queryCount: this.queryCount, leafReadCount: this.leafReadCount,
      sourceCount: this.source?.length || 0, membership,
      denominator: 'Input records after user filters; satellite observations remain a separate population. Paths and footprints do not add records.',
      markers: [...(presentation?.clusters || []).map(c => ({ id: c.id, coordinates: c.coordinates, radius: clusterMarkerSize(c.count) / 2, count: c.count, mixed: c.mixed || false })),
        ...(presentation?.singles || []).map(e => ({ id: e.id, coordinates: eventRepresentativePoint(e), radius: markerSize(e, null) / 2, count: 1, mixed: false }))] };
  }

  hitSelection(point: { x: number; y: number }, project: LabelProjection, touch = false): ClusterSelection | null {
    const presentation = this.lastPresentation;
    if (!presentation) return null;
    const radius = touch ? 20 : 11;
    const hits = [
      ...presentation.clusters.map(cluster => ({ id: cluster.id, coordinates: cluster.coordinates, radius: clusterMarkerSize(cluster.count) / 2, count: cluster.count, members: cluster.members })),
      ...presentation.singles.map(event => ({ id: event.id, coordinates: eventRepresentativePoint(event)!, radius: markerSize(event, null) / 2, count: 1, members: [{ eventId: event.id, count: 1 }] as ClusterMemberReference[] })),
    ].filter(item => { const p = item.coordinates && project(item.coordinates); return p && Math.hypot(p.x - point.x, p.y - point.y) <= item.radius + radius; });
    if (hits.length < 2) return null;
    const generation = this.buildCount, members = hits.flatMap(hit => hit.members);
    return { id: `hits:${hits.map(hit => hit.id).sort().join('|')}`, count: hits.reduce((n, hit) => n + hit.count, 0),
      readPage: (offset, limit = 30) => generation === this.buildCount ? this.readMembers({ members }, offset, limit) : null };
  }

  presentation(zoom: number, selectedId: string | null, viewport?: [number, number, number, number], project?: LabelProjection) {
    this.presentationZoom = zoom; this.presentationViewport = viewport || WORLD_VIEWPORT;
    this.lastPresentation = screenClusterPresentation(this.query(zoom, selectedId, viewport), project, selectedId);
    for (const cluster of this.lastPresentation.clusters) cluster.generation = this.buildCount;
    return this.lastPresentation;
  }

  query(zoom: number, selectedEventId: string | null,
    viewport: [number, number, number, number] = WORLD_VIEWPORT) {
    const normalizedZoom = Math.max(0, Math.floor(zoom));
    const key = `${normalizedZoom}|${disclosureTierForZoom(zoom)}|${selectedEventId || ''}|${viewport.map(value => value.toFixed(3)).join(':')}`;
    if (key === this.queryKey && this.queryResult) return this.queryResult;
    this.queryCount++;
    this.select(selectedEventId);
    const selected = selectedEventId ? this.eventById.get(selectedEventId) : undefined;
    const singles: GeoEvent[] = selected ? [selected] : [];
    const addVisible = (event: GeoEvent) => {
      if (event.id === selectedEventId || !inViewport(event, viewport)) return;
      if (eventVisibleAtZoom(event, zoom, selectedEventId)) singles.push(event);
    };
    for (const bucket of this.unclustered) {
      const layer = worldEventLayerById(bucket.layerId);
      if (!layer || Math.max(0, zoom) < layer.minZoom) continue;
      for (const event of bucket.events) addVisible(event);
    }
    const clusters: EventCluster[] = [];
    for (const bucket of this.buckets) {
      const layer = worldEventLayerById(bucket.layerId);
      if (!layer || Math.max(0, zoom) < layer.minZoom) continue;
      for (const feature of bucket.index.getClusters(viewport, normalizedZoom)) {
        if (!('cluster' in feature.properties)) {
          const event = bucket.eventById.get(feature.properties.eventId); if (event) addVisible(event); continue;
        }
        const clusterId = Number(feature.properties.cluster_id);
        const properties = feature.properties as typeof feature.properties & ClusterAggregateProperties;
        const representative = bucket.eventById.get(properties.representativeEventId);
        if (!representative) continue;
        const excluded = Boolean(selected && this.selectedAncestors.get(bucket.id)?.has(clusterId));
        const count = Number(feature.properties.point_count) - Number(excluded);
        if (!count) continue;
        if (count === 1) {
          const other = bucket.index.getChildren(clusterId).find(child => !('cluster' in child.properties) && child.properties.eventId !== selectedEventId);
          if (other && !('cluster' in other.properties)) { const event = bucket.eventById.get(other.properties.eventId); if (event) addVisible(event); continue; }
        }
        const severityCounts = Object.fromEntries(SEVERITIES.map(level => [level, properties[level] - Number(excluded && selected?.severity === level)])) as Record<GeoEventSeverity, number>;
        const severity = [...SEVERITIES].reverse().find(level => severityCounts[level] > 0) || 'info';
        clusters.push({ kind: 'event-cluster', id: `cluster:${bucket.id}:${clusterId}`,
          coordinates: feature.geometry.coordinates as [number, number],
          members: [{ bucketId: bucket.id, clusterId, generation: this.buildCount, count, excludedId: excluded ? selectedEventId : null }],
          generation: this.buildCount, typeCounts: { [eventSemanticKey(representative)]: count }, count, severityCounts, severity,
          occurrenceRange: !excluded && Number.isFinite(properties.earliest) ? [properties.earliest, properties.latest] : undefined,
          bounds: [properties.west, properties.south, properties.east, properties.north],
          expansionZoom: bucket.index.getClusterExpansionZoom(clusterId),
          color: isHazardEvent(representative) ? eventColor({ ...representative, severity }) : [...SEVERITY_COLORS[severity]],
          symbol: mapSymbolForEvent(representative), label: semanticLabel(representative), badge: semanticBadge(representative),
        });
      }
    }
    this.queryKey = key;
    this.queryResult = { singles, clusters };
    return this.queryResult;
  }
}

export function clusterEventPoints(events: GeoEvent[], zoom: number, selectedEventId: string | null,
  viewport: [number, number, number, number] = WORLD_VIEWPORT) {
  const index = new EventClusterIndex(); index.update(events); return index.query(zoom, selectedEventId, viewport);
}
