"use client";

import { useState } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatDate, formatINRWhole } from "@/lib/format";
import { termText } from "@/lib/capital-gains";
import {
  bucketLabel,
  daysLeftText,
  hasMore,
  progressPercent,
  roomSentence,
  visibleItems,
  type LossLot,
  type TurningLot,
  type UnrealisedHarvest,
} from "@/lib/unrealised";
import { gainClass } from "./gains-summary";
import { TopProgress } from "./top-progress";

const LABEL_CLS = "text-[11px] font-medium uppercase tracking-wider text-muted-foreground";

function ShowToggle({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="self-start rounded-md px-1.5 py-1 text-[13.2px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {expanded ? "Show Less" : "Show More"}
    </button>
  );
}

export function RoomCard({ harvest, switching }: { harvest: UnrealisedHarvest; switching: boolean }) {
  const pct = progressPercent(harvest.exemption_used, harvest.exemption_limit);
  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className={LABEL_CLS}>Tax-Free Room Left This Year</p>
        <CardInfo>
          Under Section 112A, the first {formatINRWhole(harvest.exemption_limit)} of equity
          long-term gains in a financial year is exempt from tax. This is an estimate, not tax
          advice, and is shown for information only.
        </CardInfo>
      </div>
      <div className={`flex flex-col gap-3 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}>
        <div>
          <p className="num text-xl font-semibold">{formatINRWhole(harvest.exemption_room)}</p>
          <p className="text-[13.2px] text-muted-foreground">{roomSentence(harvest.exemption_room)}</p>
        </div>
        <div>
          <div
            className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={Math.round(pct)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Tax-free limit used"
          >
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          <p className="num mt-1 text-[13.2px] text-muted-foreground">
            {formatINRWhole(harvest.exemption_used)} used of {formatINRWhole(harvest.exemption_limit)}
          </p>
        </div>
        <p className="text-[13.2px] text-muted-foreground">
          Unrealised long-term equity gain today:{" "}
          <span className={`num ${gainClass(harvest.unrealised_equity_lt_gain)}`}>
            {formatINRWhole(harvest.unrealised_equity_lt_gain)}
          </span>
        </p>
      </div>
    </Card>
  );
}

function TurningRow({ lot }: { lot: TurningLot }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-md px-1.5 py-1.5 text-[13.5px] hover:bg-muted/40">
      <span className="min-w-0">
        <Link
          href={`/portfolio/${lot.asset_type}/${lot.holding_id}`}
          className="block truncate hover:underline"
          title={lot.name}
        >
          {lot.name}
        </Link>
        <span className="text-[13.2px] text-muted-foreground">
          {formatDate(lot.long_term_on)} · {daysLeftText(lot.days_to_long_term)} ·{" "}
          {bucketLabel(lot.bucket_after)}
        </span>
      </span>
      <span className={`num shrink-0 text-right ${gainClass(lot.gain)}`}>{formatINRWhole(lot.gain)}</span>
    </li>
  );
}

export function TurningCard({ lots, switching }: { lots: TurningLot[]; switching: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card size="sm" className="relative min-w-0 gap-2 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className={LABEL_CLS}>Turning Long Term Soon</p>
        <CardInfo>
          Lots that cross the long-term holding period in the next 90 days. Long-term gains are
          taxed at a different rate. For information only.
        </CardInfo>
      </div>
      {lots.length === 0 ? (
        <p className="text-[13.2px] text-muted-foreground">Nothing turns long term in the next 90 days.</p>
      ) : (
        <>
          <ul className={`flex flex-col transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}>
            {visibleItems(lots, expanded).map((l, i) => (
              <TurningRow key={`${l.asset_type}-${l.holding_id}-${l.long_term_on}-${i}`} lot={l} />
            ))}
          </ul>
          {hasMore(lots) && <ShowToggle expanded={expanded} onToggle={() => setExpanded((e) => !e)} />}
        </>
      )}
    </Card>
  );
}

function LossRow({ lot }: { lot: LossLot }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-md px-1.5 py-1.5 text-[13.5px] hover:bg-muted/40">
      <span className="min-w-0">
        <Link
          href={`/portfolio/${lot.asset_type}/${lot.holding_id}`}
          className="block truncate hover:underline"
          title={lot.name}
        >
          {lot.name}
        </Link>
        <span className="text-[13.2px] text-muted-foreground">
          {termText(lot.term)} · {bucketLabel(lot.bucket)}
        </span>
      </span>
      <span className={`num shrink-0 text-right ${gainClass(lot.gain)}`}>{formatINRWhole(lot.gain)}</span>
    </li>
  );
}

export function LossesCard({ lots, switching }: { lots: LossLot[]; switching: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card size="sm" className="relative min-w-0 gap-2 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className={LABEL_CLS}>Unrealised Losses</p>
        <CardInfo>
          Lots currently worth less than their cost, largest first. Crypto losses can&apos;t be set
          off against other gains, and other losses are set off only within the same financial
          year.
        </CardInfo>
      </div>
      {lots.length === 0 ? (
        <p className="text-[13.2px] text-muted-foreground">No lots are below their cost.</p>
      ) : (
        <>
          <ul className={`flex flex-col transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}>
            {visibleItems(lots, expanded).map((l, i) => (
              <LossRow key={`${l.asset_type}-${l.holding_id}-${l.bought_on}-${i}`} lot={l} />
            ))}
          </ul>
          {hasMore(lots) && <ShowToggle expanded={expanded} onToggle={() => setExpanded((e) => !e)} />}
        </>
      )}
    </Card>
  );
}
