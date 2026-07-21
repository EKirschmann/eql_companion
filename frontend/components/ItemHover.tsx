"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";

interface AcqLine {
  text: string;
  kind: "zone" | "entry" | "note";
}
interface Acquisition {
  item: string;
  sections: { label: string; lines: AcqLine[] }[];
  available: boolean;
}

/** Session-wide client cache — acquisition data is static per item. */
const acqCache = new Map<string, Acquisition>();

const baseName = (n: string) => n.replace(/\s*\+\d+\s*$/, "");

/** An item name that reveals a where-to-get-it card on hover
 *  (wiki-mined Drops From / Sold by / quests / crafting). */
export function ItemHover({ name, children }: { name: string; children?: React.ReactNode }) {
  const [acq, setAcq] = useState<Acquisition | null>(null);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);

  const load = async () => {
    const base = baseName(name);
    const hit = acqCache.get(base);
    if (hit) {
      setAcq(hit);
      return;
    }
    try {
      const d = await apiGet<Acquisition>(
        `/api/item-acquisition?name=${encodeURIComponent(base)}`,
      );
      acqCache.set(base, d);
      setAcq(d);
    } catch {
      /* backend offline — the card just says "looking up" until close */
    }
  };

  const enter = () => {
    timer.current = window.setTimeout(() => {
      setOpen(true);
      void load();
    }, 300);
  };
  const leave = () => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  };
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  return (
    <span className="item-hover" onMouseEnter={enter} onMouseLeave={leave}>
      {children ?? name}
      {open && (
        <span className="item-hover-card" role="tooltip">
          <span className="item-hover-title">{baseName(name)}</span>
          {!acq ? (
            <span className="item-hover-note">looking up…</span>
          ) : !acq.available ? (
            <span className="item-hover-note">no acquisition data on the wiki</span>
          ) : (
            acq.sections.map((s) => (
              <span key={s.label} className="item-hover-sec">
                <span className="item-hover-label">{s.label}</span>
                {s.lines.map((l, i) => (
                  <span key={i} className="item-hover-line" data-kind={l.kind}>
                    {l.text}
                  </span>
                ))}
              </span>
            ))
          )}
        </span>
      )}
    </span>
  );
}