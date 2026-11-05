export const ANALYTICS_PATH = "/analytics/overview";
export const ANALYTICS_GROWTH_PATH = "/analytics/growth";
export const ANALYTICS_RETURNS_PATH = "/analytics/returns";
export const ANALYTICS_TAX_PATH = "/analytics/tax";
export const ANALYTICS_INFLOWS_PATH = "/analytics/inflows";

/** One fixed colour per allocation class (API class key). Colour follows the class, never its rank. */
export const CLASS_COLORS: Record<string, string> = {
  equity: "#6d48d1",
  debt: "#2773ee",
  hybrid: "#b51c79",
  gold: "#b2912e",
  cash: "#1ea381",
  other: "#a34a3d",
};

const FALLBACK_COLOR = "#898781";

export function classColor(key: string): string {
  return CLASS_COLORS[key] ?? FALLBACK_COLOR;
}

export function pctText(n: number): string {
  return `${n.toFixed(1)}%`;
}
