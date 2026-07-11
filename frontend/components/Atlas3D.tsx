"use client";

import { memo, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { API_URL, apiGet } from "@/lib/api";
import type { Position, ZoneGeometry3D } from "@/lib/types";

/** Defaults per spec: ceilings never shipped, walls on at 50%, stairs &
 *  ramps on, props on, no floor highlighting. Zone layers cull backfaces
 *  (FrontSide) for the dollhouse look — roofs vanish when orbiting above. */
const LAYER_STYLE = {
  floors: { color: 0x6e5f42, opacity: 1.0, transparent: false },
  ramps: { color: 0xc8aa6e, opacity: 1.0, transparent: false },
  walls: { color: 0xcbb68a, opacity: 0.5, transparent: true },
  props: { color: 0x8d7f5f, opacity: 1.0, transparent: false },
} as const;
type LayerKey = keyof typeof LAYER_STYLE;
const LAYER_KEYS = Object.keys(LAYER_STYLE) as LayerKey[];

interface SceneRefs {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  groups: Partial<Record<LayerKey, THREE.Group>>;
  hero: THREE.Mesh;
  render: () => void;
}

function disposeGroup(scene: THREE.Scene, group?: THREE.Group) {
  if (!group) return;
  scene.remove(group);
  group.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (mesh.isMesh) {
      mesh.geometry.dispose();
      const mat = mesh.material as THREE.MeshLambertMaterial;
      mat.map?.dispose();
      mat.dispose();
    }
  });
}

