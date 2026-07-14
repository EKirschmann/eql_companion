export interface SessionStats {
  damage_dealt: number;
  damage_taken: number;
  healing_received: number;
  healing_done: number;
  kills: number;
  deaths: number;
  xp_ticks: number;
  xp_percent: number;
  aa_points: number;
  skill_ups: number;
  hit_rate: number;
  loots: string[];
}

export interface EncounterAbility {
  name: string;
  kind: "melee" | "spell" | "dot" | "pet" | "heal";
  hits: number;
  total: number;
  avg: number;
  dps: number;
}

export interface EncounterFoe {
  name: string;
  damage: number;
  taken: number;
  slain: boolean;
}

export interface AbilitySummary {
  encounters: number;
  duration: number;
  abilities: EncounterAbility[];
  heals: EncounterAbility[];
}

export interface DeathRecapHit {
  attacker: string | null;
  damage: number;
  source: string;
  ts: string;
}

export interface DeathRecap {
  ts: string;
  killer: string;
  total: number;
  hits: DeathRecapHit[];
}

export interface MobStat {
  name: string;
  kills: number;
  xp_percent: number;
  loots: string[];
}

export interface EncounterAlly {
  name: string;
  damage: number;
  dps: number;
  level: number | null;
  classes: string | null;
}

export interface Encounter {
  in_hits?: number;
  defense?: Record<string, number>;
  active: boolean;
  started: string;
  allies: EncounterAlly[];
  heals: EncounterAbility[];
  total_healing: number;
  target: string | null;
  foes: EncounterFoe[];
  duration: number;
  total_damage: number;
  damage_taken: number;
  dps: number;
  abilities: EncounterAbility[];
}

export interface Position {
  x: number;
  y: number;
  z: number;
  ts: string;
}

export interface MapPoint {
  x: number;
  y: number;
  size: number;
  label: string;
  exit: boolean;
}

export interface MapData {
  available: boolean;
  zone: string | null;
  reason?: string;
  file?: string;
  /** [x1, y1, x2, y2, r, g, b] in map space (plot /loc at (-x, -y)) */
  lines?: number[][];
  points?: MapPoint[];
  bounds?: { min_x: number; min_y: number; max_x: number; max_y: number };
}

export interface GeometryFloor {
  z: number;
  /** wall segments: [x1, y1, x2, y2] in chart plot coords */
  walls: number[][];
  /** floor triangles: [x1, y1, x2, y2, x3, y3] */
  tris: number[][];
}

export interface ZoneGeometry {
  available: boolean;
  zone: string | null;
  reason?: string;
  bounds?: { min_x: number; min_y: number; max_x: number; max_y: number };
  floors?: GeometryFloor[];
  wall_count?: number;
  tri_count?: number;
}

export interface GeometrySubmesh {
  /** exported PNG filename, or null for untextured surfaces */
  tex: string | null;
  masked: boolean;
  /** flat vertex positions (9 per triangle, WLD coords, z up) */
  pos: number[];
  /** flat uv pairs (6 per triangle) */
  uv: number[];
}

export interface ZoneGeometry3D {
  available: boolean;
  zone: string | null;
  reason?: string;
  bounds?: {
    min_x: number; max_x: number;
    min_y: number; max_y: number;
    min_z: number; max_z: number;
  };
  layers?: {
    floors: GeometrySubmesh[];
    ramps: GeometrySubmesh[];
    walls: GeometrySubmesh[];
    props: GeometrySubmesh[];
  };
  counts?: Record<string, number>;
}

export interface Snapshot {
  name: string;
  server: string;
  level: number | null;
  class_str: string | null;
  race: string | null;
  playstyle: string | null;
  aa_available: number | null;
  spell_slots: number | null;
  loadout_hint: string | null;
  owned_aas: { distinct: number; ranks: number; synced: string | null };
  spellbook: { file: string; updated: string; age_hours: number; count: number } | null;
  sync_hints: { command: string; reason: string }[];
  last_death: DeathRecap | null;
  mob_stats: MobStat[];
  zone: string | null;
  in_combat: boolean;
  dps: number;
  session_max_dps: number;
  last_target: string | null;
  position: Position | null;
  encounter: Encounter | null;
  encounters: Encounter[];
  ability_summary: AbilitySummary | null;
  session: SessionStats;
  updated: string;
}

