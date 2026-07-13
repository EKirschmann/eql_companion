"use client";

import { FormEvent, memo, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import { Atlas3D } from "@/components/Atlas3D";
import type { GeometryFloor, MapData, Position, ZoneGeometry } from "@/lib/types";

interface OcrStatus {
  deps_ok: boolean;
  enabled: boolean;
  game_running: boolean;
  last_ok: string | null;
  error: string | null;
}

/* The Atlas renders the game's own vector map files as gold ink on dark
   vellum. Map files store coords so a /loc position plots at (-x, -y),
   screen-y down. Pan with drag, zoom with the wheel. The chart follows the
   hero at the current zoom until you drag it away; Recenter locks back on
   (or refits the whole chart when no position is known). */

interface ViewRef {
  scale: number;
  fitScale: number;
  panX: number;
  panY: number;
  cx: number; // world-space center of the fitted view
  cy: number;
}

const INK = { r: 203, g: 182, b: 138 }; // bone-gold ink for dark strokes

function inkColor(r: number, g: number, b: number): string {
  // Blend the file's color toward the ink tone so the chart reads as one
  // hand — dark walls become gold ink, colored annotations stay hinted.
  const mix = 0.68;
  const mr = Math.round(r + (INK.r - r) * mix);
  const mg = Math.round(g + (INK.g - g) * mix);
  const mb = Math.round(b + (INK.b - b) * mix);
  return `rgba(${mr},${mg},${mb},0.55)`;
}

/* Rendering is layered so the per-frame cost (position glide runs at 60fps)
   is two blits + one marker, not thousands of strokes:
   - vellum layer: ground + speckle, screen-fixed, re-rendered on resize only
   - map layer: strokes + labels, world-fixed, rendered with a BASE_MARGIN
     apron and re-rendered only on zoom/resize/zone change or when the camera
     drifts past the apron. */
const BASE_MARGIN = 300; // px apron around the viewport on the cached map layer

function renderVellum(
  w: number,
  h: number,
  dpr: number,
  noise: [number, number, number][],
): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w * dpr;
  c.height = h * dpr;
  const ctx = c.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#16130f";
  ctx.fillRect(0, 0, w, h);
  const vg = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.2, w / 2, h / 2, Math.max(w, h) * 0.75);
  vg.addColorStop(0, "rgba(0,0,0,0)");
  vg.addColorStop(1, "rgba(0,0,0,0.45)");
  ctx.fillStyle = vg;
  ctx.fillRect(0, 0, w, h);
  for (const [nx, ny, na] of noise) {
    ctx.fillStyle = `rgba(210,190,150,${na})`;
    ctx.fillRect(nx * w, ny * h, 1, 1);
  }
  return c;
}

