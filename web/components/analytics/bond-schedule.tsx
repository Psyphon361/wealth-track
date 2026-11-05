"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { CardInfo } from "@/components/analytics/card-info";
import { useAnalyticsSection } from "@/components/analytics/use-analytics-section";
import { useCountUp } from "@/components/analytics/use-count-up";
import {
  ALL_BONDS,
  BOND_SCHEDULE_PATH,
  axisLabels,
  axisLayout,
  bucketFy,
  cardLeftBeside,
  combinedNext,
  couponProgress,
  dateTile,
  daysText,
  fyMarkers,
  fyPayoutRows,
  fyPlacements,
  fyShares,
  fyShort,
  hoverSummary,
  maxColumn,
  mergeFy,
  monthBuckets,
  nextBucketIndex,
  nextSubline,
  optionDetail,
  PAYOUT_PAGE,
  payoutPaging,
  payoutStatusText,
  redemptionLabel,
  selectBonds,
  showMoreCount,
  type MonthBucket,
} from "@/lib/bond-schedule";
import { formatDate, formatINR, formatINRWhole } from "@/lib/format";
import { MONEY_COLOR } from "@/lib/growth";
import type { BondSchedule as BondScheduleData, BondScheduleBond } from "@/lib/types";

const TDS_COLOR = "oklch(0.712 0.194 13 / 0.5)";
const PAID_OPACITY = 0.35;
const MAX_DELAY_MS = 700;
/** Space (px) between a hovered month column and the card beside it. */
const CARD_GAP = 8;

/** False on first paint, true one frame later, so CSS transitions play on mount. */
function useGrown(): boolean {
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(raf);
  }, []);
  return grown;
}

/**
 * Floating month summary over the chart. The outer layer glides sideways (its transform is set by
 * the chart); the inner layer fades and scales in and out. Hidden from screen readers: the
 * `role="status"` line carries the same summary.
 */
