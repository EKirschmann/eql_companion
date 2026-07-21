"use client";

import { memo, useEffect, useState } from "react";
import type { AbilitySummary, DeathRecap, Encounter, EncounterAbility } from "@/lib/types";

const fmt = (n: number) => n.toLocaleString("en-US");

function fightLabel(idx: number, enc: Encounter): string {
  if (idx === 0) return enc.active ? "Active" : "Last fight";
  return idx === 1 ? "1 fight ago" : `${idx} fights ago`;
}

function AbilityTable({ abilities, petSection }: { abilities: EncounterAbility[]; petSection?: boolean }) {
  return (
    <table className="enc-table">
      <thead>
        <tr>
          <th scope="col">Ability</th>
          <th scope="col" title="Successful hits / casts · ✦ = crits">×</th>
          <th scope="col">Avg</th>
          <th scope="col">Total</th>
          <th scope="col">DPS</th>
        </tr>
      </thead>
      <tbody>
        {abilities.map((a) => (
          <tr key={a.name} data-kind={a.kind}>
            <td className="enc-name" title={`${a.hits} hit${a.hits === 1 ? "" : "s"}`}>
              <span className="enc-rule" aria-hidden />
              {petSection ? a.name.replace(/^Pet: /, "") : a.name}
              {a.kind === "dot" && <span className="enc-tag">{a.kind}</span>}
              {a.kind === "ds" && <span className="enc-tag">ds</span>}
              {!petSection && a.kind === "pet" && (
                <span className="enc-tag">{a.kind}</span>
              )}
            </td>
            <td className="enc-count">
              {a.hits}
              {(a.crits ?? 0) > 0 && <span className="enc-crit"> ✦{a.crits}</span>}
            </td>
            <td>{fmt(a.avg)}</td>
            <td>{fmt(a.total)}</td>
            <td>{a.dps}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Damage breakdown for the last 5 pulls. The arrows step back through
 *  recent encounters; the aggregate below sums abilities across all of them
 *  to surface which abilities actually hit hardest over time. */
export const EncounterPanel = memo(function EncounterPanel({
  encounters,
  summary,
  lastDeath,
}: {
  encounters: Encounter[];
  summary: AbilitySummary | null;
  lastDeath: DeathRecap | null;
}) {
  // Anchor the viewed pull by its start time so history shifting underneath
  // (a new fight starting) doesn't yank the panel to a different fight.
  const [viewStarted, setViewStarted] = useState<string | null>(null);

  let idx = viewStarted ? encounters.findIndex((e) => e.started === viewStarted) : 0;
  if (idx < 0) idx = 0;
  const enc = encounters[idx] ?? null;

  useEffect(() => {
    if (viewStarted && !encounters.some((e) => e.started === viewStarted)) {
      setViewStarted(null); // the viewed pull aged out of the 5-fight buffer
    }
  }, [encounters, viewStarted]);

  const step = (d: number) => {
    const next = Math.min(Math.max(idx + d, 0), encounters.length - 1);
    setViewStarted(next === 0 ? null : encounters[next].started);
  };

  const foes = enc?.foes ?? [];
  const slain = foes.filter((f) => f.slain).length;
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const s = parseFloat(localStorage.getItem("eql.encScale") ?? "1");
    if (s >= 0.8 && s <= 1.6) setScale(s);
  }, []);
  const bumpScale = (d: number) => {
    setScale((v) => {
      const n = Math.min(1.6, Math.max(0.8, Math.round((v + d) * 20) / 20));
      localStorage.setItem("eql.encScale", String(n));
      return n;
    });
  };

  return (
    <section className="panel">
      <div className="panel-title">
        Encounter
        <span className="font-scale" aria-label="Encounter text size">
          <button type="button" onClick={() => bumpScale(-0.1)} title="Smaller text">A−</button>
          <button type="button" onClick={() => bumpScale(0.1)} title="Larger text">A+</button>
        </span>
        {enc && (
          <span className="enc-nav">
            <button type="button" onClick={() => step(1)}
                    disabled={idx >= encounters.length - 1} aria-label="Older fight">
              ‹
            </button>
            <span className="enc-status" data-active={enc.active}>
              {fightLabel(idx, enc)}
              {encounters.length > 1 ? ` · ${idx + 1}/${encounters.length}` : ""}
            </span>
            <button type="button" onClick={() => step(-1)}
                    disabled={idx === 0} aria-label="Newer fight">
              ›
            </button>
          </span>
        )}
      </div>
      <div className="panel-body" style={{ zoom: scale }}>
        {!enc ? (
          <p className="chat-empty">
            No encounter yet. The breakdown appears when you enter combat, and
            the last five pulls stay browsable here.
          </p>
        ) : (
          <>
            <div className="enc-summary">
              <div className="enc-target">
                {foes.length > 1
                  ? `${foes.length} foes${slain > 0 ? ` - ${slain} slain` : ""}`
                  : enc.target ?? "Unknown foe"}
              </div>
              <div className="enc-meta">
                {enc.duration}s · {fmt(enc.total_damage)} dmg ·{" "}
                <span className="enc-dps">{enc.dps} DPS</span>
              </div>
              {enc.damage_taken > 0 && (
                <div className="enc-taken">{fmt(enc.damage_taken)} taken</div>
              )}
              {(() => {
                const d = enc.defense ?? {};
                const avoided = Object.values(d).reduce((a, b) => a + b, 0);
                const attacks = avoided + (enc.in_hits ?? 0);
                if (!attacks) return null;
                const parts = ["dodge", "parry", "block", "riposte", "miss"]
                  .filter((k) => d[k])
                  .map((k) => `${k} ${d[k]}`)
                  .join(" · ");
                return (
                  <div className="enc-defense">
                    defense {Math.round((100 * avoided) / attacks)}% —{" "}
                    {parts || "none"} <span className="adv-cls">of {attacks} attacks</span>
                  </div>
                );
              })()}
              {enc.resists && Object.keys(enc.resists).length > 0 && (
                <div className="enc-defense">
                  resisted —{" "}
                  {Object.entries(enc.resists)
                    .map(([sp, n]) => (n > 1 ? `${sp} ×${n}` : sp))
                    .join(" · ")}
                </div>
              )}
              {foes.length > 1 && (
                <ul className="enc-foes" aria-label="Foes in this encounter">
                  {foes.map((f) => (
                    <li key={f.name} data-slain={f.slain}>
                      <span className="enc-foe-name">{f.name}</span>
                      <span className="enc-foe-dmg">{fmt(f.damage)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <AbilityTable abilities={enc.abilities.filter((a) => a.kind !== "pet")} />
            {enc.abilities.some((a) => a.kind === "pet") && (
              <div className="enc-agg">
                <h3>
                  Pet ·{" "}
                  {fmt(enc.abilities.filter((a) => a.kind === "pet")
                    .reduce((s, a) => s + a.total, 0))}
                </h3>
                <AbilityTable
                  abilities={enc.abilities.filter((a) => a.kind === "pet")}
                  petSection
                />
              </div>
            )}

            {enc.heals.length > 0 && (
              <div className="enc-agg">
                <h3>Healing · {fmt(enc.total_healing)}</h3>
                <AbilityTable abilities={enc.heals} />
              </div>
            )}

            {summary && summary.encounters > 1 && (
              <div className="enc-agg">
                <h3>
                  Across last {summary.encounters} fights · {summary.duration}s in combat
                </h3>
                <AbilityTable abilities={summary.abilities.filter((a) => a.kind !== "pet")} />
                {summary.abilities.some((a) => a.kind === "pet") && (
                  <>
                    <div className="adv-sub" style={{ marginTop: 10 }}>Pet</div>
                    <AbilityTable
                      abilities={summary.abilities.filter((a) => a.kind === "pet")}
                      petSection
                    />
                  </>
                )}
                {summary.heals.length > 0 && (
                  <>
                    <div className="adv-sub" style={{ marginTop: 10 }}>Healing</div>
                    <AbilityTable abilities={summary.heals} />
                  </>
                )}
              </div>
            )}

            {enc.allies.length > 1 && (
              <div className="enc-agg">
                <h3>Group — this fight</h3>
                <table className="enc-table">
                  <thead>
                    <tr>
                      <th scope="col">Member</th>
                      <th scope="col">Total</th>
                      <th scope="col">DPS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {enc.allies.map((a) => (
                      <tr key={a.name} data-you={a.name === "You"}>
                        <td className="enc-name">
                          <span className="enc-rule" aria-hidden />
                          {a.name}
                          {a.is_pet && <span className="enc-tag">pet</span>}
                          {!a.is_pet && (a.level != null || a.classes) && (
                            <span className="enc-member-meta">
                              {a.level ?? "?"} {a.classes ?? ""}
                            </span>
                          )}
                        </td>
                        <td>{fmt(a.damage)}</td>
                        <td>{a.dps}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        {lastDeath && (
          <div className="enc-agg enc-death">
            <h3>
              Last death · {new Date(lastDeath.ts).toLocaleTimeString("en-GB", { hour12: false })} · slain by {lastDeath.killer}
            </h3>
            <ul className="death-recap">
              {lastDeath.hits.map((hit, i) => (
                <li key={i}>
                  <span>{hit.attacker} · {hit.source}</span>
                  <span className="death-dmg">−{fmt(hit.damage)}</span>
                </li>
              ))}
            </ul>
            <div className="death-total">
              {fmt(lastDeath.total)} damage in the final 15s
            </div>
          </div>
        )}
      </div>
    </section>
  );
});