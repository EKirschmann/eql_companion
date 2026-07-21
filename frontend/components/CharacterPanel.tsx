"use client";

import { memo, useEffect, useState } from "react";
import { apiSend } from "@/lib/api";
import type { Snapshot } from "@/lib/types";

const PLAYSTYLES = [
  "solo_dps", "group_dps", "tank", "healer", "support", "pet_focused", "balanced",
];

const fmt = (n: number) => n.toLocaleString("en-US");

/** 3267 copper -> "3p 2g 6s 7c" (zero denominations omitted). */
const fmtCoin = (c: number) => {
  if (!c) return "0c";
  const parts = [
    [Math.floor(c / 1000), "p"],
    [Math.floor((c % 1000) / 100), "g"],
    [Math.floor((c % 100) / 10), "s"],
    [c % 10, "c"],
  ] as const;
  return parts.filter(([n]) => n > 0).map(([n, u]) => `${n}${u}`).join(" ") || "0c";
};

export const CharacterPanel = memo(function CharacterPanel({
  snap,
  onSnapChange,
}: {
  snap: Snapshot | null;
  onSnapChange: (s: Snapshot) => void;
}) {
  const [hpDraft, setHpDraft] = useState("");
  const [manaDraft, setManaDraft] = useState("");
  useEffect(() => {
    setHpDraft(snap?.max_hp != null ? String(snap.max_hp) : "");
  }, [snap?.max_hp]);
  useEffect(() => {
    setManaDraft(snap?.max_mana != null ? String(snap.max_mana) : "");
  }, [snap?.max_mana]);
  if (!snap) {
    return (
      <section className="panel">
        <div className="panel-title">Vitals &amp; Session</div>
        <div className="panel-body">
          <p className="chat-empty">
            Waiting for the backend. Start it with{" "}
            <code>uvicorn backend.main:app --reload</code>.
          </p>
        </div>
      </section>
    );
  }

  const s = snap.session;
  const dpsPct = snap.session_max_dps > 0
    ? Math.min(100, (snap.dps / snap.session_max_dps) * 100)
    : 0;

  const patchVitals = async (field: "max_hp" | "max_mana", raw: string) => {
    const v = parseInt(raw, 10);
    if (!Number.isFinite(v) || v <= 0) return;
    if (v === (snap[field] ?? null)) return;
    try {
      const updated = await apiSend<Snapshot>("/api/character", { [field]: v }, "PATCH");
      onSnapChange(updated);
    } catch {
      /* backend offline — leave as-is */
    }
  };

  const setPlaystyle = async (playstyle: string) => {
    try {
      const updated = await apiSend<Snapshot>("/api/character", { playstyle }, "PATCH");
      onSnapChange(updated);
    } catch {
      /* backend offline — leave as-is */
    }
  };

  return (
    <section className="panel">
      <div className="panel-title">Vitals &amp; Session</div>
      <div className="panel-body">
        <div className="level-row">
          <div className="level-num">{snap.level ?? "?"}</div>
          <div className="level-meta">
            Level
            <br />
            {snap.in_combat ? (
              <span className="combat-flag">
                In combat{snap.last_target ? ` — ${snap.last_target}` : ""}
              </span>
            ) : (
              <span>At ease</span>
            )}
          </div>
        </div>

        <div
          className="vitals-edit"
          title="The log never prints your max HP/mana — copy them from the in-game UI once (update after level-ups) and gear advice can say what a +75 HP swap really means for you."
        >
          <label htmlFor="maxhp">
            Max HP
            <input
              id="maxhp"
              type="number"
              min={1}
              placeholder="?"
              value={hpDraft}
              onChange={(e) => setHpDraft(e.target.value)}
              onBlur={() => patchVitals("max_hp", hpDraft)}
              onKeyDown={(e) => e.key === "Enter" && patchVitals("max_hp", hpDraft)}
            />
          </label>
          <label htmlFor="maxmana">
            Max Mana
            <input
              id="maxmana"
              type="number"
              min={1}
              placeholder="?"
              value={manaDraft}
              onChange={(e) => setManaDraft(e.target.value)}
              onBlur={() => patchVitals("max_mana", manaDraft)}
              onKeyDown={(e) => e.key === "Enter" && patchVitals("max_mana", manaDraft)}
            />
          </label>
        </div>

        {snap.level === null && (
          <p style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
            Level unknown — type <code>/who</code> in-game once and the
            companion learns your level and class from the log.
          </p>
        )}

        {snap.loadout_hint && (
          <p className="loadout-hint" role="status">{snap.loadout_hint}</p>
        )}

        {snap.sync_hints.length > 0 && (
          <div className="sync-hints" role="status">
            {snap.sync_hints.map((h) => (
              <p key={h.command + h.reason} className="sync-hint">
                {h.reason} — type <code>{h.command}</code> in-game.
              </p>
            ))}
          </div>
        )}

        <div className="gauge">
          <div className="gauge-label">
            <span>DPS (60s)</span>
            <span className="gauge-value">{snap.dps}</span>
          </div>
          <div className="gauge-track">
            <div className="gauge-fill" style={{ width: `${dpsPct}%` }} />
          </div>
        </div>

        <div className="tiles">
          <div className="tile" data-accent="out">
            <div className="tile-value">{fmt(s.damage_dealt)}</div>
            <div className="tile-label">Damage dealt</div>
          </div>
          <div className="tile" data-accent="in">
            <div className="tile-value">{fmt(s.damage_taken)}</div>
            <div className="tile-label">Damage taken</div>
          </div>
          <div className="tile" data-accent="heal">
            <div className="tile-value">{fmt(s.healing_received)}</div>
            <div className="tile-label">Healing received</div>
          </div>
          <div className="tile" data-accent="heal">
            <div className="tile-value">{fmt(s.healing_done)}</div>
            <div className="tile-label">Healing done</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">{s.kills}</div>
            <div className="tile-label">Kills</div>
          </div>
          <div className="tile" data-accent="in">
            <div className="tile-value">{s.deaths}</div>
            <div className="tile-label">Deaths</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">
              {s.xp_percent > 0 ? `${s.xp_percent.toFixed(1)}%` : s.xp_ticks}
            </div>
            <div className="tile-label">XP gained</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">{s.aa_points}</div>
            <div className="tile-label">AA points</div>
          </div>
          <div className="tile">
            <div className="tile-value">{s.hit_rate}%</div>
            <div className="tile-label">Hit rate</div>
          </div>
          <div className="tile">
            <div className="tile-value">{s.skill_ups}</div>
            <div className="tile-label">Skill-ups</div>
          </div>
          <div className="tile" data-accent="milestone">
            <div className="tile-value">{fmtCoin(s.coin_copper ?? 0)}</div>
            <div className="tile-label">Coin earned</div>
          </div>
          <div className="tile" data-accent="out">
            <div className="tile-value">{s.crits ?? 0}</div>
            <div className="tile-label">Crits ✦</div>
          </div>
        </div>

        {s.loots.length > 0 && (
          <div className="loot-list">
            <h3>Recent loot</h3>
            <ul>
              {s.loots.slice(0, 6).map((item, i) => (
                <li key={`${item}-${i}`}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {snap.mob_stats.length > 0 && (
          <div className="loot-list hunt-list">
            <h3>Session hunting</h3>
            <table className="hunt-table">
              <thead>
                <tr>
                  <th scope="col">Mob</th>
                  <th scope="col">Kills</th>
                  <th scope="col">XP</th>
                  <th scope="col">Coin</th>
                  <th scope="col" title="Observed drop rate — items dropped / kills">
                    Drops
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...snap.mob_stats]
                  .sort((a, b) => (b.xp_percent ?? 0) - (a.xp_percent ?? 0) || b.kills - a.kills)
                  .slice(0, 8)
                  .map((m) => (
                  <tr key={m.name} title={m.loots.join(", ") || undefined}>
                    <td className="hunt-name">{m.name}</td>
                    <td>{m.kills}</td>
                    <td>{m.xp_percent > 0 ? `${m.xp_percent.toFixed(1)}%` : "—"}</td>
                    <td>{m.coin_copper ? fmtCoin(m.coin_copper) : "—"}</td>
                    <td>
                      {m.kills > 0 && (m.loot_drops ?? 0) > 0
                        ? `${Math.round((100 * (m.loot_drops ?? 0)) / m.kills)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="focus-row">
          <label htmlFor="playstyle">Focus</label>
          <select
            id="playstyle"
            value={snap.playstyle ?? "balanced"}
            onChange={(e) => setPlaystyle(e.target.value)}
          >
            {PLAYSTYLES.map((p) => (
              <option key={p} value={p}>
                {p.replace("_", " ")}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
});
