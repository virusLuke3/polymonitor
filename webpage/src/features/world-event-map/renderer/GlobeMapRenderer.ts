import Globe from "globe.gl";
import * as THREE from "three";
import type {
  CountryGeometry,
  CountryGeometryIndex,
} from "../domain/countryGeometry";
import { coordinatePositions } from "../domain/countryGeometry";
import type { GeoEvent } from "../domain/types";
import {
  defaultWorldEventMapState,
  type WorldEventMapState,
} from "../state/mapState";
import {
  EventClusterIndex,
  type EventCluster,
  type ScreenBox,
} from "./layerFactories/eventClusters";
import {
  eventColor,
  countryRiskColor,
  isCountryRiskArea,
} from "./layerFactories/shared";
import {
  mapSymbolForEvent,
  mapSymbolPaths,
  type MapSymbolKey,
} from "../config/mapSymbols";
import {
  selectAviationRenderData,
  routeMotionPointsForGroups,
  seededFlightPointsForGroups,
} from "./layerFactories/aviationScene";
import { RendererTooltip } from "./rendererTooltip";
import { worldEventTooltipModel } from "./hoverTooltip";
import {
  globeAltitudeForZoom,
  globeZoomForAltitude,
  globeEventGeometries,
  globePolygonGeometry,
  type GlobeGeometry,
} from "./globeScene";
import {
  splitViewportBounds,
  type MapRenderer,
  type MapRendererCallbacks,
  type MapCountryTarget,
} from "./MapRenderer";

const rgba = (color: number[]) =>
  `rgba(${color.slice(0, 3).join(",")},${(color[3] ?? 255) / 255})`;
type Marker = {
  coordinates: [number, number];
  event?: GeoEvent;
  cluster?: EventCluster;
};
type Area = {
  geometry: CountryGeometry["geometry"];
  event?: GeoEvent;
  country?: CountryGeometry;
  role?: string;
};

/** Globe adapter for the existing map host: no API, second registry or private filters. */
export class GlobeMapRenderer implements MapRenderer {
  private globe: any = null;
  private host: HTMLElement | null = null;
  private callbacks: MapRendererCallbacks | null = null;
  private state = defaultWorldEventMapState();
  private events: GeoEvent[] = [];
  private countries: CountryGeometryIndex | null = null;
  private countryAreas: Area[] = [];
  private eventGeometry = new Map<GeoEvent, GlobeGeometry[]>();
  private index = new EventClusterIndex();
  private tooltip: RendererTooltip | null = null;
  private language: "en" | "zh" = "en";
  private paused = false;
  private reduced = false;
  private destroyed = false;
  private ready = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private contextTimer: ReturnType<typeof setTimeout> | null = null;
  private animationTimer: ReturnType<typeof setTimeout> | null = null;
  private animationTime = 0;
  private lastTick = 0;
  private revision = 0;
  private viewportKey = "";
  private presentationKey = "";
  private geometryDirty = true;
  private cameraWrite = false;
  private cleanups: Array<() => void> = [];
  private materials = new Map<string, any>();
  private markers: Marker[] = [];
  private markerObjects = new Map<string, any>();
  private motion = new THREE.Group();
  private raycaster = new THREE.Raycaster();
  private earthSphere = new THREE.Sphere(new THREE.Vector3(), 100);
  private rayPoint = new THREE.Vector3();
  private aviation = selectAviationRenderData([], this.state);
  private motionObjects = new Map<string, any>();
  private quality = "auto";
  private fontRevision = 0;

