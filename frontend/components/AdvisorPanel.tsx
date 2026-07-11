"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import type { Advice, OwnedAAsInfo, Snapshot, SpellbookInfo } from "@/lib/types";

const CLASSES = [
  "Warrior", "Cleric", "Paladin", "Ranger", "Shadow Knight", "Druid",
  "Monk", "Bard", "Rogue", "Shaman", "Necromancer", "Wizard",
  "Magician", "Enchanter", "Beastlord", "Berserker",
];

const TRIO_LABELS = ["Primary", "Secondary", "Tertiary"] as const;

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
  const [book, setBook] = useState<SpellbookInfo | null>(null);
  const [ownedAAs, setOwnedAAs] = useState<OwnedAAsInfo | null>(null);

  const trio = (snap?.class_str ?? "").split("/").map((s) => s.trim());

  useEffect(() => {
    setAaDraft(snap?.aa_available == null ? "" : String(snap.aa_available));
  }, [snap?.aa_available]);
  useEffect(() => {
    setSlotsDraft(snap?.spell_slots == null ? "" : String(snap.spell_slots));
  }, [snap?.spell_slots]);

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

  const numberPatch = (draft: string, field: "aa_available" | "spell_slots") => {
    if (draft === "") return;
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 0) patch({ [field]: Math.floor(n) });
  };

  const [rescanning, setRescanning] = useState(false);
  const rescanAAs = async () => {
    setRescanning(true);
    try {
      await apiSend("/api/aas/rescan", {});
      setOwnedAAs(await apiGet<OwnedAAsInfo>("/api/aas"));
    } catch {
      /* backend offline */
    }
    setRescanning(false);
  };

  const consult = useCallback(async (refresh: boolean) => {
    setLoading(true);
    setError(null);
    try {
      setAdvice(await apiGet<Advice>(`/api/advisor${refresh ? "?refresh=1" : ""}`));
    } catch {
      setError("The advisor is unreachable — is the backend running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    consult(false);
  }, [consult]);

  // owned-state sync chips (refresh alongside every consult)
  useEffect(() => {
    apiGet<SpellbookInfo>("/api/spellbook").then(setBook).catch(() => {});
    apiGet<OwnedAAsInfo>("/api/aas").then(setOwnedAAs).catch(() => {});
  }, [advice]);

  // auto-consult when fresh owned-state lands while the tab is open:
  // /alternateadv list output in the log, or a new /outputfile spellbook
  // (the snapshot polls the export file's timestamp).
  const aaSynced = snap?.owned_aas?.synced ?? null;
  const bookSynced = snap?.spellbook?.updated ?? null;
  const syncStamp = `${aaSynced}|${bookSynced}`;
  const lastSyncRef = useRef<string | null>(null);
  useEffect(() => {
    if (lastSyncRef.current === null) {
      lastSyncRef.current = syncStamp; // state from before the tab opened
      return;
    }
    if (lastSyncRef.current !== syncStamp) {
      lastSyncRef.current = syncStamp;
      consult(true);
    }
  }, [syncStamp, consult]);

  const aaBlock = (items: Advice["aa_now"], emptyText: string) =>
    items.length === 0 ? (
      <p className="adv-empty">{emptyText}</p>
    ) : (
      <ul className="adv-list">
        {items.map((a) => (
          <li key={a.name}>
            <strong>{a.name}</strong>
            {a.cost != null && <span className="adv-cost">{a.cost} pts</span>}
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
            {advice.note && <div className="adv-note">{advice.note}</div>}

            {advice.loadout.length > 0 && (
              <div className="adv-section">
                <h3>
                  Memorize now
                  {snap?.spell_slots != null && ` — ${snap.spell_slots} slots`}
                </h3>
                <table className="adv-table">
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Spell</th>
                      <th scope="col">Class</th>
                      <th scope="col">Job</th>
                    </tr>
                  </thead>
                  <tbody>
                    {advice.loadout.map((s, i) => (
                      <tr key={`${s.cls}-${s.name}`}>
                        <td className="adv-pri">{i + 1}</td>
                        <td><strong>{s.name}</strong></td>
                        <td className="adv-cls">{s.cls}</td>
                        <td className="adv-why">{s.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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