function renderMapLayer(
  m: MapData | null,
  geo: GeometryFloor[] | null,
  activeFloor: number,
  scale: number,
  camX: number,
  camY: number,
  w: number,
  h: number,
  dpr: number,
): HTMLCanvasElement {
  const bw = w + BASE_MARGIN * 2;
  const bh = h + BASE_MARGIN * 2;
  const c = document.createElement("canvas");
  c.width = bw * dpr;
  c.height = bh * dpr;
  const ctx = c.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const toX = (x: number) => (x - camX) * scale + bw / 2;
  const toY = (y: number) => (y - camY) * scale + bh / 2;

  if (geo) {
    // Client-mined geometry: floor slabs first (lower bands under upper),
    // then walls. Inactive floors are ghosted so the selected one reads.
    geo.forEach((f, i) => {
      const active = activeFloor === -1 || i === activeFloor;
      ctx.fillStyle = active ? "rgba(200,170,110,0.10)" : "rgba(200,170,110,0.035)";
      ctx.beginPath();
      for (const t of f.tris) {
        const x1 = toX(t[0]), y1 = toY(t[1]);
        const x2 = toX(t[2]), y2 = toY(t[3]);
        const x3 = toX(t[4]), y3 = toY(t[5]);
        if ((x1 < -50 && x2 < -50 && x3 < -50) || (y1 < -50 && y2 < -50 && y3 < -50) ||
            (x1 > bw + 50 && x2 > bw + 50 && x3 > bw + 50) ||
            (y1 > bh + 50 && y2 > bh + 50 && y3 > bh + 50)) {
          continue;
        }
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x3, y3);
        ctx.closePath();
      }
      ctx.fill();
    });
    ctx.lineWidth = 1;
    ctx.lineCap = "round";
    geo.forEach((f, i) => {
      const active = activeFloor === -1 || i === activeFloor;
      ctx.strokeStyle = active ? "rgba(203,182,138,0.65)" : "rgba(203,182,138,0.10)";
      ctx.beginPath();
      for (const s of f.walls) {
        const x1 = toX(s[0]), y1 = toY(s[1]);
        const x2 = toX(s[2]), y2 = toY(s[3]);
        if ((x1 < -50 && x2 < -50) || (y1 < -50 && y2 < -50) ||
            (x1 > bw + 50 && x2 > bw + 50) || (y1 > bh + 50 && y2 > bh + 50)) {
          continue;
        }
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
      }
      ctx.stroke();
    });
  }

  // chart strokes (skipped in geometry mode; labels render in both modes)
  ctx.lineWidth = 1;
  ctx.lineCap = "round";
  let lastColor = "";
  for (const [x1, y1, x2, y2, r, g, b] of (geo ? [] : m?.lines ?? [])) {
    const sx1 = toX(x1);
    const sy1 = toY(y1);
    const sx2 = toX(x2);
    const sy2 = toY(y2);
    if (
      (sx1 < -50 && sx2 < -50) || (sy1 < -50 && sy2 < -50) ||
      (sx1 > bw + 50 && sx2 > bw + 50) || (sy1 > bh + 50 && sy2 > bh + 50)
    ) {
      continue;
    }
    const color = inkColor(r, g, b);
    if (color !== lastColor) {
      ctx.strokeStyle = color;
      lastColor = color;
    }
    ctx.beginPath();
    ctx.moveTo(sx1, sy1);
    ctx.lineTo(sx2, sy2);
    ctx.stroke();
  }

  // labels
  const displayFont =
    getComputedStyle(document.documentElement).getPropertyValue("--font-display").trim() || "serif";
  for (const p of m?.points ?? []) {
    const sx = toX(p.x);
    const sy = toY(p.y);
    if (sx < -60 || sy < -20 || sx > bw + 60 || sy > bh + 20) continue;
    if (p.exit) {
      // exits: gold diamond + bright label — these answer "which way out"
      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = "#c8aa6e";
      ctx.fillRect(-3, -3, 6, 6);
      ctx.restore();
      ctx.font = `600 11px ${displayFont}`;
      ctx.fillStyle = "#e7cd92";
    } else {
      ctx.fillStyle = "rgba(207,195,162,0.8)";
      ctx.beginPath();
      ctx.arc(sx, sy, 1.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = `${9 + Math.min(p.size, 3)}px ${displayFont}`;
      ctx.fillStyle = "rgba(207,195,162,0.75)";
    }
    ctx.fillText(p.label, sx + 6, sy + 3);
  }
  return c;
}

