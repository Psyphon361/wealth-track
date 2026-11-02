/**
 * One fixed chart colour per asset slug. Colour follows the entity, never its rank.
 * Stepped for the dark card surface (#111114). Ten hues exceed what the data-viz
 * palette validates all-pairs, so legend labels are the secondary encoding.
 */
export const ASSET_COLORS: Record<string, string> = {
  fd: "#2773ee",
  rd: "#878cdd",
  cash: "#1ea381",
  pf: "#728426",
  stock: "#6d48d1",
  mf: "#b51c79",
  nps: "#be79b8",
  bond: "#cb6e60",
  gold: "#b2912e",
  other: "#a34a3d",
};

/** Neutral for the folded "More" slice. */
export const MORE_COLOR = "#898781";

export function assetColor(slug: string): string {
  return ASSET_COLORS[slug] ?? MORE_COLOR;
}