function HoverCard({
  cardRef,
  bucket,
  multi,
  visible,
}: {
  cardRef: React.RefObject<HTMLDivElement | null>;
  bucket: MonthBucket | null;
  multi: boolean;
  visible: boolean;
}) {
  const s = bucket ? hoverSummary(bucket, multi) : null;
  const amount = useCountUp(s?.amount ?? 0);

  return (
    <>
      <p className="sr-only" role="status">
        {visible && s ? `${s.title}: ${formatINRWhole(s.amount)} ${s.amountLabel}, ${s.status}` : ""}
      </p>
      <div
        ref={cardRef}
        aria-hidden="true"
        className="pointer-events-none absolute top-12 left-0 z-10 w-56 max-w-full transition-transform duration-200 ease-out motion-reduce:transition-none"
      >
        <div
          className={`origin-top rounded-lg border border-border bg-popover p-2.5 text-popover-foreground shadow-md transition-[opacity,transform] duration-150 motion-reduce:transition-none ${visible ? "scale-100 opacity-100" : "scale-95 opacity-0"}`}
        >
          {s && bucket && (
            <div
              key={bucket.key}
              className="flex animate-in flex-col gap-0.5 duration-150 fade-in motion-reduce:animate-none"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13.5px] font-medium">{s.title}</span>
                <span className="text-xs text-muted-foreground">{s.status}</span>
              </div>
              <p className="num text-[18px] leading-7 font-medium">
                {formatINRWhole(amount)}
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                  {s.amountLabel}
                </span>
              </p>
              {s.coupon !== null && (
                <p className="num text-[13.2px] text-muted-foreground">
                  {formatINRWhole(s.coupon)} coupon −{" "}
                  <span className={s.tds > 0 ? "text-amber-300" : undefined}>
                    {formatINRWhole(s.tds)} TDS
                  </span>
                </p>
              )}
              {(s.rows.length > 0 || s.more > 0) && (
                <ul className="mt-1.5 flex flex-col gap-0.5 border-t border-border/50 pt-1.5">
                  {s.rows.map((r) => (
                    <li key={r.key} className="flex items-center justify-between gap-3 text-xs">
                      <span className="min-w-0 truncate text-muted-foreground">{r.label}</span>
                      <span
                        className={`num shrink-0 ${r.key.startsWith("redemption|") ? "text-gain" : ""}`}
                      >
                        {formatINRWhole(r.amount)}
                      </span>
                    </li>
                  ))}
                  {s.more > 0 && <li className="text-xs text-muted-foreground">+{s.more} more</li>}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function Chart({
  buckets,
  nextIdx,
  hover,
  hoverFy,
  grown,
  multi,
  onHover,
}: {
  buckets: MonthBucket[];
  nextIdx: number | null;
  hover: number | null;
  hoverFy: string | null;
  grown: boolean;
  multi: boolean;
  onHover: (i: number | null) => void;
}) {
  const n = buckets.length;
  const layout = axisLayout(n);
  const labels = new Map(axisLabels(buckets, layout.step).map((l) => [l.index, l]));
  const markers = fyMarkers(buckets);
  const placements = fyPlacements(markers, n, layout.slot);
  const max = maxColumn(buckets);
  const wrap = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const wasShown = useRef(false);
  const [last, setLast] = useState(hover);
  if (hover !== null && hover !== last) setLast(hover);
  const shown = hover ?? last;

  useEffect(() => {
    const el = scroller.current;
    if (!el || !layout.scroll || nextIdx === null) return;
    el.scrollLeft = Math.max(0, nextIdx * layout.slot - el.clientWidth / 2 + layout.slot / 2);
  }, [layout.scroll, layout.slot, nextIdx]);

  /** Put the card beside column `idx` (allowing for sideways scroll), flipping sides at the edge. */
  const place = useCallback(
    (idx: number) => {
      const w = wrap.current;
      const s = scroller.current;
      const t = track.current;
      const c = card.current;
      if (!w || !s || !t || !c) return;
      const col = t.offsetWidth / n;
      const barLeft = idx * col - s.scrollLeft;
      const left = cardLeftBeside(barLeft, barLeft + col, c.offsetWidth, w.clientWidth, CARD_GAP);
      c.style.transform = `translateX(${left}px)`;
    },
    [n],
  );

  // First hover jumps into place (it fades in); later moves glide.
  useLayoutEffect(() => {
    if (hover === null) {
      wasShown.current = false;
      return;
    }
    if (card.current) card.current.style.transitionDuration = wasShown.current ? "" : "0ms";
    place(hover);
    wasShown.current = true;
    const onResize = () => place(hover);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [hover, place]);

  // A tapped or focused bar stays pinned until a tap outside the chart or Escape.
  useEffect(() => {
    if (hover === null) return;
    const down = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) onHover(null);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onHover(null);
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("keydown", key);
    };
  }, [hover, onHover]);

  const bars = (
    <div
      ref={scroller}
      className="overflow-x-auto"
      onScroll={() => {
        if (hover === null) return;
        if (card.current) card.current.style.transitionDuration = "0ms";
        place(hover);
      }}
    >
      <div
        ref={track}
        className="relative"
        style={{ minWidth: layout.scroll ? n * layout.slot : undefined }}
        role="group"
        aria-label="Payouts by month"
      >
        <div
          className={`pointer-events-none absolute inset-0 transition-opacity duration-500 motion-reduce:transition-none ${grown ? "opacity-100" : "opacity-0"}`}
          aria-hidden="true"
        >
          {markers.map((m) => (
            <div
              key={m.index}
              className="absolute inset-y-0 border-l border-dashed border-border"
              style={{ left: `${(m.index / n) * 100}%` }}
            />
          ))}
          {placements.map((m) => (
            <span
              key={m.index}
              className={`absolute top-0 whitespace-nowrap text-[10px] leading-4 text-muted-foreground ${m.align === "right" ? "-translate-x-full pr-1 text-right" : "pl-1"}`}
              style={{ left: `${(m.index / n) * 100}%` }}
            >
              {m.label}
            </span>
          ))}
        </div>
        <div className="flex pt-4">
          {buckets.map((b, i) => {
            const has = b.items.length > 0;
            const delay = `${Math.min(i * 25, MAX_DELAY_MS)}ms`;
            const dimmed =
              (hover !== null && hover !== i) || (hoverFy !== null && bucketFy(b) !== hoverFy);
            const total = b.net + b.tds;
            const isNext = i === nextIdx;
            const lane = labels.get(i);
            const body = (
              <>
                <div className="relative flex h-8 w-full flex-col items-center justify-end pb-1">
                  {b.redemption > 0 && (
                    <span
                      className={`size-2.5 rotate-45 rounded-[2px] bg-gain transition-transform duration-500 motion-reduce:transition-none ${grown ? "scale-100" : "scale-0"}`}
                      style={{ transitionDelay: delay }}
                      title={redemptionLabel(b.redemption)}
                    />
                  )}
                </div>
                <div className="flex h-28 w-full items-end justify-center border-b border-border/60">
                  {total > 0 && (
                    <div
                      className="flex w-[62%] max-w-4 origin-bottom flex-col overflow-hidden rounded-t-[3px] transition-transform duration-500 ease-out motion-reduce:transition-none"
                      style={{
                        height: `${(total / max) * 100}%`,
                        minHeight: 3,
                        transform: `scaleY(${grown ? 1 : 0})`,
                        transitionDelay: delay,
                        boxShadow: isNext ? `0 0 14px ${MONEY_COLOR}` : undefined,
                      }}
                    >
                      <div style={{ flex: `${b.tds} 1 0`, backgroundColor: TDS_COLOR }} />
                      <div
                        style={{
                          flex: `${b.net} 1 0`,
                          backgroundColor: MONEY_COLOR,
                          opacity: b.paid ? PAID_OPACITY : 1,
                        }}
                      />
                    </div>
                  )}
                </div>
                <div className="flex h-8 flex-col items-center whitespace-nowrap pt-1.5 text-[10.5px] leading-3 text-muted-foreground">
                  {lane && (
                    <>
                      <span>{lane.month}</span>
                      {lane.year !== null && <span className="opacity-70">{lane.year}</span>}
                    </>
                  )}
                </div>
              </>
            );
            const cls = `min-w-0 flex-1 flex-col items-stretch rounded-md transition-[opacity,background-color,filter] duration-150 ${dimmed ? "opacity-40" : "opacity-100"} ${hover === i ? "brightness-125" : ""} ${isNext && hover === null ? "bg-muted/30" : ""}`;
            return has ? (
              <button
                key={b.key}
                type="button"
                onMouseEnter={() => onHover(i)}
                onFocus={() => onHover(i)}
                onClick={() => onHover(i)}
                aria-label={`${b.label} ${b.year}: ${formatINRWhole(b.net)} after TDS${b.redemption > 0 ? `, ${redemptionLabel(b.redemption)}` : ""}`}
                className={`flex outline-none focus-visible:ring-2 focus-visible:ring-ring ${cls}`}
              >
                {body}
              </button>
            ) : (
              <div key={b.key} className={`flex ${cls}`}>
                {body}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );

  return (
    <div
      ref={wrap}
      className="relative"
      onMouseLeave={() => onHover(null)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onHover(null);
      }}
    >
      {bars}
      <HoverCard
        cardRef={card}
        bucket={shown !== null ? buckets[shown] : null}
        multi={multi}
        visible={hover !== null}
      />
    </div>
  );
}

const EXPAND_IN =
  "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-200";

/** Small day-over-month tile, as on the Coming up card. */
function DateTile({ iso }: { iso: string }) {
  const t = dateTile(iso);
  return (
    <span
      className="num w-11 shrink-0 rounded-md bg-muted/50 py-1 text-center leading-tight"
      aria-hidden="true"
    >
      <span className="block text-[13.5px] font-medium">{t.day}</span>
      <span className="block text-[11px] text-muted-foreground">
        {t.month} {t.year}
      </span>
    </span>
  );
}

/**
 * The payouts behind one financial year row, in an inset box. Figure columns match the
 * "By financial year" header: the box's 1px border plus 12px row padding is 7px more than the
 * header's 6px, so the box reaches 7px past the row on the right to keep them aligned.
 * The paging state lives here, so collapsing the year resets it.
 */
function FyPayouts({ bonds, fy, multi }: { bonds: BondScheduleBond[]; fy: string; multi: boolean }) {
  const rows = fyPayoutRows(bonds, fy);
  const hasRepayment = rows.some((r) => r.kind === "redemption");
  const [shown, setShown] = useState(PAYOUT_PAGE);
  const paging = payoutPaging(rows.length, shown);

  return (
    <div className={`mt-2 mb-3 ml-6 -mr-[7px] ${EXPAND_IN}`}>
      <ul className="flex flex-col divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60">
        {rows.slice(0, paging.visible).map((r, i) => {
          const repay = r.kind === "redemption";
          const muted = r.paid ? "text-muted-foreground" : "";
          return (
            <li
              key={r.key}
              className={`flex items-center gap-2 px-3 py-2 ${i >= PAYOUT_PAGE ? EXPAND_IN : ""}`}
            >
              <DateTile iso={r.date} />
              <span className="min-w-0 flex-1">
                <span
                  className={`block truncate text-[13.5px] ${muted}`}
                  title={repay || multi ? r.name : undefined}
                >
                  {repay || multi ? r.name : formatDate(r.date)}
                </span>
                <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                  {repay ? (
                    <span className="truncate text-gain">◆ Repayment of principal</span>
                  ) : (
                    <>
                      <span
                        className={`size-1.5 shrink-0 rounded-full ${r.paid ? "bg-muted-foreground/60" : ""}`}
                        style={r.paid ? undefined : { backgroundColor: MONEY_COLOR }}
                        aria-hidden="true"
                      />
                      <span className="truncate">{payoutStatusText(r.paid, r.count)}</span>
                    </>
                  )}
                </span>
              </span>
              <span className="num hidden w-20 shrink-0 text-right text-[13.5px] text-muted-foreground sm:block">
                {repay ? "—" : formatINR(r.gross)}
              </span>
              <span
                className={`num w-16 shrink-0 text-right text-[13.5px] ${!repay && r.tds > 0 ? "text-amber-300" : "text-muted-foreground"}`}
              >
                {repay ? "—" : r.tds > 0 ? formatINR(r.tds) : "₹0"}
              </span>
              <span className={`num w-20 shrink-0 text-right text-[13.5px] ${muted}`}>
                {formatINR(repay ? r.gross : r.net)}
              </span>
            </li>
          );
        })}
        {(paging.moreLabel !== null || paging.canShowLess) && (
          <li className="p-1">
            {paging.moreLabel !== null ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="w-full text-muted-foreground"
                onClick={() => setShown(showMoreCount(rows.length, shown))}
              >
                {paging.moreLabel}
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="w-full text-muted-foreground"
                onClick={() => setShown(PAYOUT_PAGE)}
              >
                Show less
              </Button>
            )}
          </li>
        )}
      </ul>
      {hasRepayment && (
        <p className="pt-1.5 text-xs text-muted-foreground">
          Repayments aren&apos;t in the year totals.
        </p>
      )}
    </div>
  );
}

function Body({ bonds, asOf, multi }: { bonds: BondScheduleBond[]; asOf: string; multi: boolean }) {
  const grown = useGrown();
  const [hover, setHover] = useState<number | null>(null);
  const [hoverFy, setHoverFy] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const toggle = (fy: string) =>
    setOpen((prev) => {
      const nextSet = new Set(prev);
      if (!nextSet.delete(fy)) nextSet.add(fy);
      return nextSet;
    });
  const next =combinedNext(bonds, asOf);
  const buckets = monthBuckets(bonds);
  const nextIdx = nextBucketIndex(buckets, next?.date ?? null);
  const progress = couponProgress(bonds);
  const fyRows = mergeFy(bonds);
  const shares = fyShares(fyRows);
  const net = useCountUp(next?.net ?? 0);
  const activeFy = hover !== null ? bucketFy(buckets[hover]) : hoverFy;

  return (
    <>
      <div>
        <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Next payout</p>
        {next ? (
          <>
            <p className="num text-xl font-semibold">
              {formatINR(net)}
              <span className="ml-2 text-[13.5px] font-normal text-muted-foreground">
                {daysText(next.days)} · {formatDate(next.date)}
              </span>
            </p>
            <p className="num text-[13.2px] text-muted-foreground">
              {nextSubline(next, formatINR)}
              {multi && next.names.length > 0 && (
                <span className="font-sans"> · {next.names.join(", ")}</span>
              )}
            </p>
          </>
        ) : (
          <>
            <p className="num text-xl font-semibold">—</p>
            <p className="text-[13.2px] text-muted-foreground">All payouts received.</p>
          </>
        )}
      </div>

      {progress.total > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="h-1 overflow-hidden rounded-full bg-muted/50">
            <div
              className="h-full rounded-full transition-[width] duration-700 ease-out motion-reduce:transition-none"
              style={{ width: grown ? `${progress.pct}%` : "0%", backgroundColor: MONEY_COLOR }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            <span className="num text-foreground">{formatINRWhole(progress.received)}</span> of{" "}
            <span className="num">{formatINRWhole(progress.total)}</span> coupons received
          </p>
        </div>
      )}

      <Chart
        buckets={buckets}
        nextIdx={nextIdx}
        hover={hover}
        hoverFy={hoverFy}
        grown={grown}
        multi={multi}
        onHover={setHover}
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ backgroundColor: MONEY_COLOR }} aria-hidden="true" />
          Upcoming
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ backgroundColor: MONEY_COLOR, opacity: PAID_OPACITY }}
            aria-hidden="true"
          />
          Paid
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ backgroundColor: TDS_COLOR }} aria-hidden="true" />
          TDS
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-gain" aria-hidden="true">
            ◆
          </span>
          Repayment
        </span>
      </div>

      {fyRows.length > 0 && (
        <div className="flex flex-col border-t border-border/50 pt-2">
        <div
          className="flex items-center gap-2 px-1.5 pb-1 text-[11px] uppercase tracking-wider text-muted-foreground"
          aria-hidden="true"
        >
          <span className="min-w-0 flex-1 truncate">By financial year</span>
          <span className="hidden w-20 shrink-0 text-right sm:block">Coupons</span>
          <span className="w-16 shrink-0 text-right">TDS</span>
          <span className="w-20 shrink-0 text-right">You get</span>
        </div>
        <ul className="flex flex-col" onMouseLeave={() => setHoverFy(null)}>
          {fyRows.map((r, i) => {
            const isOpen = open.has(r.fy);
            return (
              <li
                key={r.fy}
                onMouseEnter={() => setHoverFy(r.fy)}
                className={`rounded-md text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 ${activeFy === r.fy ? "bg-muted/40" : ""} ${activeFy !== null && activeFy !== r.fy ? "opacity-60" : ""}`}
              >
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => toggle(r.fy)}
                  className="block w-full rounded-md px-1.5 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex items-center gap-2">
                    <span className="flex min-w-0 flex-1 items-center gap-1.5">
                      <ChevronDown
                        className={`size-3.5 shrink-0 text-muted-foreground motion-safe:transition-transform ${isOpen ? "" : "-rotate-90"}`}
                        aria-hidden="true"
                      />
                      <span className="min-w-0 truncate">
                        {fyShort(r.fy)}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {r.coupons} {r.coupons === 1 ? "payout" : "payouts"}
                        </span>
                      </span>
                    </span>
                    <span className="num hidden w-20 shrink-0 text-right text-muted-foreground sm:block">
                      {formatINRWhole(r.gross)}
                    </span>
                    <span
                      className={`num w-16 shrink-0 text-right ${r.tds > 0 ? "text-amber-300" : "text-muted-foreground"}`}
                    >
                      {formatINRWhole(r.tds)}
                    </span>
                    <span className="num w-20 shrink-0 text-right">{formatINRWhole(r.net)}</span>
                  </span>
                  <span
                    className="mt-1.5 block h-0.5 overflow-hidden rounded-full bg-muted/50"
                    role="img"
                    aria-label={`Share of all payouts after TDS: ${Math.round(shares[i])}%`}
                    title={`Share of all payouts after TDS: ${Math.round(shares[i])}%`}
                  >
                    <span
                      className="block h-full rounded-full transition-[width] duration-700 ease-out motion-reduce:transition-none"
                      style={{
                        width: grown ? `${shares[i]}%` : "0%",
                        backgroundColor: MONEY_COLOR,
                        transitionDelay: `${i * 80}ms`,
                      }}
                    />
                  </span>
                </button>
                {isOpen && <FyPayouts bonds={bonds} fy={r.fy} multi={multi} />}
              </li>
            );
          })}
        </ul>
        </div>
      )}
    </>
  );
}