export const AtlasPanel = memo(function AtlasPanel({
  zone,
  position,
}: {
  zone: string | null;
  position: Position | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<ViewRef>({ scale: 1, fitScale: 1, panX: 0, panY: 0, cx: 0, cy: 0 });
  const mapRef = useRef<MapData | null>(null);
  const posRef = useRef<Position | null>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const followRef = useRef(true); // keep the hero centered until the user drags
  const dispRef = useRef<{ x: number; y: number } | null>(null); // eased on-screen position
  const glideRaf = useRef(0);
  const noiseRef = useRef<[number, number, number][]>([]);
  const vellumRef = useRef<HTMLCanvasElement | null>(null);
  const vellumKey = useRef("");
  const baseRef = useRef<HTMLCanvasElement | null>(null);
  const baseKey = useRef("");
  const baseC0 = useRef<[number, number]>([0, 0]);
  const fontsTick = useRef(0);

  const [map, setMap] = useState<MapData | null>(null);
  const [zones, setZones] = useState<string[]>([]);
  const [dest, setDest] = useState("");
  const [route, setRoute] = useState<string[] | null>(null);
  const [routeMsg, setRouteMsg] = useState<string | null>(null);
  const [ocr, setOcr] = useState<OcrStatus | null>(null);
  const [ocrHelp, setOcrHelp] = useState(false);
  const [ocrPreview, setOcrPreview] = useState<string | null>(null);
  const [view, setView] = useState<"chart" | "geo" | "3d">("chart");
  const [floorSel, setFloorSel] = useState<"auto" | "all" | number>("auto");
  const [geom, setGeom] = useState<ZoneGeometry | null>(null);
  const modeRef = useRef<"chart" | "geo" | "3d">("chart");
  const floorSelRef = useRef<"auto" | "all" | number>("auto");
  const geomRef = useRef<ZoneGeometry | null>(null);

  posRef.current = position;

  /* ---------- drawing ---------- */

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    if (w === 0 || h === 0) return;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Layer 1 — vellum ground + speckle (cached per canvas size)
    if (noiseRef.current.length === 0) {
      for (let i = 0; i < 900; i++) {
        noiseRef.current.push([Math.random(), Math.random(), Math.random() * 0.05]);
      }
    }
    const vKey = `${w}|${h}|${dpr}`;
    if (vellumKey.current !== vKey || !vellumRef.current) {
      vellumKey.current = vKey;
      vellumRef.current = renderVellum(w, h, dpr, noiseRef.current);
    }
    ctx.drawImage(vellumRef.current, 0, 0, w, h);

    const m = mapRef.current;
    const g = modeRef.current === "geo" ? geomRef.current : null;
    const gf = g?.available && g.floors?.length ? g.floors : null;
    const hasChart = !!(m?.available && m.lines);
    if (!hasChart && !gf) return;

    // resolve the active floor: explicit index, all, or auto from hero z
    let activeFloor = -1;
    if (gf) {
      const sel = floorSelRef.current;
      if (typeof sel === "number") {
        activeFloor = Math.min(sel, gf.length - 1);
      } else if (sel === "auto") {
        const z = posRef.current?.z;
        if (z != null) {
          let best = 0;
          gf.forEach((f, i) => {
            if (Math.abs(f.z - z) < Math.abs(gf[best].z - z)) best = i;
          });
          activeFloor = best;
        }
      }
    }

    const v = viewRef.current;
    // camera center in world space (the world point under the viewport center)
    const camX = v.cx - v.panX / v.scale;
    const camY = v.cy - v.panY / v.scale;

    // Layer 2 — cached map strokes + labels, blitted at the camera offset
    const bKey = `${m?.zone}|${m?.lines?.length ?? 0}|${gf ? "geo" : "chart"}|` +
      `${activeFloor}|${gf?.length ?? 0}|${g?.wall_count ?? 0}|` +
      `${v.scale}|${w}|${h}|${dpr}|${fontsTick.current}`;
    const drifted =
      Math.abs(baseC0.current[0] - camX) * v.scale > BASE_MARGIN ||
      Math.abs(baseC0.current[1] - camY) * v.scale > BASE_MARGIN;
    if (baseKey.current !== bKey || drifted || !baseRef.current) {
      baseKey.current = bKey;
      baseC0.current = [camX, camY];
      baseRef.current = renderMapLayer(
        hasChart ? m : null, gf, activeFloor, v.scale, camX, camY, w, h, dpr);
    }
    const dx = (baseC0.current[0] - camX) * v.scale - BASE_MARGIN;
    const dy = (baseC0.current[1] - camY) * v.scale - BASE_MARGIN;
    ctx.drawImage(baseRef.current, dx, dy, w + BASE_MARGIN * 2, h + BASE_MARGIN * 2);

    // Dynamic layer — the hero (plot /loc at (-x, -y)); dispRef trails the
    // true position with a short eased glide
    const pos = dispRef.current ?? posRef.current;
    if (pos) {
      const sx = (-pos.x - camX) * v.scale + w / 2;
      const sy = (-pos.y - camY) * v.scale + h / 2;
      ctx.strokeStyle = "rgba(31,179,140,0.55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(sx, sy, 10, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "#1fb38c";
      ctx.strokeStyle = "#0b0d10";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(sx, sy, 4.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
  }, []);

  const fitToBounds = useCallback(() => {
    const m = mapRef.current;
    const wrap = wrapRef.current;
    const gb = geomRef.current?.available ? geomRef.current.bounds : null;
    const b = (m?.available && m.bounds) || gb;
    if (!b || !wrap) return;
    const spanX = Math.max(b.max_x - b.min_x, 1);
    const spanY = Math.max(b.max_y - b.min_y, 1);
    const scale = Math.min(wrap.clientWidth / spanX, wrap.clientHeight / spanY) * 0.92;
    viewRef.current = {
      scale,
      fitScale: scale,
      panX: 0,
      panY: 0,
      cx: (b.min_x + b.max_x) / 2,
      cy: (b.min_y + b.max_y) / 2,
    };
    draw();
  }, [draw]);

  // Pin the hero to the center of the chart without touching the zoom.
  const centerOnPlayer = useCallback(() => {
    const pos = dispRef.current ?? posRef.current;
    if (!pos) return false;
    const v = viewRef.current;
    v.panX = (v.cx + pos.x) * v.scale;
    v.panY = (v.cy + pos.y) * v.scale;
    return true;
  }, []);

  /* ---------- data ---------- */

  useEffect(() => {
    apiGet<{ zones: string[] }>("/api/zones").then((r) => setZones(r.zones)).catch(() => {});
  }, []);

  // OCR status poll (light — every 4s while the Atlas is mounted)
  useEffect(() => {
    let alive = true;
    const tick = () =>
      apiGet<OcrStatus>("/api/ocr/status")
        .then((s) => alive && setOcr(s))
        .catch(() => alive && setOcr(null));
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const toggleOcr = async () => {
    if (!ocr) return;
    try {
      const s = await apiSend<OcrStatus>("/api/ocr/enabled", { enabled: !ocr.enabled });
      setOcr(s);
    } catch {
      /* backend offline */
    }
  };

  const calibrate = async () => {
    try {
      await apiSend("/api/ocr/overlay", {});
    } catch {
      /* backend offline */
    }
  };

  const testRead = async () => {
    setOcrPreview("reading…");
    try {
      const r = await apiGet<{ text: string | null; parsed: { x: number; y: number; z: number } | null; error?: string }>(
        "/api/ocr/preview",
      );
      if (r.parsed) {
        setOcrPreview(`✓ read X:${r.parsed.x} Y:${r.parsed.y} Z:${r.parsed.z}`);
      } else if (r.text) {
        setOcrPreview(
          `box sees "${r.text.slice(0, 60)}" — not an X/Y/Z readout` +
            (ocr?.enabled && ocr?.last_ok
              ? " this frame (live tracking is working; single frames sometimes misread)"
              : "; move or resize the box"),
        );
      } else {
        setOcrPreview(r.error ? `capture failed: ${r.error}` : "box sees nothing — is the game visible?");
      }
    } catch {
      setOcrPreview("backend offline");
    }
  };

  useEffect(() => {
    if (!zone) return;
    let cancelled = false;
    apiGet<MapData>(`/api/map?zone=${encodeURIComponent(zone)}`)
      .then((data) => {
        if (cancelled) return;
        setMap(data);
        mapRef.current = data;
        fitToBounds();
      })
      .catch(() => {
        if (!cancelled) setMap({ available: false, zone, reason: "Backend unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, [zone, fitToBounds]);

  // redraw when the chart itself changes
  useEffect(() => {
    if (followRef.current) centerOnPlayer();
    draw();
  }, [map, draw, centerOnPlayer]);

  // mirror view state into refs for the draw closure; refit when geometry
  // arrives for a chartless zone
  useEffect(() => {
    modeRef.current = view;
    floorSelRef.current = floorSel;
    geomRef.current = geom;
    if (geom?.available && !mapRef.current?.available) {
      fitToBounds();
    } else {
      draw();
    }
  }, [view, floorSel, geom, draw, fitToBounds]);

  // fetch client-mined geometry when the view needs it (cached server-side)
  useEffect(() => {
    if (view !== "geo" || !zone) return;
    let cancelled = false;
    setGeom(null);
    apiGet<ZoneGeometry>(`/api/geometry?zone=${encodeURIComponent(zone)}`)
      .then((g) => {
        if (!cancelled) setGeom(g);
      })
      .catch(() => {
        if (!cancelled) setGeom({ available: false, zone, reason: "Backend unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, [view, zone]);

  // glide the marker (and the follow camera) toward each new position;
  // snap on the first fix, reduced motion, or a gate-sized jump
  useEffect(() => {
    cancelAnimationFrame(glideRaf.current);
    if (!position) {
      dispRef.current = null;
      draw();
      return;
    }
    const from = dispRef.current;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const jump = from ? Math.hypot(position.x - from.x, position.y - from.y) : Infinity;
    if (!from || reduced || jump > 2000 || jump < 0.5) {
      dispRef.current = { x: position.x, y: position.y };
      if (followRef.current) centerOnPlayer();
      draw();
      return;
    }
    const start = performance.now();
    const DURATION = 700; // ms - just under the ~1s OCR cadence
    const fx = from.x;
    const fy = from.y;
    const step = (now: number) => {
      const t = Math.min((now - start) / DURATION, 1);
      const e = 1 - Math.pow(1 - t, 3); // ease-out cubic
      dispRef.current = { x: fx + (position.x - fx) * e, y: fy + (position.y - fy) * e };
      if (followRef.current) centerOnPlayer();
      draw();
      if (t < 1) glideRaf.current = requestAnimationFrame(step);
    };
    glideRaf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(glideRaf.current);
  }, [position, draw, centerOnPlayer]);

  useEffect(() => {
    document.fonts?.ready.then(() => {
      fontsTick.current++; // labels were rendered with a fallback font
      draw();
    });
    const wrap = wrapRef.current;
    if (!wrap) return;
    const ro = new ResizeObserver(() => {
      if (followRef.current && posRef.current) {
        centerOnPlayer();
        draw();
      } else {
        fitToBounds();
      }
    });
    ro.observe(wrap);
    return () => ro.disconnect();
    // re-run when the canvas remounts after leaving the 3D view
  }, [draw, fitToBounds, centerOnPlayer, view]);

  /* ---------- interactions ---------- */

  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = { x: e.clientX, y: e.clientY };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    followRef.current = false; // manual pan releases the follow lock
    viewRef.current.panX += e.clientX - dragRef.current.x;
    viewRef.current.panY += e.clientY - dragRef.current.y;
    dragRef.current = { x: e.clientX, y: e.clientY };
    draw();
  };
  const onPointerUp = () => {
    dragRef.current = null;
  };
  const onWheel = (e: React.WheelEvent) => {
    const v = viewRef.current;
    const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
    const next = Math.min(Math.max(v.scale * factor, v.fitScale * 0.4), v.fitScale * 30);
    // zoom about the cursor
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const mx = e.clientX - rect.left - rect.width / 2 - v.panX;
    const my = e.clientY - rect.top - rect.height / 2 - v.panY;
    if (followRef.current && posRef.current) {
      // zoom about the hero so the follow lock holds
      v.scale = next;
      centerOnPlayer();
    } else {
      const ratio = next / v.scale;
      v.panX -= mx * (ratio - 1);
      v.panY -= my * (ratio - 1);
      v.scale = next;
    }
    draw();
  };

  const recenter = () => {
    followRef.current = true;
    if (centerOnPlayer()) draw();
    else fitToBounds(); // no position yet - fall back to the full-chart fit
  };

  /* ---------- routing ---------- */

  const findRoute = async (e: FormEvent) => {
    e.preventDefault();
    if (!dest.trim()) return;
    setRouteMsg(null);
    setRoute(null);
    try {
      const r = await apiGet<{ path: string[] | null; reason?: string }>(
        `/api/route?to=${encodeURIComponent(dest.trim())}`,
      );
      if (r.path) setRoute(r.path);
      else setRouteMsg(r.reason ?? "No route found.");
    } catch {
      setRouteMsg("The backend is unreachable.");
    }
  };

  return (
    <section className="panel atlas-panel">
      <div className="panel-title">
        Atlas
        <span className="atlas-zone">{map?.zone ?? zone ?? ""}</span>
      </div>

      <form className="route-bar" onSubmit={findRoute}>
        <input
          list="zone-list"
          value={dest}
          onChange={(e) => setDest(e.target.value)}
          placeholder="Travel to…"
          aria-label="Destination zone"
        />
        <datalist id="zone-list">
          {zones.map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
        <button type="submit" disabled={!dest.trim()}>Route</button>
        <button type="button" onClick={recenter} title="Lock the chart on the hero at the current zoom">
          Recenter
        </button>
      </form>

      <div className="geo-bar">
        <div className="geo-toggle" role="tablist" aria-label="Map source">
          <button
            type="button"
            data-active={view === "chart"}
            onClick={() => setView("chart")}
          >
            Chart
          </button>
          <button
            type="button"
            data-active={view === "geo"}
            onClick={() => setView("geo")}
          >
            True walls
          </button>
          <button
            type="button"
            data-active={view === "3d"}
            onClick={() => setView("3d")}
          >
            3D
          </button>
        </div>
        {view === "geo" && geom?.available && (geom.floors?.length ?? 0) > 1 && (
          <select
            className="geo-floor"
            value={String(floorSel)}
            onChange={(e) => {
              const val = e.target.value;
              setFloorSel(val === "auto" || val === "all" ? val : Number(val));
            }}
            aria-label="Floor"
          >
            <option value="auto">Floor: auto</option>
            <option value="all">All floors</option>
            {geom.floors!.map((f, i) => (
              <option key={i} value={i}>
                F{i + 1} · z {f.z}
              </option>
            ))}
          </select>
        )}
        {view === "geo" && geom && !geom.available && (
          <span className="geo-note">{geom.reason ?? "No client geometry for this place"}</span>
        )}
        {view === "geo" && !geom && <span className="geo-note">Mining walls from the client…</span>}
      </div>

      {route && (
        <div className="route-chips" aria-label="Route">
          {route.map((z, i) => (
            <span key={z} className="route-chip" data-last={i === route.length - 1}>
              {z}
              {i < route.length - 1 && <span className="route-arrow"> ▸ </span>}
            </span>
          ))}
          <button className="route-clear" onClick={() => setRoute(null)} aria-label="Clear route">
            ×
          </button>
        </div>
      )}
      {routeMsg && <div className="route-msg">{routeMsg}</div>}

      {view === "3d" ? (
        <Atlas3D zone={zone} position={position} />
      ) : (
      <div className="atlas-canvas-wrap" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          className="atlas-canvas"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
          onWheel={onWheel}
        />
        {map && !map.available && (
          <div className="atlas-empty">
            <p>No chart for <strong>{map.zone}</strong>.</p>
            <p className="atlas-empty-sub">
              Classic dungeons keep their secrets — the route finder above still
              knows the way there.
            </p>
          </div>
        )}
        {map?.available && !position && (
          <div className="atlas-hint">
            Type <code>/loc</code> in-game to mark your position — or enable
            live OCR below.
          </div>
        )}
      </div>
      )}

      <div className="ocr-row">
        <span className="ocr-status" data-live={!!(ocr?.enabled && ocr?.last_ok && !ocr?.error)}>
          {!ocr
            ? "Live position: backend offline"
            : !ocr.deps_ok
              ? "Live position: OCR deps missing (pip install -r requirements.txt)"
              : !ocr.game_running
                ? "Live position: game not running"
                : !ocr.enabled
                  ? "Live position: off"
                  : ocr.error
                    ? `Live position: ${ocr.error}`
                    : ocr.last_ok
                      ? `Live position: reading (last ${ocr.last_ok})`
                      : "Live position: searching…"}
        </span>
        <label className="ocr-toggle">
          <input
            type="checkbox"
            checked={ocr?.enabled ?? false}
            onChange={toggleOcr}
            disabled={!ocr?.deps_ok}
          />
          OCR
        </label>
        <button type="button" onClick={() => { setOcrPreview(null); setOcrHelp(true); }} disabled={!ocr?.deps_ok}>
          Calibrate
        </button>
      </div>

      {ocrHelp && (
        <div className="ocr-modal-backdrop" role="dialog" aria-modal="true" aria-label="OCR setup guide">
          <div className="ocr-modal">
            <h3>Live position via screen reading</h3>
            <p className="ocr-modal-note">
              The companion reads the map window&apos;s coordinate text off your
              screen once a second — purely passive, nothing touches the game.
            </p>
            <ol>
              <li>
                In game, open the <strong>Map window</strong> with its location
                readout visible — the lines starting <code>X:</code>{" "}
                <code>Y:</code> <code>Z:</code>. The game must run{" "}
                <strong>Windowed or Borderless</strong>, not exclusive
                Fullscreen.
              </li>
              <li>
                Press <strong>Launch calibrator</strong> — a gold box appears on
                top of the game. Drag and resize it so it{" "}
                <strong>tightly frames the X / Y / Z lines</strong> (nothing
                else). Close the box to save.
              </li>
              <li>
                Press <strong>Test read</strong> — it should echo your
                coordinates. Then flip the <strong>OCR</strong> toggle on and
                the Atlas dot follows you.
              </li>
            </ol>
            <div className="ocr-modal-actions">
              <button type="button" onClick={calibrate}>Launch calibrator</button>
              <button type="button" onClick={testRead}>Test read</button>
              <button type="button" onClick={() => setOcrHelp(false)}>Close</button>
            </div>
            {ocrPreview && <div className="ocr-modal-preview">{ocrPreview}</div>}
          </div>
        </div>
      )}
    </section>
  );
});
