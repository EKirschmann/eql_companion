"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import type { Advice, ExportsStatus, GearAdvice, HuntingData, LlmInfo, OwnedAAsInfo, Snapshot, SpellbookInfo } from "@/lib/types";

const CLASSES = [
  "Warrior", "Cleric", "Paladin", "Ranger", "Shadow Knight", "Druid",
  "Monk", "Bard", "Rogue", "Shaman", "Necromancer", "Wizard",
  "Magician", "Enchanter", "Beastlord", "Berserker",
];

const TRIO_LABELS = ["Primary", "Secondary", "Tertiary"] as const;

const HG_TICKS = [10, 20, 30, 40, 50, 60];
const HG_MIN = 1;
const HG_MAX = 65;
const hgX = (l: number) => ((Math.min(l, HG_MAX) - HG_MIN) / (HG_MAX - HG_MIN)) * 100;

/** Merge 5-level marks (each mark m = content in [m, m+5)) into bar spans. */
function hgSegments(levels: number[]): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (const m of [...levels].sort((a, b) => a - b)) {
    const last = out[out.length - 1];
    if (last && m <= last[1]) last[1] = m + 5;
    else out.push([m, m + 5]);
  }
  return out;
}

/** Gantt of hunting-zone level bands (community Recommended-Levels table):
 *  the advisor's picks highlighted, best remaining at-level zones as context,
 *  a green line at the character's level. */