function Loaded({ data, single }: { data: BondScheduleData; single: boolean }) {
  const [sel, setSel] = useState<string>(ALL_BONDS);
  const bonds = selectBonds(data.bonds, sel);
  const current = bonds.length === 1 && data.bonds.length > 1 ? String(bonds[0].id) : ALL_BONDS;
  const showSelect = !single && data.bonds.length > 1;

  return (
    <Card size="sm" className="min-w-0 gap-3 px-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Bond payouts
          </p>
          <CardInfo>
            Estimated dates. Each bond&apos;s coupons are counted back from its maturity date using
            its payment frequency, and only after you bought it. Real dates can differ by a few
            days. Corporate bonds have 10% TDS on every coupon; government bonds, SGBs and tax-free
            bonds have none.
          </CardInfo>
        </div>
        {showSelect && (
          <Select value={current} onValueChange={(v) => setSel((v as string | null) ?? ALL_BONDS)}>
            <SelectTrigger
              size="sm"
              className="max-w-[min(14rem,100%)] text-xs"
              aria-label="Bond"
              title={data.bonds.find((b) => String(b.id) === current)?.name ?? "All Bonds"}
            >
              <SelectValue className="min-w-0">
                {(v: string | null) => (
                  <span className="min-w-0 truncate">
                    {v === null || v === ALL_BONDS
                      ? "All Bonds"
                      : (data.bonds.find((b) => String(b.id) === v)?.name ?? "All Bonds")}
                  </span>
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent
              alignItemWithTrigger={false}
              align="end"
              className="w-auto max-w-[min(28rem,calc(100vw-2rem))] min-w-(--anchor-width)"
            >
              <SelectItem value={ALL_BONDS}>All Bonds</SelectItem>
              {data.bonds.map((b) => (
                <SelectItem
                  key={b.id}
                  value={String(b.id)}
                  className="*:first:min-w-0 *:first:shrink *:first:overflow-hidden"
                >
                  <span className="flex min-w-0 flex-1 flex-col text-left">
                    <span className="truncate" title={b.name}>
                      {b.name}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      {optionDetail(b)}
                    </span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      <Body key={current} bonds={bonds} asOf={data.as_of} multi={bonds.length > 1} />
    </Card>
  );
}

function BondScheduleSkeleton() {
  return (
    <Card size="sm" className="min-w-0 gap-3 px-4" aria-busy="true" aria-label="Loading…">
      <div className="flex items-center justify-between">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="h-7 w-32 rounded-lg" />
      </div>
      <div className="flex flex-col gap-1.5">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-3.5 w-56" />
      </div>
      <Skeleton className="h-1 w-full rounded-full" />
      <div className="flex h-36 items-end gap-1.5">
        {[40, 70, 55, 85, 60, 95, 50, 75, 65, 90].map((h, i) => (
          <Skeleton key={i} className="flex-1 rounded-t-[3px]" style={{ height: `${h}%` }} />
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
      </div>
    </Card>
  );
}

/** Estimated payout schedule: all bonds (Interest & TDS tab) or one bond (`id`, details page). */
export function BondSchedule({ id }: { id?: number }) {
  const single = id !== undefined;
  const path = single ? `${BOND_SCHEDULE_PATH}?id=${id}` : BOND_SCHEDULE_PATH;
  const { state, retry } = useAnalyticsSection<BondScheduleData>(path);

  if (state.status === "loading") return <BondScheduleSkeleton />;

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <div>
          <p className="text-[13.5px] font-medium text-destructive">{state.message}</p>
          {state.description && (
            <p className="text-[13.5px] text-muted-foreground">{state.description}</p>
          )}
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }

  if (state.data.bonds.length === 0) return null;
  return <Loaded data={state.data} single={single} />;
}
