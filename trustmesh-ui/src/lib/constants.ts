// ── Capsule Types ──────────────────────────────────────────────────────────────

export const CAPSULE_TYPES = [
  "memory", "skill", "procedure", "schedule", "preference", "contact",
] as const;

export type CapsuleType = typeof CAPSULE_TYPES[number];

export const CAPSULE_TYPE_EMOJIS: Record<string, string> = {
  memory: "💭", skill: "⚡", procedure: "📋",
  schedule: "📅", preference: "♥", contact: "👤",
};

export const CAPSULE_TYPE_COLORS: Record<string, string> = {
  memory: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  skill: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  procedure: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  schedule: "bg-cyan-500/15 text-cyan-400 border-cyan-500/20",
  preference: "bg-pink-500/15 text-pink-400 border-pink-500/20",
  contact: "bg-green-500/15 text-green-400 border-green-500/20",
};

// ── Capsule Categories ─────────────────────────────────────────────────────────

export const CAPSULE_CATEGORIES = [
  "health", "home", "work", "personal", "family", "general",
] as const;

export const CATEGORY_ICONS: Record<string, string> = {
  health: "❤️", family: "🏠", work: "💼",
  personal: "👤", general: "⚡", home: "🏡", test: "🧪",
  system: "⚙️", "system.metrics": "📈", data: "📊",
};

// ── Sharing Tiers ──────────────────────────────────────────────────────────────

export const TIER_FILTER_LABELS: Record<string, string> = {
  public: "everyone",
  network: "shared",
  private: "only me",
};

// ── Connection Relationship Types ──────────────────────────────────────────────

export const RELATIONSHIP_TYPES = [
  "family", "friend", "work", "healthcare", "neighbor", "emergency", "other",
] as const;
