"use client";

import { useEffect, useRef, useState } from "react";
import type { LedgerRow } from "@/lib/types";

/** Events that are ambient-world noise, not the player's own combat. */
const OTHER_TYPES = new Set(["other_death", "non_melee"]);

/** kind → left-rule + value color (see globals.css [data-kind]) */
function classify(r: LedgerRow): {
  kind: string;
  text: string;
  value?: string;
  divider?: boolean;
} {
  switch (r.type) {
    case "zone":
      return { kind: "milestone", text: `Entered ${r.zone}`, divider: true };
    case "melee_out":
      return { kind: "out", text: `You ${r.verb} ${r.target}`, value: `${r.damage}${r.crit ? " ✦" : ""}` };
    case "spell_out":
      return { kind: "out", text: `${r.spell} → ${r.target}`, value: `${r.damage}${r.crit ? " ✦" : ""}` };
    case "melee_in":
      return { kind: "in", text: `${r.attacker} ${r.verb}s YOU`, value: `−${r.damage}${r.crit ? " ✦" : ""}` };
    case "spell_in":
      return { kind: "in", text: `${r.spell} from ${r.attacker}`, value: `−${r.damage}${r.crit ? " ✦" : ""}` };
    case "ds_out":
      return { kind: "out", text: `Damage shield sears ${r.target}`, value: `${r.damage}` };
    case "non_melee":
      return { kind: "dim", text: `${r.target} hit by non-melee`, value: `${r.damage}` };
    case "heal_in":
      return { kind: "heal", text: "Healed", value: `+${r.amount}` };
    case "heal_out":
      return { kind: "heal", text: `Healed ${r.target} (${r.spell})`, value: `+${r.amount}` };
    case "cast":
      return { kind: "cast", text: `Casting ${r.spell}…` };
    case "interrupt":
      return { kind: "cast", text: "Spell interrupted" };
    case "fizzle":
      return { kind: "cast", text: "Fizzle!" };
    case "kill":
      return { kind: "milestone", text: `Slain: ${r.target}` };
    case "death":
      return { kind: "in", text: `YOU DIED — ${r.killer}` };
    case "other_death":
      return { kind: "dim", text: `${r.victim} slain by ${r.killer}` };
    case "dot_out":
      return { kind: "out", text: `${r.spell} gnaws ${r.target}`, value: `${r.damage}${r.crit ? " ✦" : ""}` };
    case "miss_out":
      return { kind: "dim", text: `You miss ${r.target}` };
    case "miss_in":
      return { kind: "dim", text: `${r.attacker} misses you` };
    case "coin":
      return {
        kind: "milestone",
        text: r.vendor
          ? `Sold ${r.item} to ${r.vendor} — +${r.amount}`
          : r.split
            ? `Split share +${r.amount}`
            : `+${r.amount}`,
      };
    case "resist":
      return {
        kind: "cast",
        text:
          r.direction === "in"
            ? `You resist ${r.spell}`
            : `${r.target ?? "Target"} resisted ${r.spell}`,
      };
    case "faction":
      return {
        kind: "dim",
        text: r.capped ? `Faction maxed (${r.capped}): ${r.faction}` : `Faction: ${r.faction}`,
        value: r.capped ? undefined : `${Number(r.delta) > 0 ? "+" : ""}${r.delta}`,
      };
    case "tell":
      return { kind: "cast", text: `${r.sender} tells you: ${r.text}` };
    case "summoned":
      return { kind: "in", text: "YOU HAVE BEEN SUMMONED" };
    case "stunned":
      return { kind: "dim", text: "Stunned" };
    case "mend":
      return { kind: "heal", text: "Mend" };
    case "cooldown_readout":
      return { kind: "dim", text: `${r.name} ready in ${r.seconds}s` };
    case "buff_fade":
      return {
        kind: "dim",
        text: r.target ? `${r.spell} broke on ${r.target}` : `${r.spell} faded`,
      };
    case "rune":
      return { kind: "heal", text: "Rune absorbs", value: `${r.amount}` };
    case "self_hurt":
      return { kind: "in", text: "You hurt yourself", value: `−${r.damage}` };
    case "roll":
      return {
        kind: "milestone",
        text: r.who ? `${r.who} rolls ${r.value} (${r.lo}-${r.hi})` : `Random roll ${r.lo}-${r.hi}`,
      };
    case "merge":
      return { kind: "milestone", text: `Merged → ${r.item}` };
    case "destroyed":
      return { kind: "dim", text: `Destroyed ${Number(r.count) > 1 ? `${r.count}× ` : ""}${r.item}` };
    case "exp":
      return {
        kind: "milestone",
        text: "Experience gained",
        value: r.percent ? `+${r.percent}%` : undefined,
      };
    case "level":
      return { kind: "milestone", text: `LEVEL ${r.level}!` };
    case "aa":
      return { kind: "milestone", text: "Ability point earned" };
    case "skill":
      return { kind: "dim", text: `${r.skill} → ${r.value}` };
    case "loot":
      return {
        kind: "milestone",
        text: r.upgraded_to
          ? `Looted ${r.item} → ${r.upgraded_to}`
          : `Looted ${r.item}`,
      };

    default:
      return { kind: "dim", text: String(r.raw ?? r.type) };
  }
}

function timeOf(ts: string): string {
  const d = new Date(ts);
  return isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString("en-GB", { hour12: false });
}

const VISIBLE_ROWS = 50;

export function WarLedger({ rows: allRows }: { rows: LedgerRow[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [mineOnly, setMineOnly] = useState(true);
  const [open, setOpen] = useState(true);
  useEffect(() => {
    setOpen(localStorage.getItem("eql.ledgerOpen") !== "0");
  }, []);
  const toggleOpen = () => {
    setOpen((v) => {
      localStorage.setItem("eql.ledgerOpen", v ? "0" : "1");
      return !v;
    });
  };

  // Filter, keep only the most recent 50, newest first (top of the list).
  const filtered = mineOnly
    ? allRows.filter((r) => !OTHER_TYPES.has(r.type))
    : allRows;
  const rows = filtered.slice(-VISIBLE_ROWS).reverse();

  // Newest rows arrive at the TOP — stay pinned there unless the user
  // scrolled down to read older entries.
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinned.current = el.scrollTop < 40;
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinned.current) el.scrollTop = 0;
  }, [rows]);

  return (
    <section className="panel ledger-panel" data-collapsed={open ? undefined : "1"}>
      <div className="panel-title">
        War Ledger
        <label className="ledger-filter">
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(e) => setMineOnly(e.target.checked)}
          />
          Mine only
        </label>
        <button
          type="button"
          className="ledger-collapse"
          onClick={toggleOpen}
          title={open ? "Collapse the ledger to just this bar" : "Expand the ledger"}
        >
          {open ? "▾ hide" : "▸ show"}
        </button>
      </div>
      {open && (
      <div className="panel-body" ref={scrollRef} onScroll={onScroll}>
        {rows.length === 0 ? (
          <p className="ledger-empty">
            Blank ledger — it fills as you fight. Events stream in the moment
            your log file moves.
          </p>
        ) : (
          <ul className="ledger">
            {rows.map((r, i) => {
              const c = classify(r);
              if (c.divider) {
                return (
                  <li key={r._id ?? i} className="ledger-divider">
                    {c.text}
                  </li>
                );
              }
              return (
                <li key={r._id ?? i} className="ledger-row" data-kind={c.kind}>
                  <span className="ledger-time">{timeOf(r.ts)}</span>
                  <span className="ledger-text">{c.text}</span>
                  <span className="ledger-value">{c.value ?? ""}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      )}
    </section>
  );
}
