import { expect, it } from "vitest";
import {
  globeAltitudeForZoom,
  globeZoomForAltitude,
  globeEventGeometries,
} from "./globeScene";
import { EventClusterIndex } from "./layerFactories/eventClusters";
import type { GeoEvent } from "../domain/types";
const event: GeoEvent = {
  id: "native",
  title: "Native fixture",
  category: "conflict",
  severity: "warning",
  locationPrecision: "exact",
  sources: [],
  limitations: [],
  relatedMarketIds: [],
  properties: {},
  geometry: { type: "Point", coordinates: [178, 20] },
};
it("round trips a real globe camera through shared 2D state", () => {
  for (const zoom of [0, 0.93, 1.5, 3, 6, 8])
    expect(globeZoomForAltitude(globeAltitudeForZoom(zoom))).toBeCloseTo(
      zoom,
      8,
    );
});
it("preserves observed/forecast geometry roles and exact coordinates across the date line", () => {
  const observed = {
    type: "LineString",
    coordinates: [
      [178, 20],
      [-178, 21],
    ],
  };
  const forecast = {
    type: "LineString",
    coordinates: [
      [-178, 21],
      [-175, 22],
    ],
  };
  const data = globeEventGeometries([
    {
      ...event,
      properties: {
        geometries: { observedTrack: observed, forecastTrack: forecast },
      },
    },
  ]);
  expect(data.map((d) => d.role)).toEqual(["observedTrack", "forecastTrack"]);
  expect(data.map((d) => d.geometry)).toEqual([observed, forecast]);
});
it("keeps all native polygon parts without invented point positions", () => {
  const parts = [
    [
      [
        [10, 10],
        [11, 10],
        [11, 11],
        [10, 10],
      ],
    ],
    [
      [
        [12, 12],
        [13, 12],
        [13, 13],
        [12, 12],
      ],
    ],
  ];
  const data = globeEventGeometries([
    { ...event, geometry: { type: "MultiPolygon", coordinates: parts } },
  ]);
  expect(data.map((d) => d.geometry.coordinates)).toEqual(
    parts.map((rings) => rings.map((ring) => [...ring].reverse())),
  );
  expect(data.every((d) => d.event.id === event.id)).toBe(true);
});
it("represents every identity in the shared globe index, including populations beyond the former low quality cap", () => {
  const events = Array.from({ length: 1000 }, (_, i) => ({
    ...event,
    id: `fixture:${i}`,
    severity: "info" as const,
    geometry: {
      type: "Point" as const,
      coordinates: [10 + (i % 10) / 100, 10] as [number, number],
    },
  }));
  const critical = {
    ...event,
    id: "critical",
    severity: "critical" as const,
    geometry: events[0]!.geometry,
  };
  const index = new EventClusterIndex();
  index.update([...events, critical]);
  const view = index.query(1.5, null);
  expect(view.singles.map((e) => e.id)).toContain("critical");
  const represented = [
    ...view.singles,
    ...view.clusters.flatMap((c) =>
      Array.from(
        { length: Math.ceil(c.count / 30) },
        (_, i) => index.readMembers(c, i * 30) || [],
      ).flat(),
    ),
  ];
  expect(new Set(represented.map((e) => e.id)).size).toBe(1001);
});
