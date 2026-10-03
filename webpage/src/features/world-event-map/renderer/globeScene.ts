import type { GeoEvent, GeoEventGeometry, GeoPoint } from "../domain/types";

// Inverse camera conversions keep 2D links and the real globe POV in one state.
export const globeAltitudeForZoom = (zoom: number) =>
  Math.max(0.012, Math.min(5, 5 / 2 ** zoom));
export const globeZoomForAltitude = (altitude: number) =>
  Math.max(0, Math.min(12, Math.log2(5 / Math.max(0.001, altitude))));
export type GlobeGeometry = {
  event: GeoEvent;
  geometry: GeoEventGeometry;
  role: string;
};

/** three-globe's spherical tessellator uses clockwise exteriors (the inverse of
 * RFC 7946). Adapt winding only; preserve every source coordinate and hole. */
export function globePolygonGeometry<
  T extends Extract<GeoEventGeometry, { type: "Polygon" | "MultiPolygon" }>,
>(geometry: T): T {
  const polygon = (rings: number[][][]) =>
    rings.map((ring, index) => {
      let area = 0,
        previous = ring[0]?.[0] || 0;
      const unwrapped = ring.map((point) => {
        let lon = point[0]!;
        while (lon - previous > 180) lon -= 360;
        while (lon - previous < -180) lon += 360;
        previous = lon;
        return [lon, point[1]!] as const;
      });
      for (let i = 0; i < unwrapped.length; i++) {
        const a = unwrapped[i]!,
          b = unwrapped[(i + 1) % unwrapped.length]!;
        area += a[0] * b[1] - b[0] * a[1];
      }
      return (index === 0 ? area > 0 : area < 0) ? [...ring].reverse() : ring;
    });
  return {
    ...geometry,
    coordinates:
      geometry.type === "Polygon"
        ? polygon(geometry.coordinates)
        : geometry.coordinates.map(polygon),
  } as T;
}

/** Keep native areas/paths and named observed/forecast geometry. Never invent centroids. */
export function globeEventGeometries(events: GeoEvent[]): GlobeGeometry[] {
  return events.flatMap((event) => {
    const named = event.properties.geometries as
      | Record<string, unknown>
      | undefined;
    const entries: Array<[string, unknown]> =
      named && typeof named === "object" ? Object.entries(named) : [];
    if (
      !entries.some(
        ([role]) => role === "observedTrack" || role === "forecastTrack",
      )
    )
      entries.unshift(["primary", event.geometry]);
    return entries.flatMap(([role, value]): GlobeGeometry[] => {
      if (!value || typeof value !== "object") return [];
      const g = value as { type: string; coordinates: any };
      if (g.type === "MultiLineString")
        return g.coordinates.map((coordinates: GeoPoint[]) => ({
          event,
          role,
          geometry: { type: "LineString" as const, coordinates },
        }));
      if (g.type === "LineString")
        return [
          {
            event,
            role,
            geometry: { type: "LineString", coordinates: g.coordinates },
          },
        ];
      if (g.type === "MultiPolygon")
        return g.coordinates.map((coordinates: number[][][]) => ({
          event,
          role,
          geometry: globePolygonGeometry({
            type: "Polygon" as const,
            coordinates,
          }),
        }));
      if (g.type === "Polygon")
        return [
          {
            event,
            role,
            geometry: globePolygonGeometry(
              g as Extract<GeoEventGeometry, { type: "Polygon" }>,
            ),
          },
        ];
      if (g.type === "Point")
        return [{ event, role, geometry: g as GeoEventGeometry }];
      return [];
    });
  });
}
