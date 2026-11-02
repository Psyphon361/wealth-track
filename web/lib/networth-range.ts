type Point = { invested: number; current: number };

/** Change in gain (current − invested) from the first to the last point; null with fewer than 2 points. */
export function rangeGrowth(points: Point[]): number | null {
  if (points.length < 2) return null;
  const first = points[0];
  const last = points[points.length - 1];
  return last.current - last.invested - (first.current - first.invested);
}

/** Y axis domain: min and max over current and invested, padded, lower bound floored at 0. */
export function chartDomain(points: Point[]): [number, number] {
  if (points.length === 0) return [0, 0];
  let min = Infinity;
  let max = -Infinity;
  for (const p of points) {
    min = Math.min(min, p.current, p.invested);
    max = Math.max(max, p.current, p.invested);
  }
  const span = max - min;
  const pad = span === 0 ? Math.abs(max) * 0.02 : span * 0.08;
  return [Math.max(0, min - pad), max + pad];
}