  async mount(host: HTMLElement, callbacks: MapRendererCallbacks) {
    this.host = host;
    this.callbacks = callbacks;
    host.classList.add("wm-globe-renderer");
    this.tooltip = new RendererTooltip(host);
    const globe = (this.globe = new Globe(host, {
      animateIn: false,
      rendererConfig: { antialias: true, powerPreference: "high-performance" },
    }));
    this.quality = (() => {
      try {
        return localStorage.getItem("polydata-globe-quality-v1") || "auto";
      } catch {
        return "auto";
      }
    })();
    globe
      .backgroundColor("#101619")
      .showAtmosphere(true)
      .atmosphereColor("#859fa8")
      .atmosphereAltitude(0.1)
      .onGlobeReady(() => {
        if (this.destroyed) return;
        this.ready = true;
        this.flush();
        this.draw();
        if (
          !performance.getEntriesByName("polymonitor:map:first-basemap").length
        )
          performance.mark("polymonitor:map:first-basemap");
        callbacks.onBasemapStateChange("primary-ready");
      })
      .globeImageUrl("/textures/earth-topo-bathy.jpg")
      .polygonsTransitionDuration(0)
      .polygonGeoJsonGeometry((d: Area) => d.geometry)
      .polygonAltitude((d: Area) => (d.event ? 0.003 : 0.001))
      .polygonCapColor((d: Area) =>
        d.event
          ? rgba(
              isCountryRiskArea(d.event)
                ? countryRiskColor(d.event, 32)
                : [...eventColor(d.event).slice(0, 3), 45],
            )
          : "",
      )
      .polygonSideColor(() => "")
      .polygonStrokeColor((d: Area) =>
        d.event
          ? rgba(
              isCountryRiskArea(d.event)
                ? countryRiskColor(d.event, 100)
                : [...eventColor(d.event).slice(0, 3), 140],
            )
          : "#626970",
      )
      .onPolygonClick((d: Area) =>
        d.event
          ? callbacks.onEventSelect(d.event.id)
          : this.selectCountry(d.country),
      )
      .onPolygonHover((d: Area | null) => this.hover(d?.event || null))
      .pathTransitionDuration(0)
      .pathPoints((d: GlobeGeometry) => d.geometry.coordinates)
      .pathPointLat((p: number[]) => p[1])
      .pathPointLng((p: number[]) => p[0])
      .pathPointAlt(0.005)
      .pathColor((d: GlobeGeometry) =>
        rgba(
          d.event.properties.mapEntity === "air-route"
            ? [50, 154, 167, 105]
            : eventColor(d.event),
        ),
      )
      .pathStroke(null)
      .pathDashLength((d: GlobeGeometry) =>
        d.role.toLowerCase().includes("forecast") ? 0.035 : 1,
      )
      .pathDashGap((d: GlobeGeometry) =>
        d.role.toLowerCase().includes("forecast") ? 0.018 : 0,
      )
      .pathDashAnimateTime(0)
      .onPathClick((d: GlobeGeometry) => callbacks.onEventSelect(d.event.id))
      .onPathHover((d: GlobeGeometry | null) => this.hover(d?.event || null))
      .customThreeObject((d: Marker) => this.marker(d))
      .customThreeObjectUpdate((object: any, d: Marker) =>
        this.place(object, d.coordinates),
      )
      .onCustomLayerClick((d: Marker) => {
        if (d.cluster) {
          callbacks.onClusterSelect?.(this.index.selection(d.cluster));
          this.move(
            d.coordinates,
            Math.max(this.state.zoom + 1, d.cluster.expansionZoom),
          );
        } else if (d.event) callbacks.onEventSelect(d.event.id);
      })
      .onCustomLayerHover((d: Marker | null) =>
        this.hover(d?.cluster || d?.event || null),
      );
    const controls = globe.controls();
    controls.autoRotate = false;
    controls.enableDamping = false;
    controls.enablePan = false;
    controls.minDistance = 101.2;
    controls.maxDistance = 600;
    globe.scene().add(this.motion);
    const cameraChanged = () => {
      if (this.destroyed || this.cameraWrite) return;
      const pov = globe.pointOfView();
      const camera = {
        center: {
          lon: ((((pov.lng + 180) % 360) + 360) % 360) - 180,
          lat: pov.lat,
        },
        zoom: globeZoomForAltitude(pov.altitude),
      };
      if (
        Math.abs(this.state.center.lon - camera.center.lon) < 1e-5 &&
        Math.abs(this.state.center.lat - camera.center.lat) < 1e-5 &&
        Math.abs(this.state.zoom - camera.zoom) < 1e-5
      )
        return;
      this.geometryDirty ||=
        Math.floor(this.state.zoom) !== Math.floor(camera.zoom);
      this.state = { ...this.state, ...camera };
      callbacks.onCameraChange(camera);
      this.queue();
      this.wake();
    };
    controls.addEventListener("change", cameraChanged);
    this.cleanups.push(() =>
      controls.removeEventListener("change", cameraChanged),
    );
    const canvas = globe.renderer().domElement as HTMLCanvasElement;
    const lost = (e: Event) => {
      e.preventDefault();
      this.pause();
      callbacks.onError(
        new Error("3D graphics context lost; attempting bounded recovery."),
      );
      if (this.contextTimer) clearTimeout(this.contextTimer);
      this.contextTimer = setTimeout(
        () =>
          callbacks.onRendererFallbackRequested(
            new Error("3D context recovery timed out."),
          ),
        2000,
      );
    };
    const restored = () => {
      if (this.contextTimer) clearTimeout(this.contextTimer);
      this.contextTimer = null;
      this.geometryDirty = true;
      this.resume();
      callbacks.onBasemapStateChange("primary-ready");
    };
    canvas.addEventListener("webglcontextlost", lost);
    canvas.addEventListener("webglcontextrestored", restored);
    this.cleanups.push(() => {
      canvas.removeEventListener("webglcontextlost", lost);
      canvas.removeEventListener("webglcontextrestored", restored);
    });
    const pointer = (e: MouseEvent) => {
      const box = host.getBoundingClientRect();
      this.pointer = { x: e.clientX - box.left, y: e.clientY - box.top };
      this.wake();
    };
    host.addEventListener("pointermove", pointer);
    this.cleanups.push(() => host.removeEventListener("pointermove", pointer));
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("button,input,select,textarea"))
        return;
      const delta = 5 / Math.max(1, this.state.zoom);
      if (
        [
          "ArrowLeft",
          "ArrowRight",
          "ArrowUp",
          "ArrowDown",
          "+",
          "-",
          "Home",
        ].includes(e.key)
      ) {
        e.preventDefault();
        if (e.key === "Home") this.move([0, 20], 1.5);
        else if (e.key === "+" || e.key === "-")
          this.move(
            [this.state.center.lon, this.state.center.lat],
            this.state.zoom + (e.key === "+" ? 0.5 : -0.5),
          );
        else
          this.move(
            [
              this.state.center.lon +
                (e.key === "ArrowLeft"
                  ? -delta
                  : e.key === "ArrowRight"
                    ? delta
                    : 0),
              this.state.center.lat +
                (e.key === "ArrowUp"
                  ? delta
                  : e.key === "ArrowDown"
                    ? -delta
                    : 0),
            ],
            this.state.zoom,
          );
      }
    };
    const keyboardHost = host.parentElement || host;
    keyboardHost.addEventListener("keydown", key);
    this.cleanups.push(() => keyboardHost.removeEventListener("keydown", key));
    const fontsReady = () => {
      this.fontRevision++;
      this.markers = [];
      this.queue();
    };
    document.fonts.addEventListener("loadingdone", fontsReady);
    this.cleanups.push(() =>
      document.fonts.removeEventListener("loadingdone", fontsReady),
    );
    this.addControls();
    this.resize();
    this.applyCamera();
    this.flush();
  }
  private pointer = { x: 0, y: 0 };
  private hover(value: GeoEvent | EventCluster | null) {
    this.tooltip?.show(
      worldEventTooltipModel(value, "", this.language),
      value ? this.pointer : null,
    );
  }
  private selectCountry(country: CountryGeometry | undefined) {
    if (!country) return;
    const bounds: [[number, number], [number, number]] = [
      [180, 90],
      [-180, -90],
    ];
    for (const [lon, lat] of coordinatePositions(
      country.geometry.coordinates,
    )) {
      bounds[0][0] = Math.min(bounds[0][0], lon!);
      bounds[0][1] = Math.min(bounds[0][1], lat!);
      bounds[1][0] = Math.max(bounds[1][0], lon!);
      bounds[1][1] = Math.max(bounds[1][1], lat!);
    }
    this.callbacks?.onCountrySelect(
      { iso2: country.iso2, name: country.name, bounds },
      this.pointer,
    );
  }
  private addControls() {
    const quality = document.createElement("select");
    quality.setAttribute(
      "aria-label",
      this.language === "zh" ? "地球画质" : "Globe render quality",
    );
    for (const [value, en, zh] of [
      ["auto", "Auto", "自动"],
      ["high", "High", "高"],
      ["balanced", "Balanced", "均衡"],
      ["performance", "Performance", "性能"],
      ["battery", "Battery", "节能"],
    ]) {
      const option = document.createElement("option");
      option.value = value!;
      option.textContent = (this.language === "zh" ? zh : en)!;
      quality.append(option);
    }
    quality.value = this.quality;
    quality.onchange = () => {
      this.quality = quality.value;
      try {
        localStorage.setItem("polydata-globe-quality-v1", this.quality);
      } catch {}
      this.resize();
    };
    quality.className = "wm-globe-quality-select";
    this.host?.append(quality);
    this.cleanups.push(() => quality.remove());
  }
  private sprite(symbol: MapSymbolKey, color: string, count = 0) {
    const key = `${symbol}:${color}:${count}:${count ? this.fontRevision : 0}`;
    if (!this.materials.has(key)) {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 96;
      const ctx = canvas.getContext("2d")!;
      ctx.translate(48, 40);
      ctx.strokeStyle = "#101619";
      ctx.lineWidth = 3;
      ctx.fillStyle = color;
      if (count) {
        ctx.beginPath();
        ctx.arc(0, 0, 32, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.translate(-24, -24);
      ctx.scale(2, 2);
      for (const path of mapSymbolPaths(symbol)) {
        const shape = new Path2D(path);
        ctx.stroke(shape);
        ctx.fill(shape);
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (count) {
        ctx.font = `500 24px ${this.host ? getComputedStyle(this.host).fontFamily : "sans-serif"}`;
        ctx.textAlign = "center";
        ctx.lineWidth = 5;
        ctx.strokeStyle = "#101619";
        ctx.strokeText(String(count), 48, 91);
        ctx.fillStyle = "#e4e9eb";
        ctx.fillText(String(count), 48, 91);
      }
      const texture = new THREE.CanvasTexture(canvas);
      this.materials.set(
        key,
        new THREE.SpriteMaterial({
          map: texture,
          depthTest: true,
          depthWrite: false,
          transparent: true,
        }),
      );
    }
    return new THREE.Sprite(this.materials.get(key));
  }
  private marker(d: Marker) {
    const color = rgba(d.cluster?.color || eventColor(d.event!));
    const object = this.sprite(
      d.cluster?.symbol || mapSymbolForEvent(d.event!),
      color,
      d.cluster?.count,
    );
    this.markerObjects.set(d.cluster?.id || d.event!.id, object);
    this.place(object, d.coordinates);
    return object;
  }
  private place(object: any, coordinates: [number, number]) {
    if (!this.globe) return;
    const point = this.globe.getCoords(coordinates[1], coordinates[0], 0.009);
    object.position.set(point.x, point.y, point.z);
    // Sprite size follows actual camera distance so labels don't inflate on zoom.
    const camera = this.globe.camera();
    const distance = camera.position.distanceTo(object.position);
    const scale =
      (distance * 2 * Math.tan((camera.fov * Math.PI) / 360) * 22) /
      Math.max(1, this.host?.clientHeight || 1);
    object.scale.set(scale, scale, 1);
  }
  private move(point: [number, number], zoom: number) {
    this.state = {
      ...this.state,
      center: {
        lon: ((((point[0] + 180) % 360) + 360) % 360) - 180,
        lat: Math.max(-85, Math.min(85, point[1])),
      },
      zoom: Math.max(0, Math.min(8.7, zoom)),
    };
    this.applyCamera();
    this.callbacks?.onCameraChange({
      center: this.state.center,
      zoom: this.state.zoom,
    });
    this.queue();
  }
  private applyCamera() {
    if (!this.globe) return;
    this.cameraWrite = true;
    this.globe.pointOfView(
      {
        lat: this.state.center.lat,
        lng: this.state.center.lon,
        altitude: globeAltitudeForZoom(this.state.zoom),
      },
      0,
    );
    this.cameraWrite = false;
    this.wake();
  }
  private visible(point: [number, number]) {
    const g = this.globe;
    if (!g || !this.host) return false;
    const xyz = g.getCoords(point[1], point[0], 0),
      camera = g.camera().position;
    if (xyz.x * camera.x + xyz.y * camera.y + xyz.z * camera.z < 10000)
      return false;
    const p = g.getScreenCoords(point[1], point[0]);
    return (
      p.x >= 0 &&
      p.y >= 0 &&
      p.x <= this.host.clientWidth &&
      p.y <= this.host.clientHeight
    );
  }
  private publishViewport() {
    if (!this.globe || !this.host) return;
    const { clientWidth: w, clientHeight: h } = this.host;
    const key = [
      w,
      h,
      this.state.center.lon,
      this.state.center.lat,
      this.state.zoom,
    ].join(":");
    if (key === this.viewportKey) return;
    this.viewportKey = key;
    const samples: Array<{ lng: number; lat: number }> = [];
    for (let y = 0; y <= 12; y++)
      for (let x = 0; x <= 20; x++) {
        // Ray/sphere intersection uses the real camera without traversing
        // every event/country mesh for each viewport sample.
        this.raycaster.setFromCamera(
          new THREE.Vector2(x / 10 - 1, 1 - y / 6),
          this.globe.camera(),
        );
        const hit = this.raycaster.ray.intersectSphere(
          this.earthSphere,
          this.rayPoint,
        );
        if (hit) samples.push(this.globe.toGeoCoords(hit));
      }
    const { lon, lat } = this.state.center;
    const offsets = samples.map(
      (p) => ((((p.lng - lon + 180) % 360) + 360) % 360) - 180,
    );
    // Include a sampling-cell buffer. All inputs come from the renderer's ray/sphere intersection.
    const lonStep = offsets.length
      ? Math.max(...offsets) - Math.min(...offsets)
      : 360;
    const south = samples.length ? Math.min(...samples.map((p) => p.lat)) : -85,
      north = samples.length ? Math.max(...samples.map((p) => p.lat)) : 85;
    this.callbacks?.onViewportChange?.({
      revision: ++this.revision,
      center: [lon, lat],
      zoom: this.state.zoom,
      widthCssPx: w,
      heightCssPx: h,
      bounds: splitViewportBounds(
        lon + (offsets.length ? Math.min(...offsets) - lonStep / 20 : -180),
        Math.max(-85, south - (north - south) / 12),
        lon + (offsets.length ? Math.max(...offsets) + lonStep / 20 : 180),
        Math.min(85, north + (north - south) / 12),
      ),
    });
  }
  private flush() {
    if (!this.globe || this.paused || this.destroyed) return;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const selected = this.state.selectedEventId;
    this.aviation = selectAviationRenderData(this.events, this.state);
    if (
      !this.aviation.routeMotionGroups.length &&
      !this.aviation.flightMotionGroups.length
    ) {
      if (this.animationTimer) clearTimeout(this.animationTimer);
      this.animationTimer = null;
      this.motion.clear();
      this.motionObjects.clear();
    }
    const { singles, clusters } = this.index.query(
      this.state.presentationMode === "records" ? 18 : this.state.zoom,
      selected,
    );
    const markers: Marker[] = [
      ...[
        ...new Map(
          [...singles, ...this.aviation.hubs, ...this.aviation.liveAircraft]
            .filter((event) => event.geometry?.type === "Point")
            .map((event) => [event.id, event]),
        ).values(),
      ].map((event) => ({
        coordinates: event.geometry!.coordinates as [number, number],
        event,
      })),
      ...clusters.map((cluster) => ({
        coordinates: cluster.coordinates,
        cluster,
      })),
    ];
    const changed =
      markers.length !== this.markers.length ||
      markers.some(
        (m, i) =>
          m.event !== this.markers[i]?.event ||
          m.cluster !== this.markers[i]?.cluster,
      );
    if (changed) {
      this.markers = markers;
      this.markerObjects.clear();
      this.globe.customLayerData(markers);
    } else
      for (const marker of this.markers) {
        const object = this.markerObjects.get(
          marker.cluster?.id || marker.event!.id,
        );
        if (object) this.place(object, marker.coordinates);
      }
    if (this.geometryDirty) {
      const routeIds = new Set(
        [...this.aviation.routes, ...this.aviation.flights].map((e) => e.id),
      );
      const active = this.events.filter(
        (e) =>
          !["air-route", "air-flight"].includes(
            String(e.properties.mapEntity),
          ) || routeIds.has(e.id),
      );
      const cache = new Map<GeoEvent, GlobeGeometry[]>();
      const geometry = active.flatMap((event) => {
        const value =
          this.eventGeometry.get(event) || globeEventGeometries([event]);
        cache.set(event, value);
        return value;
      });
      this.eventGeometry = cache;
      this.globe.pathsData(
        geometry.filter((g) => g.geometry.type === "LineString"),
      );
      this.globe.polygonsData([
        ...this.countryAreas,
        ...geometry.filter(
          (g) =>
            g.geometry.type === "Polygon" || g.geometry.type === "MultiPolygon",
        ),
      ]);
      this.geometryDirty = false;
    }
    const inView = this.events.filter((e) =>
      coordinatePositions(e.geometry?.coordinates).some(
        (p, i, all) =>
          i % Math.max(1, Math.floor(all.length / 16)) === 0 &&
          this.visible([p[0]!, p[1]!]),
      ),
    );
    const presentation = {
      inView: inView.length,
      inViewIds: inView.map((e) => e.id),
      singles: markers.filter((m) => m.event && this.visible(m.coordinates))
        .length,
      clusters: markers.filter((m) => m.cluster && this.visible(m.coordinates))
        .length,
      observations: 0,
    };
    const key = JSON.stringify(presentation);
    if (key !== this.presentationKey) {
      this.presentationKey = key;
      this.callbacks?.onPresentationChange?.(presentation);
    }
    this.host!.dataset.globeFlushes = String(
      Number(this.host!.dataset.globeFlushes || 0) + 1,
    );
    this.host!.dataset.globeRecords = String(this.events.length);
    this.host!.dataset.globeMarkers = String(markers.length);
    this.host!.dataset.globeAircraft = String(
      markers.filter(
        (marker) => marker.event?.properties.mapEntity === "live-aircraft",
      ).length,
    );
    this.publishViewport();
    this.draw();
    this.wake();
    this.startMotion();
  }
  private queue() {
    if (this.paused || this.destroyed || this.timer) return;
    this.timer = setTimeout(() => this.flush(), 100);
  }
  private startMotion() {
    if (
      this.animationTimer ||
      this.paused ||
      this.reduced ||
      this.destroyed ||
      (!this.aviation.routeMotionGroups.length &&
        !this.aviation.flightMotionGroups.length)
    )
      return;
    this.lastTick = performance.now();
    const tick = () => {
      this.animationTimer = null;
      if (this.paused || this.reduced || this.destroyed) return;
      const now = performance.now();
      this.animationTime += Math.min(80, now - this.lastTick) / 1000;
      this.lastTick = now;
      const points = [
        ...routeMotionPointsForGroups(
          this.aviation.routeMotionGroups,
          this.animationTime,
          this.state.selectedEventId,
        ),
        ...seededFlightPointsForGroups(
          this.aviation.flightMotionGroups,
          this.animationTime,
          this.state.zoom,
          this.state.selectedEventId,
        ),
      ];
      const used = new Set<string>();
      for (const point of points) {
        used.add(point.id);
        let sprite = this.motionObjects.get(point.id);
        if (!sprite) {
          sprite = this.sprite("aircraft", rgba(point.color));
          this.motionObjects.set(point.id, sprite);
          this.motion.add(sprite);
        }
        this.place(sprite, point.position);
      }
      for (const [id, sprite] of this.motionObjects)
        if (!used.has(id)) {
          this.motion.remove(sprite);
          this.motionObjects.delete(id);
        }
      this.draw();
      if (
        this.aviation.routeMotionGroups.length ||
        this.aviation.flightMotionGroups.length
      )
        this.animationTimer = setTimeout(
          tick,
          this.quality === "battery" ? 80 : 40,
        );
    };
    this.animationTimer = setTimeout(
      tick,
      this.quality === "battery" ? 80 : 40,
    );
  }
  private draw() {
    if (!this.globe || this.paused || this.destroyed) return;
    this.globe.renderer().render(this.globe.scene(), this.globe.camera());
  }
  private wake() {
    if (!this.globe || this.paused || this.destroyed) return;
    this.globe.resumeAnimation();
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      this.globe?.pauseAnimation();
      const live = new Set(
        [...this.markerObjects.values(), ...this.motionObjects.values()].map(
          (object) => object.material,
        ),
      );
      for (const [key, material] of this.materials)
        if (!live.has(material)) {
          material.map?.dispose();
          material.dispose();
          this.materials.delete(key);
        }
      this.idleTimer = null;
      this.host?.classList.add("is-render-idle");
    }, 180);
    this.host?.classList.remove("is-render-idle");
  }
  setState(state: WorldEventMapState) {
    if (state === this.state) return;
    const moved =
      this.state.center.lon !== state.center.lon ||
      this.state.center.lat !== state.center.lat ||
      this.state.zoom !== state.zoom;
    this.geometryDirty ||=
      this.state.zoom !== state.zoom ||
      this.state.aviationLens !== state.aviationLens ||
      this.state.aviationRiskSource !== state.aviationRiskSource ||
      this.state.selectedEventId !== state.selectedEventId;
    this.state = state;
    if (moved) this.applyCamera();
    this.queue();
  }
  setEvents(events: GeoEvent[]) {
    if (events === this.events) return;
    this.events = events;
    this.index.update(events);
    this.geometryDirty = true;
    this.queue();
  }
  setCountries(index: CountryGeometryIndex | null) {
    if (this.countries === index) return;
    this.countries = index;
    this.countryAreas = (index?.countries || []).map((country) => ({
      country,
      geometry: globePolygonGeometry(country.geometry),
    }));
    this.geometryDirty = true;
    this.queue();
  }
  setLanguage(language: "en" | "zh") {
    this.language = language;
    const select = this.host?.querySelector<HTMLSelectElement>(
      ".wm-globe-quality-select",
    );
    if (select) {
      select.setAttribute(
        "aria-label",
        language === "zh" ? "地球画质" : "Globe render quality",
      );
      const labels =
        language === "zh"
          ? ["自动", "高", "均衡", "性能", "节能"]
          : ["Auto", "High", "Balanced", "Performance", "Battery"];
      Array.from(select.options).forEach((option, index) => {
        option.textContent = labels[index] || option.value;
      });
    }
  }
  setOcclusions(boxes: ScreenBox[]) {
    this.tooltip?.setOcclusions(boxes);
  }
  setHoveredEvent(id: string | null) {
    this.hover(this.events.find((e) => e.id === id) || null);
  }
  setReducedMotion(reduced: boolean) {
    this.reduced = reduced;
    if (reduced) {
      if (this.animationTimer) clearTimeout(this.animationTimer);
      this.animationTimer = null;
      this.motion.visible = false;
    } else {
      this.motion.visible = true;
      this.startMotion();
    }
  }
  fitCountry(country: MapCountryTarget) {
    const [a, b] = country.bounds;
    this.move(
      [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2],
      Math.max(2, Math.log2(240 / Math.max(1, b[0] - a[0], b[1] - a[1]))),
    );
  }
  resize() {
    if (!this.globe || !this.host) return;
    this.globe.width(this.host.clientWidth).height(this.host.clientHeight);
    this.globe
      .renderer()
      .setPixelRatio(
        Math.min(
          this.quality === "battery" || this.quality === "performance"
            ? 1
            : this.quality === "balanced"
              ? 1.5
              : 2,
          window.devicePixelRatio || 1,
        ),
      );
    this.queue();
    this.wake();
  }
  pause() {
    this.paused = true;
    for (const timer of [this.timer, this.idleTimer, this.animationTimer])
      if (timer) clearTimeout(timer);
    this.timer = this.idleTimer = this.animationTimer = null;
    this.globe?.pauseAnimation();
    this.tooltip?.clear();
    this.host?.setAttribute("data-render-paused", "true");
  }
  resume() {
    this.paused = false;
    this.host?.setAttribute("data-render-paused", "false");
    this.flush();
    this.wake();
  }
  async verifyReady() {
    return (
      this.ready &&
      !this.destroyed &&
      Boolean(this.globe?.renderer().info.render.calls)
    );
  }
  destroy() {
    this.destroyed = true;
    this.pause();
    if (this.contextTimer) clearTimeout(this.contextTimer);
    this.cleanups.forEach((fn) => fn());
    this.cleanups = [];
    this.tooltip?.destroy();
    this.globe?.scene().remove(this.motion);
    this.globe?._destructor();
    this.globe = null;
    for (const material of this.materials.values()) {
      material.map?.dispose();
      material.dispose();
    }
    this.materials.clear();
    this.markerObjects.clear();
    this.motionObjects.clear();
    this.eventGeometry.clear();
    this.host?.remove();
    this.host = null;
  }
}