export const Atlas3D = memo(function Atlas3D({
  zone,
  position,
}: {
  zone: string | null;
  position: Position | null;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SceneRefs | null>(null);
  const [geom, setGeom] = useState<ZoneGeometry3D | null>(null);
  const [show, setShow] = useState<Record<LayerKey, boolean>>({
    floors: true, ramps: true, walls: true, props: true,
  });
  const [wallOpacity, setWallOpacity] = useState(0.5);

  // fetch the 3D payload per zone (extracted + cached server-side)
  useEffect(() => {
    if (!zone) return;
    let cancelled = false;
    setGeom(null);
    apiGet<ZoneGeometry3D>(`/api/geometry3d?zone=${encodeURIComponent(zone)}`)
      .then((g) => {
        if (!cancelled) setGeom(g);
      })
      .catch(() => {
        if (!cancelled) setGeom({ available: false, zone, reason: "Backend unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, [zone]);

  // scene lifecycle (once per mount)
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x16130f);
    const camera = new THREE.PerspectiveCamera(55, 1, 1, 40000);
    camera.up.set(0, 0, 1); // WLD is z-up
    const controls = new OrbitControls(camera, renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const sun = new THREE.DirectionalLight(0xfff2d0, 1.2);
    sun.position.set(0.6, 1, 2);
    scene.add(sun);
    const hero = new THREE.Mesh(
      new THREE.SphereGeometry(5, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0x1fb38c }),
    );
    hero.visible = false;
    scene.add(hero);
    const render = () => renderer.render(scene, camera);
    controls.addEventListener("change", render);
    const ro = new ResizeObserver(() => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    });
    ro.observe(mount);
    sceneRef.current = { renderer, scene, camera, controls, groups: {}, hero, render };
    return () => {
      ro.disconnect();
      controls.dispose();
      Object.values(sceneRef.current?.groups ?? {}).forEach((g) =>
        disposeGroup(scene, g));
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      sceneRef.current = null;
    };
  }, []);

  return (
    <div className="atlas3d">
      <div className="geo-bar atlas3d-bar">
        {LAYER_KEYS.map((k) => (
          <label key={k} className="atlas3d-toggle">
            <input
              type="checkbox"
              checked={show[k]}
              onChange={(e) => setShow((p) => ({ ...p, [k]: e.target.checked }))}
            />
            {k === "ramps" ? "stairs & ramps" : k}
          </label>
        ))}
        <label className="atlas3d-toggle">
          wall {Math.round(wallOpacity * 100)}%
          <input
            type="range"
            min={10}
            max={100}
            step={5}
            value={Math.round(wallOpacity * 100)}
            onChange={(e) => setWallOpacity(Number(e.target.value) / 100)}
          />
        </label>
        {!geom && <span className="geo-note">Mining the zone…</span>}
        {geom && !geom.available && <span className="geo-note">{geom.reason}</span>}
        {geom?.available && <span className="geo-note">drag to orbit · scroll to zoom</span>}
      </div>
      <div className="atlas3d-mount" ref={mountRef} />
      <Atlas3DEffects
        geom={geom}
        show={show}
        wallOpacity={wallOpacity}
        position={position}
        sceneRef={sceneRef}
      />
    </div>
  );
});

/** Imperative scene updates kept out of the main component so its JSX stays
 *  readable; renders nothing. */
function Atlas3DEffects({
  geom,
  show,
  wallOpacity,
  position,
  sceneRef,
}: {
  geom: ZoneGeometry3D | null;
  show: Record<LayerKey, boolean>;
  wallOpacity: number;
  position: Position | null;
  sceneRef: React.MutableRefObject<SceneRefs | null>;
}) {
  // (re)build layer groups when a zone payload arrives
  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    LAYER_KEYS.forEach((k) => disposeGroup(s.scene, s.groups[k]));
    s.groups = {};
    if (geom?.available && geom.layers) {
      const loader = new THREE.TextureLoader();
      LAYER_KEYS.forEach((k) => {
        const subs = geom.layers![k];
        if (!subs?.length) return;
        const st = LAYER_STYLE[k];
        const group = new THREE.Group();
        subs.forEach((sub) => {
          if (!sub.pos.length) return;
          const g3 = new THREE.BufferGeometry();
          g3.setAttribute("position", new THREE.Float32BufferAttribute(sub.pos, 3));
          g3.setAttribute("uv", new THREE.Float32BufferAttribute(sub.uv, 2));
          g3.computeVertexNormals();
          const mat = new THREE.MeshLambertMaterial({
            color: sub.tex ? 0xffffff : st.color,
            transparent: st.transparent || sub.masked,
            opacity: k === "walls" ? wallOpacity : st.opacity,
            alphaTest: sub.masked ? 0.5 : 0,
            // dollhouse: cull zone backfaces so roofs never block the view
            side: k === "props" ? THREE.DoubleSide : THREE.FrontSide,
            depthWrite: k !== "walls",
          });
          if (sub.tex && geom.zone) {
            loader.load(
              `${API_URL}/api/texture/${geom.zone}/${sub.tex}`,
              (tx) => {
                tx.wrapS = tx.wrapT = THREE.RepeatWrapping;
                tx.colorSpace = THREE.SRGBColorSpace;
                tx.flipY = false;
                tx.needsUpdate = true;
                mat.map = tx;
                mat.needsUpdate = true;
                s.render();
              },
            );
          }
          group.add(new THREE.Mesh(g3, mat));
        });
        group.visible = show[k];
        s.scene.add(group);
        s.groups[k] = group;
      });
      const b = geom.bounds;
      if (b) {
        const cx = (b.min_x + b.max_x) / 2;
        const cy = (b.min_y + b.max_y) / 2;
        const cz = (b.min_z + b.max_z) / 2;
        const span = Math.max(b.max_x - b.min_x, b.max_y - b.min_y, 200);
        s.controls.target.set(cx, cy, cz);
        s.camera.position.set(cx, cy - span * 0.55, cz + span * 0.75);
        s.camera.far = span * 10;
        s.camera.updateProjectionMatrix();
        s.controls.update();
      }
    }
    s.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geom, sceneRef]);

  // visibility + wall opacity without rebuilding buffers
  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    LAYER_KEYS.forEach((k) => {
      const g = s.groups[k];
      if (g) g.visible = show[k];
    });
    s.groups.walls?.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        (mesh.material as THREE.MeshLambertMaterial).opacity = wallOpacity;
      }
    });
    s.render();
  }, [show, wallOpacity, sceneRef]);

  // hero marker: tracker /loc (x=locX, y=locY, z) -> WLD space (locY, locX, z)
  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    if (position) {
      s.hero.position.set(position.y, position.x, position.z);
      s.hero.visible = true;
    } else {
      s.hero.visible = false;
    }
    s.render();
  }, [position, geom, sceneRef]);

  return null;
}
