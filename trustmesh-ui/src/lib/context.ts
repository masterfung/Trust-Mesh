import type { ContextMode } from "./api";

/**
 * Filter items by context mode. DRY utility used across vault, services, and connections pages.
 * "all" shows everything. "work"/"personal" show matching items + "both" items.
 */
export function matchesContext(
  itemContext: string | undefined,
  activeContext: ContextMode,
): boolean {
  if (activeContext === "all") return true;
  const ctx = itemContext || "personal";
  return ctx === activeContext || ctx === "both";
}