/** One parsed log event; fields beyond these vary by `type`. */
export interface LedgerRow {
  type: string;
  ts: string;
  raw: string;
  live?: boolean;
  /** Client-side monotonic id, stamped on receipt — stable React key. */
  _id?: number;
  [key: string]: unknown;
}

export interface SuggestionItem {
  name: string;
  category: string;
  priority: number;
  reason: string;
  synergies: string[];
  source: string;
}

export interface Suggestions {
  spells: SuggestionItem[];
  aas: SuggestionItem[];
  zones: SuggestionItem[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  suggestions?: Suggestions;
}

export type WsMessage =
  | { type: "hello"; data: Snapshot }
  | { type: "state"; data: Snapshot }
  | { type: "event"; data: LedgerRow }
  | { type: "events"; data: LedgerRow[] }; // batched (~150ms) frames

export interface AdvisorLoadout {
  name: string;
  cls: string;
  reason: string;
  level?: number | null;
}

export interface AdvisorReplace {
  using: string;
  upgrade: string;
  why: string;
}

export interface AdvisorAA {
  name: string;
  cost: number | null;
  reason: string;
}

export interface AdvisorHorizon {
  level: number | null;
  cls: string;
  name: string;
  reason: string;
}

export interface AdvisorLocation {
  zone: string;
  why: string;
  notable: string;
}

export interface AdvisorClassNote {
  topic: string;
  advice: string;
}

export interface SpellbookInfo {
  available: boolean;
  reason?: string;
  file?: string;
  updated?: string;
  age_hours?: number;
  castable?: { level: number; name: string }[];
  other_loadouts?: string[];
}

export type ExportsStatus = Record<string, {
  found: boolean;
  file?: string;
  updated?: string;
  age_hours?: number;
  count?: number | null;
}>;

export interface OwnedAAsInfo {
  available: boolean;
  synced: string | null;
  aas: { name: string; id: number; ranks: number; cost: number | null; desc: string | null }[];
}

export interface GearSlot {
  slot: string;
  current: string | null;
  recommend: string | null;
  why: string;
  where?: string | null;
}

export interface GearFarm {
  item: string;
  slot: string | null;
  zone: string | null;
  source: string | null;
  why: string;
}

export interface GearExalt {
  name: string;
  move_to: string | null;
  why: string;
}

export interface GearAdvice {
  source: "llm" | "builtin";
  generated: string;
  note: string | null;
  context: Record<string, unknown>;
  slots: GearSlot[];
  farm: GearFarm[];
  exaltations: GearExalt[];
  unknown: string[];
}

export interface Advice {
  purchase?: PurchaseItem[];
  source: "llm" | "builtin";
  grounding: "wiki" | "memory";
  generated: string;
  note: string | null;
  context: {
    classes: string | null;
    level: number | null;
    playstyle: string | null;
    zone: string | null;
    aa_available: number | null;
    spell_slots: number | null;
    spellbook_file: string | null;
    spellbook_age_hours: number | null;
    spellbook_count: number | null;
  };
  loadout: AdvisorLoadout[];
  must_have: AdvisorLoadout[];
  should_have: AdvisorLoadout[];
  nice_to_have: AdvisorLoadout[];
  prebuffs: AdvisorLoadout[];
  replace: AdvisorReplace[];
  aa_now: AdvisorAA[];
  aa_save: AdvisorAA[];
  horizon: AdvisorHorizon[];
  locations: AdvisorLocation[];
  class_notes: AdvisorClassNote[];
}

export interface PurchaseItem {
  name: string;
  level: number;
  now: boolean;
}

export interface HuntingZone {
  zone: string;
  band: string;
  marks: number[];
  levels: number[];
  at_level: boolean;
}

export interface HuntingData {
  level: number | null;
  zones: HuntingZone[];
}

export interface LlmOption {
  provider: string;
  model: string;
  label: string;
}

export interface LlmInfo {
  active: { provider: string; model: string };
  options?: LlmOption[];
  openai_key_set: boolean;
}
