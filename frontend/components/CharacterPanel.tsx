"use client";

import { memo } from "react";
import { apiSend } from "@/lib/api";
import type { Snapshot } from "@/lib/types";

const PLAYSTYLES = [
  "solo_dps", "group_dps", "tank", "healer", "support", "pet_focused", "balanced",
];

const fmt = (n: number) => n.toLocaleString("en-US");

export const CharacterPanel = memo(function CharacterPanel({
  snap,
  onSnapChange,
}: {
  snap: Snapshot | null;
  onSnapChange: (s: Snapshot) => void;
}) {
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