function HuntChart({ data, picked }: { data: HuntingData; picked: string[] }) {
  const lv = data.level ?? 0;
  const isPicked = (z: string) => picked.some((p) => p.startsWith(z));
  const rows = [
    ...data.zones.filter((z) => isPicked(z.zone)),
    ...data.zones.filter((z) => !isPicked(z.zone)),
  ]
    .slice(0, 8)
    .sort((a, b) => Math.min(...a.levels) - Math.min(...b.levels));
  return (
    <div className="hunt-gantt" role="img" aria-label={`Level bands of ${rows.length} hunting zones around level ${lv}`}>
      <div className="hg-row hg-head" aria-hidden="true">
        <span className="hg-label" />
        <div className="hg-track">
          {HG_TICKS.map((t) => (
            <span key={t} className="hg-tick" style={{ left: `${hgX(t)}%` }}>{t}</span>
          ))}
          <span className="hg-now-label" style={{ left: `${hgX(lv)}%` }}>you · {lv}</span>
        </div>
      </div>
      {rows.map((z) => (
        <div key={z.zone} className={`hg-row${isPicked(z.zone) ? " hg-picked" : ""}`}>
          <span className="hg-label" title={`${z.zone} (levels ${z.band})`}>{z.zone}</span>
          <div className="hg-track">
            {HG_TICKS.map((t) => (
              <i key={t} className="hg-grid" style={{ left: `${hgX(t)}%` }} />
            ))}
            {hgSegments(z.levels).map(([a, b]) => (
              <i key={a} className="hg-seg" style={{ left: `${hgX(a)}%`, width: `${hgX(b) - hgX(a)}%` }} />
            ))}
            <i className="hg-now" style={{ left: `${hgX(lv)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Class-trio counsel: spells to learn, AA spending order, upcoming unlocks,
 *  and picks for the current zone. The backend grounds the counsel in EQL
 *  wiki data (via MCP) and generates it with the configured LLM, caching it
 *  until the character context changes. */
export const AdvisorPanel = memo(function AdvisorPanel({
  snap,
  onSnapChange,
}: {
  snap: Snapshot | null;
  onSnapChange: (s: Snapshot) => void;
}) {
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aaDraft, setAaDraft] = useState("");
  const [slotsDraft, setSlotsDraft] = useState("");
  const [petSlotsDraft, setPetSlotsDraft] = useState("");
  const [petClassDraft, setPetClassDraft] = useState("");
  const [book, setBook] = useState<SpellbookInfo | null>(null);
  const [ownedAAs, setOwnedAAs] = useState<OwnedAAsInfo | null>(null);
  const [exports, setExports] = useState<ExportsStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [scanResult, setScanResult] = useState<{ text: string; ok: boolean } | null>(null);
  const [hunting, setHunting] = useState<HuntingData | null>(null);
  const [pickSel, setPickSel] = useState<Record<string, boolean>>({});
  const [llm, setLlm] = useState<LlmInfo | null>(null);
  const [llmModelDraft, setLlmModelDraft] = useState("");
  const scanTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flashScanResult = (text: string, ok: boolean, sticky = false) => {
    setScanResult({ text, ok });
    if (scanTimer.current) clearTimeout(scanTimer.current);
    if (!sticky) scanTimer.current = setTimeout(() => setScanResult(null), 8000);
  };
  useEffect(() => () => {
    if (scanTimer.current) clearTimeout(scanTimer.current);
  }, []);

  const trio = (snap?.class_str ?? "").split("/").map((s) => s.trim());

  useEffect(() => {
    apiGet<HuntingData>("/api/hunting")
      .then(setHunting)
      .catch(() => setHunting(null));
  }, [snap?.level]);

  useEffect(() => {
    apiGet<LlmInfo>("/api/llm")
      .then((info) => {
        setLlm(info);
        setLlmModelDraft(
          info.active.provider === "openai" || info.active.provider === "custom"
            ? info.active.model
            : "",
        );
      })
      .catch(() => setLlm(null));
  }, []);

  const switchLlm = async (provider: string, model?: string) => {
    try {
      const r = await apiSend<LlmInfo>("/api/llm", { provider, model }, "POST");
      setLlm((prev) => ({ ...(prev ?? r), ...r }));
      if (provider === "openai" || provider === "custom") setLlmModelDraft(r.active.model);
    } catch {
      /* backend offline */
    }
  };

  useEffect(() => {
    setAaDraft(snap?.aa_available == null ? "" : String(snap.aa_available));
  }, [snap?.aa_available]);
  useEffect(() => {
    setSlotsDraft(snap?.spell_slots == null ? "" : String(snap.spell_slots));
  }, [snap?.spell_slots]);
  useEffect(() => {
    setPetSlotsDraft(snap?.pet_slots == null ? "" : String(snap.pet_slots));
  }, [snap?.pet_slots]);
  useEffect(() => {
    setPetClassDraft(snap?.pet_classes ?? "");
  }, [snap?.pet_classes]);

  const patch = async (body: Record<string, unknown>) => {
    try {
      onSnapChange(await apiSend<Snapshot>("/api/character", body, "PATCH"));
    } catch {
      /* backend offline */
    }
  };

  const setTrioAt = (i: number, cls: string) => {
    const next = [trio[0] ?? "", trio[1] ?? "", trio[2] ?? ""];
    next[i] = cls;
    patch({ class_str: next.filter(Boolean).join("/") });
  };

  const numberPatch = (draft: string, field: "aa_available" | "spell_slots" | "pet_slots") => {
    if (draft === "") return;
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 0) patch({ [field]: Math.floor(n) });
  };

  const [rescanning, setRescanning] = useState(false);
  const [gear, setGear] = useState<GearAdvice | null>(null);
  const [gearLoading, setGearLoading] = useState(false);

  useEffect(() => {
    // restore the last gear counsel if the backend still has it (no LLM run)
    apiGet<GearAdvice & { cached?: boolean }>("/api/gear?cached=1")
      .then((r) => {
        if (r && (r as { source?: string }).source) setGear(r);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const writeSpellSet = async (source: "loadout" | "prebuffs") => {
    const names =
      source === "loadout" && advice
        ? [...advice.must_have, ...advice.should_have, ...advice.nice_to_have]
            .filter((s) => pickSel[s.name])
            .map((s) => s.name)
        : undefined;
    try {
      const r = await apiSend<{ name: string; count: number; memspellset: string; skipped: string[]; note: string }>(
        "/api/spellsets/generate",
        { source, names },
      );
      flashScanResult(
        `set "${r.name}" written (${r.count} spells) — in game: ${r.memspellset}` +
          (r.skipped.length ? ` · no id for: ${r.skipped.join(", ")}` : "") +
          ` · ${r.note}`,
        true,
        true,
      );
    } catch (e) {
      flashScanResult(`spell-set write failed: ${e instanceof Error ? e.message : "backend error"}`, false, true);
    }
  };

  useEffect(() => {
    if (!advice) return;
    const sel: Record<string, boolean> = {};
    advice.must_have.forEach((s) => { sel[s.name] = true; });
    advice.should_have.forEach((s) => { sel[s.name] = true; });
    advice.nice_to_have.forEach((s) => { sel[s.name] = sel[s.name] ?? false; });
    setPickSel(sel);
  }, [advice]);

  const consultGear = async (refresh: boolean) => {
    setGearLoading(true);
    try {
      setGear(await apiGet<GearAdvice>(`/api/gear${refresh ? "?refresh=1" : ""}`));
    } catch {
      /* backend offline */
    }
    setGearLoading(false);
  };
  const rescanAAs = async () => {
    setRescanning(true);
    try {
      const res = await apiSend<{ found: boolean; distinct?: number; synced?: string }>(
        "/api/aas/rescan", {});
      const aas = await apiGet<OwnedAAsInfo>("/api/aas");
      setOwnedAAs(aas);
      if (res.found) {
        flashScanResult(
          `log scan done — ${res.distinct} AAs (listed ${res.synced ? new Date(res.synced).toLocaleTimeString() : "?"})`,
          true);
      } else {
        flashScanResult("log scan done — no /alternateadv output found", false);
      }
    } catch {
      flashScanResult("log scan failed — is the backend running?", false);
    }
    setRescanning(false);
  };

  const consult = useCallback(async (refresh: boolean) => {
    setLoading(true);
    setError(null);
    setScanResult(null); // sticky spell-set notes live until the next consult
    try {
      setAdvice(await apiGet<Advice>(`/api/advisor${refresh ? "?refresh=1" : ""}`));
    } catch {
      setError("The advisor is unreachable — is the backend running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // restore the last counsel if the backend still has it — never trigger
    // an LLM run without the Consult button
    apiGet<Advice & { cached?: boolean }>("/api/advisor?cached=1")
      .then((r) => {
        if (r && (r as { source?: string }).source) setAdvice(r);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // owned-state sync chips (refresh alongside every consult)
  useEffect(() => {
    apiGet<SpellbookInfo>("/api/spellbook").then(setBook).catch(() => {});
    apiGet<OwnedAAsInfo>("/api/aas").then(setOwnedAAs).catch(() => {});
    apiGet<ExportsStatus>("/api/exports").then(setExports).catch(() => {});
  }, [advice]);

  // "check exports": fresh directory scan after the in-game /outputfile
  // macro; re-consult when anything actually changed.
  const checkExports = async () => {
    setChecking(true);
    try {
      const fresh = await apiSend<ExportsStatus>("/api/exports/refresh", {});
      const changed = Object.keys(fresh).filter(
        (k) => fresh[k]?.updated !== exports?.[k]?.updated,
      );
      const found = Object.keys(fresh).filter((k) => fresh[k]?.found);
      setExports(fresh);
      apiGet<SpellbookInfo>("/api/spellbook").then(setBook).catch(() => {});
      if (found.length === 0) {
        flashScanResult("scan done — no exports found; run the /outputfile macro first", false);
      } else if (changed.length > 0) {
        flashScanResult(`scan done — updated: ${changed.join(", ")} — press Consult to refresh counsel`, true);
      } else {
        flashScanResult(`scan done — ${found.length} exports present, nothing new`, true);
      }
    } catch {
      flashScanResult("scan failed — is the backend running?", false);
    }
    setChecking(false);
  };

  // fresh owned-state landing while the tab is open (/alternateadv list in
  // the log, a new /outputfile spellbook) no longer auto-consults — the
  // sync chips show freshness and the user consults when ready.

  const aaBlock = (items: Advice["aa_now"], emptyText: string) =>
    items.length === 0 ? (
      <p className="adv-empty">{emptyText}</p>
    ) : (
      <ul className="adv-list">
        {items.map((a) => (
          <li key={a.name}>
            <strong>{a.name}</strong>
            {a.cost != null && <span className="adv-cost"> · {a.cost} pts</span>}
            <br />
            {a.reason}
          </li>
        ))}
      </ul>
    );

  return (
    <section className="panel advisor-panel">
      <div className="panel-title">
        Advisor
        {advice && (
          <span className="atlas-zone">
            {advice.grounding === "wiki" ? "wiki-grounded" : "from memory"}
          </span>
        )}
      </div>

      <div className="adv-controls">
        {TRIO_LABELS.map((label, i) => (
          <div className="adv-field" key={label}>
            <label htmlFor={`adv-cls-${i}`}>{label}</label>
            <select
              id={`adv-cls-${i}`}
              value={trio[i] ?? ""}
              onChange={(e) => setTrioAt(i, e.target.value)}
            >
              <option value="">—</option>
              {CLASSES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        ))}
        <div className="adv-field">
          <label htmlFor="adv-aa">AA points</label>
          <input
            id="adv-aa"
            type="number"
            min={0}
            placeholder="?"
            value={aaDraft}
            onChange={(e) => setAaDraft(e.target.value)}
            onBlur={() => numberPatch(aaDraft, "aa_available")}
            onKeyDown={(e) => e.key === "Enter" && numberPatch(aaDraft, "aa_available")}
          />
        </div>
        <div className="adv-field">
          <label htmlFor="adv-slots">Spell slots</label>
          <input
            id="adv-slots"
            type="number"
            min={0}
            placeholder="?"
            value={slotsDraft}
            onChange={(e) => setSlotsDraft(e.target.value)}
            onBlur={() => numberPatch(slotsDraft, "spell_slots")}
            onKeyDown={(e) => e.key === "Enter" && numberPatch(slotsDraft, "spell_slots")}
          />
        </div>
        <div className="adv-field">
          <label htmlFor="adv-pet-slots" title="Your pet's equipment slot count (varies by class) — the gear consult builds it a loadout from your spare bags/bank items">Pet slots</label>
          <input
            id="adv-pet-slots"
            type="number"
            min={0}
            placeholder="0"
            value={petSlotsDraft}
            onChange={(e) => setPetSlotsDraft(e.target.value)}
            onBlur={() => numberPatch(petSlotsDraft, "pet_slots")}
            onKeyDown={(e) => e.key === "Enter" && numberPatch(petSlotsDraft, "pet_slots")}
          />
        </div>
        <div className="adv-field">
          <label htmlFor="adv-pet-class" title="Your pet's equip class(es) — most pets are Warrior; some have a second like WAR/RNG. Gear the pet can wear is filtered by this.">Pet class</label>
          <input
            id="adv-pet-class"
            type="text"
            placeholder="Warrior"
            value={petClassDraft}
            onChange={(e) => setPetClassDraft(e.target.value)}
            onBlur={() => patch({ pet_classes: petClassDraft.trim() || null })}
            onKeyDown={(e) => e.key === "Enter" && patch({ pet_classes: petClassDraft.trim() || null })}
          />
        </div>
        <div className="adv-field">
          <label htmlFor="adv-llm">Counsel model</label>
          <select
            id="adv-llm"
            value={llm?.active.provider ?? "lmstudio"}
            onChange={(e) => switchLlm(e.target.value)}
            title="Local = LM Studio on this machine; OpenAI = frontier model via your API key in .env"
          >
            {(llm?.options ?? [{ provider: "lmstudio", model: "", label: "Local" }]).map((o) => (
              <option key={o.provider} value={o.provider}>{o.label}</option>
            ))}
          </select>
        </div>
        {(llm?.active.provider === "openai" || llm?.active.provider === "custom") && (
          <div className="adv-field">
            <label htmlFor="adv-llm-model">
              {llm.active.provider === "openai" ? "OpenAI model" : "Custom model"}
            </label>
            <input
              id="adv-llm-model"
              type="text"
              value={llmModelDraft}
              placeholder={llm.active.provider === "openai" ? "o3" : "model id"}
              onChange={(e) => setLlmModelDraft(e.target.value)}
              onBlur={() =>
                llmModelDraft.trim() && switchLlm(llm.active.provider, llmModelDraft.trim())
              }
              onKeyDown={(e) =>
                e.key === "Enter" && llmModelDraft.trim() && switchLlm(llm.active.provider, llmModelDraft.trim())
              }
            />
          </div>
        )}
        {llm?.active.provider === "openai" && !llm.openai_key_set && (
          <span className="adv-llm-warn" role="alert">
            No OPENAI_API_KEY in .env — consults will fall back to local data. Paste the key, restart the backend.
          </span>
        )}
        <button className="adv-consult" onClick={() => consult(true)} disabled={loading}>
          {loading ? "Consulting…" : "Consult"}
        </button>
      </div>

      <div className="adv-sync">
        <span data-ok={!!book?.available}>
          {book?.available
            ? `spellbook: ${book.castable?.length ?? 0} spells · ${book.age_hours}h old`
            : "spellbook: none — type /outputfile spellbook in-game"}
        </span>
        <span data-ok={!!ownedAAs?.available}>
          {ownedAAs?.available
            ? `AAs: ${ownedAAs.aas.length} synced`
            : "AAs: unsynced — type /alternateadv list in-game"}
        </span>
        {exports && ["missingspells", "inventory", "achievements"].map((k) => (
          <span key={k} data-ok={!!exports[k]?.found}>
            {exports[k]?.found
              ? `${k === "missingspells" ? "missing" : k.slice(0, 4)}: ${exports[k]!.age_hours}h`
              : `${k === "missingspells" ? "missing" : k.slice(0, 4)}: —`}
          </span>
        ))}
        <button
          type="button"
          className="adv-rescan"
          onClick={checkExports}
          disabled={checking}
          title="Scan the game folder for fresh /outputfile exports (run your macro first)"
        >
          {checking ? "checking…" : "check exports"}
        </button>
        <button
          type="button"
          className="adv-rescan"
          onClick={rescanAAs}
          disabled={rescanning}
          title="Deep-scan the whole log for the most recent /alternateadv list output"
        >
          {rescanning ? "scanning…" : "rescan log"}
        </button>
      </div>
      {scanResult && (
        <div className="adv-scan-result" data-ok={scanResult.ok} role="status">
          {scanResult.text}
        </div>
      )}

      <div className="advisor-scroll">
        {error && <p className="adv-empty">{error}</p>}
        {!advice && !error && (
          <p className="adv-empty">
            {loading
              ? "Consulting the archives… (wiki + local model, this can take a moment)"
              : "No counsel yet — press Consult."}
          </p>
        )}
        {advice && (
          <>
            {advice.stale && (
              <div className="adv-stale">
                Saved counsel from {advice.generated?.replace("T", " ") ?? "earlier"} — your
                level, zone, or exports have changed since. Consult to refresh.
              </div>
            )}
            {advice.note && <div className="adv-note">{advice.note}</div>}

            {advice.loadout.length + advice.nice_to_have.length > 0 && (
              <div className="adv-section">
                <h3>
                  Memorize now
                  {snap?.spell_slots != null &&
                    ` — ${advice.loadout.length}/${snap.spell_slots} slots filled`}
                  <button
                    type="button"
                    className="adv-rescan adv-gear-btn"
                    onClick={() => writeSpellSet("loadout")}
                    title={'Write these picks as an in-game spell set ("companion") — then /memspellset companion loads the whole bar'}
                  >
                    write in-game spell set
                  </button>
                  <span className="adv-pick-count">
                    {Object.values(pickSel).filter(Boolean).length}/14 picked · gems auto-ordered: DD, DoT, AoE, heals@8, utility, pets
                  </span>
                </h3>
                {([
                  ["Must have", advice.must_have, 0],
                  ["Should have", advice.should_have, advice.must_have.length],
                  ["Nice to have — extra alternatives, pick and choose",
                   advice.nice_to_have, -1],
                ] as [string, typeof advice.loadout, number][]).map(
                  ([label, list, offset]) =>
                    list.length > 0 && (
                      <div key={label}>
                        <div className="adv-sub" style={{ marginTop: 8 }}>{label}</div>
                        <table className="adv-table">
                          <tbody>
                            {list.map((s, i) => (
                              <tr key={`${s.cls}-${s.name}`}>
                                <td className="adv-pick">
                                  <input
                                    type="checkbox"
                                    checked={pickSel[s.name] ?? false}
                                    disabled={
                                      !(pickSel[s.name] ?? false) &&
                                      Object.values(pickSel).filter(Boolean).length >= 14
                                    }
                                    onChange={(e) =>
                                      setPickSel((p) => {
                                        const picked = Object.values(p).filter(Boolean).length;
                                        if (e.target.checked && picked >= 14) return p;
                                        return { ...p, [s.name]: e.target.checked };
                                      })
                                    }
                                    title="Include in the written spell set (max 14)"
                                  />
                                </td>
                                <td className="adv-pri">
                                  {offset >= 0 ? offset + i + 1 : `·`}
                                </td>
                                <td>
                                  <strong>{s.name}</strong>
                                  {s.level != null && (
                                    <span className="adv-cls"> (L{s.level})</span>
                                  )}
                                </td>
                                <td className="adv-cls">{s.cls}</td>
                                <td className="adv-why">{s.reason}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ),
                )}
              </div>
            )}

            {advice.prebuffs.length > 0 && (
              <div className="adv-section">
                <h3>
                  Pre-buffs — cast, then swap the slot
                  <button
                    type="button"
                    className="adv-rescan adv-gear-btn"
                    onClick={() => writeSpellSet("prebuffs")}
                    title={'Write the pre-buffs as an in-game spell set ("prebuffs", permanent buffs first) — /memspellset prebuffs, buff up, then /memspellset companion for combat'}
                  >
                    write pre-buff set
                  </button>
                </h3>
                <ul className="adv-list">
                  {advice.prebuffs.map((s) => (
                    <li key={`${s.cls}-${s.name}`}>
                      <strong>{s.name}</strong>
                      {s.level != null && <span className="adv-cls"> (L{s.level})</span>}{" "}
                      <span className="adv-cls">({s.cls})</span>
                      <br />
                      {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {advice.replace.length > 0 && (
              <div className="adv-section">
                <h3>Upgrade warnings</h3>
                <ul className="adv-list adv-replace">
                  {advice.replace.map((r) => (
                    <li key={r.using}>
                      <strong>{r.using}</strong> → <strong>{r.upgrade}</strong>
                      <br />
                      {r.why}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(advice.purchase?.length ?? 0) > 0 && (
              <div className="adv-section">
                <h3>Vendor shopping list</h3>
                <p className="adv-purchase">
                  {advice.purchase!
                    .map((p) => `${p.name} (L${p.level}${p.now ? "" : " — buy ahead"})`)
                    .join(" · ")}
                </p>
                <p className="adv-purchase-note">
                  Missing from your spellbook — spells can be bought and scribed
                  before you reach their level.
                </p>
              </div>
            )}

            {(advice.aa_now.length > 0 || advice.aa_save.length > 0) && (
              <div className="adv-section">
                <h3>
                  AA counsel
                  {snap?.aa_available != null && ` — ${snap.aa_available} unspent`}
                </h3>
                <div className="adv-cols">
                  <div>
                    <div className="adv-sub">Unlock now</div>
                    {aaBlock(advice.aa_now, "Nothing affordable stands out.")}
                  </div>
                  <div>
                    <div className="adv-sub">Save for</div>
                    {aaBlock(advice.aa_save, "No savings goal right now.")}
                  </div>
                </div>
              </div>
            )}

            {advice.horizon.length > 0 && (
              <div className="adv-section">
                <h3>Next two levels</h3>
                <ul className="adv-list">
                  {advice.horizon.map((h) => (
                    <li key={`${h.cls}-${h.name}`}>
                      <span className="adv-lvl">L{h.level ?? "?"}</span>
                      <strong>{h.name}</strong> <span className="adv-cls">({h.cls})</span>
                      <br />
                      {h.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {advice.locations.length > 0 && (
              <div className="adv-section">
                <h3>Where to hunt</h3>
                <ul className="adv-list">
                  {advice.locations.map((l) => (
                    <li key={l.zone}>
                      <strong>{l.zone}</strong>
                      <br />
                      {l.why}
                      {l.notable && (
                        <>
                          <br />
                          <em className="adv-notable">Notable: {l.notable}</em>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {hunting && hunting.level != null && hunting.zones.length > 0 && (
              <div className="adv-section">
                <h3>Leveling chart</h3>
                <HuntChart
                  data={hunting}
                  picked={(advice?.locations ?? []).map((l) => l.zone)}
                />
              </div>
            )}

            <div className="adv-section">
              <h3>
                Equipment
                <button
                  type="button"
                  className="adv-rescan adv-gear-btn"
                  onClick={() => consultGear(true)}
                  disabled={gearLoading}
                  title="Best owned item per slot + farming targets (first run mines item stats from the wiki — slow)"
                >
                  {gearLoading ? "consulting…" : gear ? "re-consult gear" : "consult gear"}
                </button>
              </h3>
              {gear?.stale && (
                <div className="adv-stale">
                  Saved gear counsel from {gear.generated?.replace("T", " ") ?? "earlier"} —
                  context changed since. Re-consult to refresh.
                </div>
              )}
              {gear?.note && <div className="adv-note">{gear.note}</div>}
              {gear && gear.slots.length > 0 && (
                <table className="adv-table">
                  <thead>
                    <tr>
                      <th scope="col">Slot</th>
                      <th scope="col">Now</th>
                      <th scope="col">Use</th>
                      <th scope="col">Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gear.slots.map((s) => (
                      <tr
                        key={s.slot + (s.recommend ?? "")}
                        data-dim={
                          !s.why ||
                          s.why.startsWith("keep —") ||
                          s.why.startsWith("empty —") ||
                          (s.recommend != null && s.recommend === s.current)
                            ? "1"
                            : undefined
                        }
                      >
                        <td className="adv-cls">{s.slot}</td>
                        <td>{s.current || "—"}</td>
                        <td>
                          <strong>{s.recommend ?? "—"}</strong>
                          {s.where && (
                            <span className="adv-cls"> ({s.where})</span>
                          )}
                        </td>
                        <td className="adv-why">{s.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {gear && gear.exaltations.length > 0 && (
                <>
                  <div className="adv-sub" style={{ marginTop: 10 }}>
                    Exaltations you own (can-socket-into is computed from the
                    class/slot rules; the actual move is done in-game)
                  </div>
                  <ul className="adv-list">
                    {gear.exaltations.map((x) => (
                      <li key={x.name}>
                        <strong>{x.name}</strong>
                        {x.where && <span className="adv-cls"> — {x.where}</span>}
                        <br />
                        {x.why}
                        {x.move_to && (
                          <>
                            <br />
                            <span className="adv-cls">can socket into: {x.move_to}</span>
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {snap?.pet_inventory && Object.keys(snap.pet_inventory).length > 0 && (
                <>
                  <div className="adv-sub" style={{ marginTop: 10 }}>
                    Pet currently equipped (from /pet inventory check)
                  </div>
                  <table className="adv-table">
                    <tbody>
                      {Object.entries(snap.pet_inventory).map(([slot, item]) => (
                        <tr key={slot}>
                          <td className="adv-cls">{slot}</td>
                          <td>{item}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              {gear && (gear.pet_gear?.length ?? 0) > 0 && (
                <>
                  <div className="adv-sub" style={{ marginTop: 10 }}>
                    Suggested pet swaps — hand these to the pet; lost if it
                    dies or is re-summoned
                  </div>
                  <ul className="adv-list">
                    {gear.pet_gear!.map((p) => (
                      <li key={p.item}>
                        <strong>{p.item}</strong>
                        {p.slot && <span className="adv-cls"> — {p.slot}</span>}
                        {p.where && <span className="adv-cls"> ({p.where})</span>}
                        <br />
                        {p.why}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {gear && gear.farm.length > 0 && (
                <>
                  <div className="adv-sub" style={{ marginTop: 10 }}>Where to farm upgrades</div>
                  <ul className="adv-list">
                    {gear.farm.map((f) => (
                      <li key={f.item}>
                        <strong>{f.item}</strong>
                        {f.slot && <span className="adv-cls"> ({f.slot})</span>}
                        {f.zone && (
                          <>
                            {" — "}
                            {f.zone}
                            {f.source ? ` · ${f.source}` : ""}
                          </>
                        )}
                        <br />
                        {f.why}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>

            {advice.class_notes.length > 0 && (
              <div className="adv-section">
                <h3>Class notes</h3>
                <ul className="adv-list">
                  {advice.class_notes.map((n) => (
                    <li key={n.topic}>
                      <strong>{n.topic}</strong>
                      <br />
                      {n.advice}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="adv-foot">
              <span>
                {advice.source === "llm"
                  ? advice.grounding === "wiki"
                    ? "Grounded in the EQL wiki — verify costs in-game."
                    : "From model memory (wiki unreachable) — treat names as approximate."
                  : "Built-in notes only — the LLM is offline."}
              </span>
              <span>{new Date(advice.generated).toLocaleTimeString()}</span>
            </div>
          </>
        )}
      </div>
    </section>
  );
});