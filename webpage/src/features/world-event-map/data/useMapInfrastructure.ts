import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { fetchMapInfrastructure } from "@/services/api";
import type { RendererViewport } from "../renderer/MapRenderer";
import type { GeoEvent } from "../domain/types";
import type { WorldEventSourceStatus } from "./sourceStatus";
import { validateGeoEvents } from "../domain/validation";
import { aviationQueryBounds } from "./useAviationViewport";

/** Actual renderer bounds, including both date-line halves; never a center box. */
export function useMapInfrastructure(
  enabled: boolean,
  viewport: RendererViewport | null,
) {
  const bounds = aviationQueryBounds(viewport);
  const ready =
    bounds.length > 0 &&
    bounds.every(([w, s, e, n]) => (e - w) * (n - s) <= 25);
  const key = enabled && ready ? JSON.stringify(bounds) : "";
  const [result, setResult] = useState<{
    key: string;
    hasSnapshot?: boolean;
    events: GeoEvent[];
    error?: string;
    updatedAt?: string;
    message?: string;
  } | null>(null);
  const snapshots = useRef<{
    key: string;
    parts: Map<string, { events: GeoEvent[]; updatedAt?: string }>;
  }>({ key: "", parts: new Map() });
  useEffect(() => {
    if (!key) return;
    let disposed = false,
      controller: AbortController | null = null,
      timer: ReturnType<typeof setTimeout> | undefined,
      failures = 0;
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
        if (snapshots.current.key !== key)
          snapshots.current = { key, parts: new Map() };
        const boxes = JSON.parse(key) as number[][];
        const parts = await Promise.allSettled(
          boxes.map((b) => fetchMapInfrastructure(b, request.signal)),
        );
        if (disposed || request.signal.aborted || controller !== request)
          return;
        const errors: string[] = [],
          messages: string[] = [];
        parts.forEach((part, index) => {
          const id = JSON.stringify(boxes[index]);
          const payload = part.status === "fulfilled" ? part.value : null;
          if (
            payload &&
            payload.status !== "unavailable" &&
            payload.status !== "error"
          ) {
            const parsed = validateGeoEvents(payload.events);
            snapshots.current.parts.set(id, {
              events: parsed.events,
              updatedAt: payload.updatedAt,
            });
            if (payload.message) messages.push(payload.message);
            if (parsed.rejected.length)
              messages.push(
                `${parsed.rejected.length} invalid records rejected`,
              );
          } else {
            errors.push(
              payload?.message ||
                (part.status === "rejected"
                  ? String(part.reason)
                  : "Infrastructure source unavailable"),
            );
            const previous = snapshots.current.parts.get(id);
            if (previous)
              snapshots.current.parts.set(id, {
                ...previous,
                events: previous.events.map((event) => ({
                  ...event,
                  sources: event.sources.map((source) => ({
                    ...source,
                    freshness: "stale" as const,
                    status: "degraded" as const,
                  })),
                })),
              });
          }
        });
        const retained = [...snapshots.current.parts.values()];
        setResult({
          key,
          hasSnapshot: retained.length > 0,
          events: [
            ...new Map(
              retained
                .flatMap((part) => part.events)
                .map((event) => [event.id, event]),
            ).values(),
          ],
          updatedAt: retained
            .map((part) => part.updatedAt)
            .filter((date): date is string => Boolean(date))
            .sort()[0],
          message: [...new Set(messages)].join(" · "),
          error: errors.length ? errors.join(" · ") : undefined,
        });
        failures = errors.length ? failures + 1 : 0;
      } catch (error) {
        if (!disposed && !request.signal.aborted) {
          failures++;
          setResult((previous) =>
            previous?.key === key
              ? { ...previous, error: String(error) }
              : { key, events: [], error: String(error) },
          );
        }
      } finally {
        if (controller === request) {
          controller = null;
          if (!disposed && !document.hidden)
            timer = setTimeout(
              refresh,
              failures
                ? ([5000, 15000, 45000][failures - 1] ?? 300000)
                : 3600000,
            );
        }
      }
    };
    const resume = () => {
      clearTimeout(timer);
      controller?.abort();
      controller = null;
      void refresh();
    };
    timer = setTimeout(refresh, 500);
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
    };
  }, [key]);
  return useMemo(() => {
    const current = result?.key === key ? result : null;
    const source: WorldEventSourceStatus = {
      key: "osm-infrastructure",
      label: "OSM infrastructure",
      status: !ready
        ? "partial"
        : current?.error
          ? current.hasSnapshot
            ? "degraded"
            : "error"
          : current
            ? "partial"
            : "loading",
      eventCount: current?.events.length || 0,
      rejectedCount: 0,
      generatedAt: current?.updatedAt,
      message: !ready
        ? "Zoom in for mapped waterways, cables and pipelines; native viewport query limited to 25 square degrees."
        : current?.error || current?.message,
      phase: !ready
        ? "zoom-required"
        : current?.error
          ? current.hasSnapshot
            ? "stale"
            : "unavailable"
          : current
            ? "partial"
            : "loading",
    };
    return {
      events: enabled ? current?.events || [] : [],
      sources: enabled ? [source] : [],
    };
  }, [result, key, ready, enabled]);
}
