"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import type { LedgerRow, Snapshot, WsMessage } from "@/lib/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { APP_VERSION } from "@/lib/version";
import { AdvisorPanel } from "@/components/AdvisorPanel";
import { AtlasPanel } from "@/components/AtlasPanel";
import { CharacterPanel } from "@/components/CharacterPanel";
import { CompanionPanel } from "@/components/CompanionPanel";
import { EncounterPanel } from "@/components/EncounterPanel";
import { WarLedger } from "@/components/WarLedger";

const MAX_ROWS = 300;

interface CharacterEntry {
  name: string;
  server: string | null;
  file: string;
}

export default function Home() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [overlayOn, setOverlayOn] = useState(false);
  const [updateMsg, setUpdateMsg] = useState<{ text: string; newer: boolean } | null>(null);

  const checkUpdates = async () => {
    setUpdateMsg({ text: "checking…", newer: false });
    try {
      const r = await apiGet<{ current: string; latest: string | null; update_available?: boolean; error?: string }>(
        "/api/update-check",
      );
      if (r.error) setUpdateMsg({ text: r.error, newer: false });
      else if (r.update_available)
        setUpdateMsg({ text: `v${r.latest} available — close the app and run update_companion.bat`, newer: true });
      else setUpdateMsg({ text: "up to date", newer: false });
    } catch {
      setUpdateMsg({ text: "backend offline", newer: false });
    }
    setTimeout(() => setUpdateMsg(null), 10000);
  };

  useEffect(() => {
    apiGet<{ running: boolean }>("/api/overlay")
      .then((r) => setOverlayOn(r.running))
      .catch(() => {});
  }, []);
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [centerTab, setCenterTab] = useState<"atlas" | "companion" | "advisor">("atlas");

  // Monotonic id stamped on receipt — stable React keys for ledger rows.
  const idRef = useRef(0);
  const stamp = useCallback(
    (rs: LedgerRow[]) => rs.map((r) => ({ ...r, _id: ++idRef.current })),
    [],
  );

  const onMessage = useCallback(
    (msg: WsMessage) => {
      if (msg.type === "hello" || msg.type === "state") {
        setSnap(msg.data);
      } else if (msg.type === "events") {
        // one batched frame per ~150ms instead of one render per swing
        setRows((prev) => [...prev, ...stamp(msg.data)].slice(-MAX_ROWS));
      } else if (msg.type === "event") {
        setRows((prev) => [...prev, ...stamp([msg.data])].slice(-MAX_ROWS));
      }
    },
    [stamp],
  );

  const status = useWebSocket(onMessage);
  const [chars, setChars] = useState<CharacterEntry[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ characters: CharacterEntry[]; active_file: string | null }>("/api/characters")
      .then((r) => {
        setChars(r.characters);
        setActiveFile(r.active_file);
      })
      .catch(() => {});
  }, []);

  const switchChar = async (file: string) => {
    if (!file || file === activeFile) return;
    try {
      const s = await apiSend<Snapshot>("/api/character/select", { file });
      setSnap(s);
      setActiveFile(file);
      setRows([]);
      apiGet<{ events: LedgerRow[] }>("/api/events?limit=120")
        .then((r) => setRows(stamp(r.events)))
        .catch(() => {});
    } catch {
      /* backend offline or unknown character */
    }
  };

  useEffect(() => {
    apiGet<Snapshot>("/api/character").then(setSnap).catch(() => {});
    apiGet<{ events: LedgerRow[] }>("/api/events?limit=120")
      .then((r) => setRows(stamp(r.events)))
      .catch(() => {});
  }, [stamp]);

  const statusLabel =
    status === "linked" ? "Linked" : status === "connecting" ? "Linking" : "Link lost";

  return (
    <main className="hud">
      <header className="hud-header">
        <div>
          <div className="eyebrow">
            EQL Companion{" "}
            <button
              type="button"
              className="app-version"
              onClick={checkUpdates}
              title="Check for updates (compares against the latest release on GitHub)"
            >
              v{APP_VERSION}
            </button>
            {updateMsg && (
              <span className="update-msg" data-newer={updateMsg.newer ? "1" : undefined}>
                {updateMsg.text}
              </span>
            )}
          </div>
          <h1 className="nameplate">{snap?.name ?? "—"}</h1>
          <div className="nameplate-sub">
            {snap?.server ?? ""}
            {snap?.class_str ? ` — ${snap.class_str}` : ""}
            {snap?.race ? ` — ${snap.race}` : ""}
          </div>
        </div>
        <div className="header-right">
          {chars.length > 1 && (
            <div className="zone-now">
              <div className="zone-label">Character</div>
              <select
                className="char-select"
                value={activeFile ?? ""}
                onChange={(e) => switchChar(e.target.value)}
                aria-label="Active character"
              >
                {!activeFile && <option value="">—</option>}
                {chars.map((c) => (
                  <option key={c.file} value={c.file}>
                    {c.name}{c.server ? ` — ${c.server}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="zone-now">
            <div className="zone-label">Current zone</div>
            <div className="zone-name">{snap?.zone ?? "Unknown"}</div>
          </div>
          <button
            type="button"
            className="overlay-btn"
            data-on={overlayOn ? "1" : undefined}
            onClick={() =>
              apiSend<{ running: boolean }>("/api/overlay", {})
                .then((r) => setOverlayOn(r.running))
                .catch(() => {})
            }
            title="Toggle the always-on-top combat strip (Scroll Lock ON = move it, OFF = click-through)"
          >
            {overlayOn ? "Overlay ✕" : "Overlay"}
          </button>
          <div className="link" data-status={status}>
            <span className="link-rune" aria-hidden />
            {statusLabel}
          </div>
        </div>
      </header>

      <div className="hud-grid">
        <CharacterPanel snap={snap} onSnapChange={setSnap} />
        <div className="center-stack">
          <div className="tab-row" role="tablist">
            <button
              role="tab"
              aria-selected={centerTab === "atlas"}
              data-active={centerTab === "atlas"}
              onClick={() => setCenterTab("atlas")}
            >
              Atlas
            </button>
            <button
              role="tab"
              aria-selected={centerTab === "companion"}
              data-active={centerTab === "companion"}
              onClick={() => setCenterTab("companion")}
            >
              Companion
            </button>
            <button
              role="tab"
              aria-selected={centerTab === "advisor"}
              data-active={centerTab === "advisor"}
              onClick={() => setCenterTab("advisor")}
            >
              Advisor
            </button>
          </div>
          {centerTab === "atlas" ? (
            <AtlasPanel zone={snap?.zone ?? null} position={snap?.position ?? null} />
          ) : centerTab === "companion" ? (
            <CompanionPanel />
          ) : (
            <AdvisorPanel snap={snap} onSnapChange={setSnap} />
          )}
        </div>
        <WarLedger rows={rows} />
        <EncounterPanel
          encounters={snap?.encounters ?? []}
          summary={snap?.ability_summary ?? null}
          lastDeath={snap?.last_death ?? null}
        />
      </div>
    </main>
  );
}
