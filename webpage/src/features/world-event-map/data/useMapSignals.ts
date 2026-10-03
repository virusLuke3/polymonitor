import { useEffect, useMemo, useState } from "preact/hooks";
import { fetchMapSignalSource, fetchTransportMapSource } from "@/services/api";
import { validateGeoEvents } from "../domain/validation";
import type { GeoEvent } from "../domain/types";
import type { WorldEventSourceStatus } from "./sourceStatus";

const feeds = [
  {
    key: "faa",
    layer: "airport-disruptions",
    label: "FAA NAS",
    interval: 120000,
  },
  { key: "ais", layer: "ais-vessels", label: "AIS sample", interval: 900000 },
  {
    key: "gpsjam",
    layer: "gnss-interference",
    label: "GPSJAM daily",
    interval: 3600000,
  },
  {
    key: "ioda",
    layer: "internet-outages",
    label: "IODA signals",
    interval: 300000,
  },
] as const;
type RecordState = {
  hasSnapshot?: boolean;
  events: GeoEvent[];
  source: WorldEventSourceStatus;
};
function useSource(feed: (typeof feeds)[number], enabled: boolean) {
  const [record, setRecord] = useState<RecordState | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let disposed = false,
      timer: ReturnType<typeof setTimeout> | undefined,
      controller: AbortController | null = null,
      failures = 0;
    const publish = (
      events: GeoEvent[],
      status: WorldEventSourceStatus["status"],
      message?: string,
      generatedAt?: string,
    ) => {
      if (!disposed)
        setRecord({
          hasSnapshot: true,
          events,
          source: {
            key: feed.key,
            label: feed.label,
            status,
            eventCount: events.length,
            rejectedCount: 0,
            message,
            generatedAt,
            phase:
              status === "error"
                ? "unavailable"
                : status === "degraded"
                  ? "stale"
                  : status === "loading"
                    ? "loading"
                    : status === "partial"
                      ? "partial"
                      : events.length
                        ? "fresh"
                        : "empty",
          },
        });
    };
    const stop = () => {
      clearTimeout(timer);
      controller?.abort();
      controller = null;
    };
    const refresh = async () => {
      if (
        disposed ||
        document.hidden ||
        navigator.onLine === false ||
        controller
      )
        return;
      const request = new AbortController();
      controller = request;
      try {
        const result = await (feed.key === "faa" || feed.key === "ais"
          ? fetchTransportMapSource(feed.key, request.signal)
          : fetchMapSignalSource(feed.key, request.signal));
        if (disposed || request.signal.aborted || controller !== request)
          return;
        if (["unavailable", "error"].includes(result.status))
          throw new Error(result.message || "Source unavailable");
        const parsed = validateGeoEvents(result.events);
        publish(
          parsed.events,
          result.status === "degraded"
            ? "degraded"
            : parsed.rejected.length || result.status === "partial"
              ? "partial"
              : "ok",
          [
            result.message,
            parsed.rejected.length
              ? `${parsed.rejected.length} invalid records rejected`
              : "",
          ]
            .filter(Boolean)
            .join(" · "),
          result.updatedAt,
        );
        failures = result.status === "degraded" ? failures + 1 : 0;
      } catch (error) {
        if (!disposed && !request.signal.aborted) {
          failures++;
          setRecord((previous) =>
            previous?.hasSnapshot
              ? {
                  hasSnapshot: true,
                  events: previous.events.map((event) => ({
                    ...event,
                    sources: event.sources.map((source) => ({
                      ...source,
                      freshness: "stale" as const,
                      status: "degraded" as const,
                    })),
                  })),
                  source: {
                    ...previous.source,
                    status: "degraded",
                    phase: "stale",
                    message: String(error),
                  },
                }
              : {
                  events: [],
                  source: {
                    key: feed.key,
                    label: feed.label,
                    eventCount: 0,
                    rejectedCount: 0,
                    status: "error",
                    phase: "unavailable",
                    message: String(error),
                  },
                },
          );
        }
      } finally {
        if (controller === request) {
          controller = null;
          if (!disposed && !document.hidden)
            timer = setTimeout(
              refresh,
              failures
                ? ([5000, 15000, 45000][failures - 1] ?? feed.interval)
                : feed.interval,
            );
        }
      }
    };
    const resume = () => {
      stop();
      if (!document.hidden) void refresh();
    };
    setRecord(
      (previous) =>
        previous ?? {
          events: [],
          source: {
            key: feed.key,
            label: feed.label,
            eventCount: 0,
            rejectedCount: 0,
            status: "loading",
            phase: "loading",
          },
        },
    );
    void refresh();
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    return () => {
      disposed = true;
      stop();
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
    };
  }, [enabled, feed]);
  return record;
}

/** Independent demand lifetimes; disabling FAA never cancels GNSS or AIS. */
export function useMapSignals(layerIds: readonly string[], suspended: boolean) {
  const enabled = (index: number) =>
    !suspended && layerIds.includes(feeds[index]!.layer);
  const faa = useSource(feeds[0], enabled(0)),
    ais = useSource(feeds[1], enabled(1));
  const gps = useSource(feeds[2], enabled(2)),
    ioda = useSource(feeds[3], enabled(3));
  return useMemo(() => {
    const active = [faa, ais, gps, ioda].filter(
      (r, index): r is RecordState =>
        r !== null && layerIds.includes(feeds[index]!.layer),
    );
    return {
      events: active.flatMap((r) => r.events),
      sources: active.map((r) => r.source),
    };
  }, [faa, ais, gps, ioda, layerIds]);
}
