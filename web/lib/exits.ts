import { formatDate } from "./format";
import { amountText } from "./sip";
import type {
  AssetType,
  BondItem,
  FixedDepositItem,
  GoldItem,
  GoldMetal,
  HoldingRow,
  MutualFundItem,
  OtherItem,
  PaidFrom,
  RecurringDepositItem,
  StockItem,
} from "./types";

// ---- Request and response shapes (api/app/schemas/exits.py) ----

export type SellableType = "stock" | "bond" | "mf" | "gold" | "other";
export type SettleableType = "fd" | "rd" | "bond";

export type SellDestinationBody =
  | { kind: "cash_existing"; cash_id: number }
  | { kind: "cash_new"; cash_name: string }
  | { kind: "none" };

export type SettleDestinationBody = SellDestinationBody;

export interface SellBody {
  date: string;
  /** Omitted for Other (always sold whole). */
  quantity?: number;
  price?: number;
  /** Other only: the sale value before charges. */
  amount?: number;
  charges: number;
  destination: SellDestinationBody;
}

export interface SettleBody {
  date?: string;
  amount?: number;
  destination: SettleDestinationBody;
}

export interface ExitRead {
  id: number;
  asset_type: string;
  holding_id: number;
  kind: "maturity" | "sale";
  date: string;
  quantity: number | null;
  amount: number;
  cost: number;
  charges: number;
  destination: "cash" | "none";
  cash_holding_id: number | null;
  cash_added: number | null;
  created_at: string;
  realised_gain: number;
  /** Part of the money in the account that a later holding was paid from. */
  reinvested: number;
  /** What is still in the account from this exit; null when it went nowhere. */
  left_in_account: number | null;
}

export type ExitResult = ExitRead & {
  message: string;
  description: string;
  closed: boolean;
  remaining: number | null;
  cash_name: string | null;
  sips_cancelled: number;
};

export interface StockClose {
  price: number;
  price_date: string;
  source: "history" | "latest";
}

/** An active cash account the money can go into. */
export interface CashAccount {
  id: number;
  name: string;
  balance: number;
}

// ---- Which holdings can be sold or settled ----

const SELLABLE: readonly AssetType[] = ["stock", "bond", "mf", "gold", "other"];
const SETTLEABLE: readonly AssetType[] = ["fd", "rd", "bond"];

export function isSellableType(type: AssetType): type is SellableType {
  return SELLABLE.includes(type);
}

export function isSettleableType(type: AssetType): type is SettleableType {
  return SETTLEABLE.includes(type);
}

interface StatusFields {
  status: "active" | "matured" | "sold";
  settled?: boolean;
  closed_on?: string | null;
}

/** A sellable type that is still held (not matured, not sold). */
export function canSell(type: AssetType, row: StatusFields): boolean {
  return isSellableType(type) && row.status === "active";
}

/** A deposit or bond that has matured and whose payout has not been recorded. */
export function canSettle(type: AssetType, row: StatusFields): boolean {
  return (
    isSettleableType(type) &&
    row.status === "matured" &&
    !row.settled &&
    !row.closed_on
  );
}

// ---- Sale maths ----

function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

export interface SaleInput {
  type: SellableType;
  /** Quantity held; null for Other. */
  held: number | null;
  /** Invested amount of the whole holding (0 when unknown). */
  invested: number;
  /** Quantity being sold; null for Other. */
  quantity: number | null;
  price: number | null;
  /** Other: the sale value before charges. */
  amount: number | null;
  charges: number;
}

export interface SaleSummary {
  gross: number;
  charges: number;
  youGet: number;
  cost: number;
  /** Cost is the invested share; false when nothing was invested (no gain to show). */
  hasCost: boolean;
  gain: number;
  gainPct: number | null;
  /** True when every unit is sold. */
  full: boolean;
  /** A fund partial sale is costed first-in-first-out on the server unless the invested amount was edited, so the preview is an estimate. */
  estimated: boolean;
}

/** Whether `quantity` is everything held (compared at 4 decimals). */
export function sellsAll(held: number | null, quantity: number | null): boolean {
  if (held === null || quantity === null) return false;
  return Math.abs(held - quantity) < 0.00005;
}

/**
 * What a sale brings in: gross = quantity x price, you get = gross less charges, cost = the
 * invested amount (all of it for a full sale, the proportional share otherwise), gain = you get
 * less cost. Returns null while the inputs are incomplete.
 */
export function saleSummary(input: SaleInput): SaleSummary | null {
  const { type, held, invested, quantity, price, amount } = input;
  const charges = Number.isFinite(input.charges) && input.charges > 0 ? input.charges : 0;
  let gross: number;
  let cost: number;
  let full: boolean;
  if (type === "other") {
    if (amount === null || !Number.isFinite(amount) || amount <= 0) return null;
    gross = round2(amount);
    cost = round2(invested);
    full = true;
  } else {
    if (
      quantity === null ||
      price === null ||
      held === null ||
      !Number.isFinite(quantity) ||
      !Number.isFinite(price) ||
      quantity <= 0 ||
      price <= 0 ||
      held <= 0 ||
      quantity > held + 0.00005
    ) {
      return null;
    }
    gross = round2(quantity * price);
    full = sellsAll(held, quantity);
    cost = full ? round2(invested) : round2((invested * quantity) / held);
  }
  const youGet = round2(gross - charges);
  const gain = round2(youGet - cost);
  const hasCost = cost > 0;
  return {
    gross,
    charges,
    youGet,
    cost,
    hasCost,
    gain,
    gainPct: hasCost ? (gain / cost) * 100 : null,
    full,
    estimated: type === "mf" && !full,
  };
}

/** "Gain ₹2,500" or "Loss ₹300"; null when there is no cost to compare against. */
export function gainText(summary: Pick<SaleSummary, "gain" | "hasCost">): string | null {
  if (!summary.hasCost) return null;
  const word = summary.gain < 0 ? "Loss" : "Gain";
  return `${word} ${amountText(Math.abs(summary.gain))}`;
}

// ---- Held period ----

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
}

function addMonthsClamped(iso: string, months: number): string {
  const [y, m, d] = parts(iso);
  const total = y * 12 + (m - 1) + months;
  const ny = Math.floor(total / 12);
  const nm = total - ny * 12;
  const dim = new Date(Date.UTC(ny, nm + 1, 0)).getUTCDate();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${ny}-${pad(nm + 1)}-${pad(Math.min(d, dim))}`;
}

/** Whole years, months and days from `start` to `end` (zeros when end is not after start). */
export function periodBetween(
  start: string,
  end: string,
): { years: number; months: number; days: number } {
  if (end <= start) return { years: 0, months: 0, days: 0 };
  const [sy, sm] = parts(start);
  const [ey, em, ed] = parts(end);
  let k = (ey - sy) * 12 + (em - sm);
  while (k > 0 && addMonthsClamped(start, k) > end) k--;
  const [ry, rm, rd] = parts(addMonthsClamped(start, k));
  const days = Math.round(
    (Date.UTC(ey, em - 1, ed) - Date.UTC(ry, rm - 1, rd)) / 86400000,
  );
  return { years: Math.floor(k / 12), months: k % 12, days };
}

/** "held 1 yr 3 mo", "held 2 yrs", "held 5 mo", "held 20 days"; null without a start date. */
export function heldText(start: string | null, end: string): string | null {
  if (!start || end < start) return null;
  const { years, months, days } = periodBetween(start, end);
  if (years > 0 || months > 0) {
    const bits: string[] = [];
    if (years > 0) bits.push(`${years} ${years === 1 ? "yr" : "yrs"}`);
    if (months > 0) bits.push(`${months} mo`);
    return `held ${bits.join(" ")}`;
  }
  if (days === 0) return "held less than a day";
  return `held ${days} ${days === 1 ? "day" : "days"}`;
}

// ---- Quantity and price wording ----

const quantityFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });
const priceFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

export function formatQuantity(n: number): string {
  return quantityFormat.format(n);
}

/** Price per unit with 2 to 4 decimals: ₹123.45 or ₹52.1234. */
export function formatPrice(n: number): string {
  return priceFormat.format(n);
}

/** Plain number text for a price field: no trailing zeros, at most 4 decimals. */
export function priceFieldText(n: number): string {
  return String(Number(n.toFixed(4)));
}

/** Whole numbers only (stock and bond units). */
export function wholeQuantity(type: SellableType): boolean {
  return type === "stock" || type === "bond";
}

export function quantityLabel(type: SellableType): string {
  switch (type) {
    case "stock":
      return "Quantity";
    case "bond":
      return "Bonds";
    case "mf":
      return "Units";
    case "gold":
      return "Weight (g)";
    case "other":
      return "Amount";
  }
}

export function priceLabel(type: SellableType): string {
  switch (type) {
    case "stock":
      return "Price per share";
    case "bond":
      return "Price per bond";
    case "mf":
      return "NAV per unit";
    case "gold":
      return "Rate per gram";
    case "other":
      return "Amount";
  }
}

/** "40 shares", "1 share", "12.5 units", "5 g". */
export function quantityWithUnit(type: AssetType, quantity: number): string {
  const n = formatQuantity(quantity);
  const one = quantity === 1;
  switch (type) {
    case "stock":
      return `${n} ${one ? "share" : "shares"}`;
    case "bond":
      return `${n} ${one ? "bond" : "bonds"}`;
    case "mf":
      return `${n} ${one ? "unit" : "units"}`;
    case "gold":
      return `${n} g`;
    default:
      return n;
  }
}

// ---- Price lookup for a date ----

export type PriceSource =
  | { kind: "stock"; masterId: number }
  | { kind: "mf"; schemeCode: number }
  | { kind: "gold"; metal: GoldMetal; purity: string };

/** API path for the price of a source on a date (ISO). */
export function priceRequestPath(source: PriceSource, date: string): string {
  switch (source.kind) {
    case "stock":
      return `/master/stock/${source.masterId}/close?date=${date}`;
    case "mf":
      return `/master/mf/${source.schemeCode}/nav?date=${date}`;
    case "gold":
      return `/master/gold/rate?metal=${source.metal}&purity=${source.purity}&date=${date}`;
  }
}

export interface PriceOnDate {
  price: number;
  /** The date the price is for (can be earlier than the date asked for). */
  date: string;
}

/** Reads the price and its date out of a stock close, MF NAV or gold rate response. */
export function readPrice(kind: PriceSource["kind"], raw: unknown): PriceOnDate | null {
  const r = raw as Record<string, unknown> | null;
  if (!r) return null;
  const pick = (priceKey: string, dateKey: string): PriceOnDate | null => {
    const price = r[priceKey];
    const date = r[dateKey];
    return typeof price === "number" && typeof date === "string" ? { price, date } : null;
  };
  switch (kind) {
    case "stock":
      return pick("price", "price_date");
    case "mf":
      return pick("nav", "nav_date");
    case "gold":
      return pick("rate_per_gram", "rate_date");
  }
}

/** "Price on 5 Nov 2026: ₹123.45". */
export function priceHint(found: PriceOnDate): string {
  return `Price on ${formatDate(found.date)}: ${formatPrice(found.price)}`;
}

// ---- Where the money went ----

export type ExitFlow = "sell" | "settle";

/** Select values: "" (not chosen), "cash:<id>", "new", "none". */
export type DestinationChoice = string;

export const CHOICE_NEW = "new";
export const CHOICE_NONE = "none";

export interface DestinationOption {
  value: string;
  label: string;
}

export function cashChoice(id: number): string {
  return `cash:${id}`;
}

export type ParsedChoice =
  | { kind: "cash"; id: number }
  | { kind: "new" }
  | { kind: "none" };

export function parseChoice(choice: DestinationChoice): ParsedChoice | null {
  if (choice.startsWith("cash:")) {
    const id = Number(choice.slice(5));
    return Number.isInteger(id) && id > 0 ? { kind: "cash", id } : null;
  }
  if (choice === CHOICE_NEW) return { kind: "new" };
  if (choice === CHOICE_NONE) return { kind: "none" };
  return null;
}

/** The info line under the destination Select. */
export const PAID_FROM_INFO =
  "Investing this money later? Pick this account under 'Paid From' when you add the holding, so it isn't counted twice.";

/** The choices (same for a sale and a settlement): each cash account, a new account, spent elsewhere. */
export function destinationOptions(
  accounts: readonly CashAccount[],
): DestinationOption[] {
  const options: DestinationOption[] = accounts.map((a) => ({
    value: cashChoice(a.id),
    label: `${a.name} · ${amountText(a.balance)}`,
  }));
  options.push({ value: CHOICE_NEW, label: "A New Savings Account" });
  options.push({ value: CHOICE_NONE, label: "Spent Or Moved Elsewhere (Not Counted)" });
  return options;
}

/**
 * The net-worth effect of a choice, shown under the select. Null until a choice and a usable
 * amount exist.
 */
export function effectText(
  choice: DestinationChoice,
  accounts: readonly CashAccount[],
  amount: number | null,
): string | null {
  if (amount === null || !Number.isFinite(amount) || amount <= 0) return null;
  const parsed = parseChoice(choice);
  if (!parsed) return null;
  const money = amountText(round2(amount));
  switch (parsed.kind) {
    case "cash": {
      const account = accounts.find((a) => a.id === parsed.id);
      if (!account) return null;
      return `${account.name}: ${amountText(account.balance)} → ${amountText(round2(account.balance + amount))}`;
    }
    case "new":
      return `Adds ${money} to your net worth`;
    case "none":
      return `This ${money} won't be added to your net worth.`;
  }
}

/** "HDFC Bank Savings" for a known bank; empty when the bank is unknown. */
export function suggestedAccountName(bank: string | null | undefined): string {
  const name = bank?.trim();
  return name ? `${name} Savings`.slice(0, 200) : "";
}

/** The destination object of a sale; null when the choice is missing or invalid. */
export function sellDestination(
  choice: DestinationChoice,
  cashName: string,
): SellDestinationBody | null {
  const parsed = parseChoice(choice);
  if (!parsed) return null;
  switch (parsed.kind) {
    case "cash":
      return { kind: "cash_existing", cash_id: parsed.id };
    case "new":
      return { kind: "cash_new", cash_name: cashName.trim() };
    case "none":
      return { kind: "none" };
  }
}

/** The destination object of a settlement (same shapes as a sale). */
export function settleDestination(
  choice: DestinationChoice,
  cashName: string,
): SettleDestinationBody | null {
  return sellDestination(choice, cashName);
}

// ---- What a sell dialog needs to know about a holding ----

export interface SellSubject {
  type: SellableType;
  id: number;
  name: string;
  /** Quantity held; null for Other. */
  held: number | null;
  invested: number;
  startDate: string | null;
  source: PriceSource | null;
  /** A running or paused SIP feeds this fund (a full sale leaves it running). */
  hasSip: boolean;
  /** Bank, broker or platform, used to name a new savings account. */
  suggestedBank: string | null;
}

/** Reads a grid or details row into what the sell dialog needs; null if the type can't be sold. */
export function sellSubject(
  type: AssetType,
  row: HoldingRow,
  name: string,
): SellSubject | null {
  switch (type) {
    case "stock": {
      const r = row as StockItem;
      return {
        type,
        id: r.id,
        name,
        held: r.quantity,
        invested: r.invested,
        startDate: r.buy_date,
        source: r.master_id !== null ? { kind: "stock", masterId: r.master_id } : null,
        hasSip: false,
        suggestedBank: r.broker,
      };
    }
    case "bond": {
      const r = row as BondItem;
      return {
        type,
        id: r.id,
        name,
        held: r.quantity,
        invested: r.invested,
        startDate: r.purchase_date,
        source: null,
        hasSip: false,
        suggestedBank: r.platform,
      };
    }
    case "mf": {
      const r = row as MutualFundItem;
      return {
        type,
        id: r.id,
        name,
        held: r.units,
        invested: r.invested,
        startDate: r.purchase_date,
        source: r.scheme_code !== null ? { kind: "mf", schemeCode: r.scheme_code } : null,
        hasSip: !!r.sip && (r.sip.status === "active" || r.sip.status === "paused"),
        suggestedBank: r.platform,
      };
    }
    case "gold": {
      const r = row as GoldItem;
      return {
        type,
        id: r.id,
        name,
        held: r.weight_grams,
        invested: r.invested,
        startDate: r.purchase_date,
        source: { kind: "gold", metal: r.metal, purity: r.purity },
        hasSip: false,
        suggestedBank: null,
      };
    }
    case "other": {
      const r = row as OtherItem;
      return {
        type,
        id: r.id,
        name,
        held: null,
        invested: r.invested_amount ?? 0,
        startDate: r.acquired_on,
        source: null,
        hasSip: false,
        suggestedBank: null,
      };
    }
    default:
      return null;
  }
}

/** "40 shares · invested ₹1,00,000": the line under the dialog title. */
export function holdingLine(subject: SellSubject): string {
  const bits: string[] = [];
  if (subject.held !== null) bits.push(`${quantityWithUnit(subject.type, subject.held)} held`);
  if (subject.invested > 0) bits.push(`invested ${amountText(subject.invested)}`);
  return bits.join(" · ");
}

// ---- What a settle dialog needs to know about a matured holding ----

export interface SettleSubject {
  type: SettleableType;
  id: number;
  name: string;
  maturityDate: string;
  /** What the deposit or bond pays at maturity; null when unknown. */
  maturityAmount: number | null;
  /** Bank or issuer, used to name a new savings account. */
  suggestedBank: string | null;
}

/** Reads a grid or details row into what the settle dialog needs; null if it can't be settled. */
export function settleSubject(
  type: AssetType,
  row: HoldingRow,
  name: string,
): SettleSubject | null {
  if (!isSettleableType(type)) return null;
  const maturityDate = row.maturity_date;
  if (!maturityDate) return null;
  const common = {
    type,
    id: row.id,
    name,
    maturityDate,
    maturityAmount: row.maturity_amount ?? null,
  };
  if (type === "bond") {
    const r = row as BondItem;
    return { ...common, suggestedBank: r.platform ?? r.issuer };
  }
  const r = row as FixedDepositItem | RecurringDepositItem;
  return { ...common, suggestedBank: r.bank };
}

// ---- After an exit: what changed ----

/** Types whose lists change after this exit: the holding's own, and cash when money went in. */
export function changedTypes(
  type: AssetType,
  exit: Pick<ExitRead, "cash_holding_id">,
): AssetType[] {
  const out: AssetType[] = [type];
  if (exit.cash_holding_id !== null) out.push("cash");
  return out;
}

// ---- Reinvesting the money that landed in an account ----

/** The asset types offered as quick "reinvest" buttons, in order. */
export const REINVEST_TYPES: readonly { type: string; label: string }[] = [
  { type: "mf", label: "+ Mutual Fund" },
  { type: "fd", label: "+ FD" },
  { type: "stock", label: "+ Stock" },
  { type: "bond", label: "+ Bond" },
  { type: "gold", label: "+ Gold" },
];

type ReinvestExit = Pick<
  ExitRead,
  "id" | "date" | "amount" | "cash_holding_id" | "cash_added" | "left_in_account"
>;

/** What reached the account: cash added, else the amount. */
export function landedAmount(exit: Pick<ExitRead, "amount" | "cash_added">): number {
  return exit.cash_added ?? exit.amount;
}

/** Money from this exit still in the account; what a reinvestment is prefilled with. */
export function reinvestableAmount(
  exit: Pick<ExitRead, "amount" | "cash_added" | "left_in_account">,
): number {
  return exit.left_in_account ?? landedAmount(exit);
}

/** Whether a Reinvest action makes sense: money went to an account and some is left. */
export function canReinvest(
  exit: Pick<ExitRead, "cash_holding_id" | "left_in_account" | "amount" | "cash_added">,
): boolean {
  return exit.cash_holding_id !== null && reinvestableAmount(exit) > 0;
}

/** What the add form is prefilled with when reinvesting (matches lib/reinvest.ts). */
export function reinvestPrefillFor(
  type: string,
  exit: ReinvestExit,
  cashName: string,
): {
  type: string;
  amount: number;
  date: string;
  cash_id: number;
  cash_name: string;
  from_exit_id: number;
} | null {
  if (exit.cash_holding_id === null) return null;
  return {
    type,
    amount: reinvestableAmount(exit),
    date: exit.date,
    cash_id: exit.cash_holding_id,
    cash_name: cashName,
    from_exit_id: exit.id,
  };
}

/** "₹1,07,186 is now in HDFC Savings." */
export function successLine(
  exit: Pick<ExitRead, "amount" | "cash_added">,
  cashName: string,
): string {
  return `${amountText(landedAmount(exit))} is now in ${cashName}.`;
}

export const REINVEST_QUESTION = "Reinvested some of it?";

/** True when a finished exit put money into a cash account (the dialog shows the next step). */
export function landedInAccount(exit: Pick<ExitRead, "cash_holding_id">): boolean {
  return exit.cash_holding_id !== null;
}

/**
 * Details-page line for an exit's money: "₹50,000 reinvested · ₹57,186 still in HDFC Savings",
 * or "₹1,07,186 in HDFC Savings" when none was reinvested. Null when it went to no account.
 */
export function reinvestSummary(
  exit: Pick<ExitRead, "cash_holding_id" | "amount" | "cash_added" | "reinvested" | "left_in_account">,
  accountName: string | null,
): string | null {
  if (exit.cash_holding_id === null) return null;
  const account = accountName ?? "a cash account";
  if (exit.reinvested > 0) {
    const left = exit.left_in_account ?? Math.max(landedAmount(exit) - exit.reinvested, 0);
    return `${amountText(exit.reinvested)} reinvested · ${amountText(left)} still in ${account}`;
  }
  return `${amountText(landedAmount(exit))} in ${account}`;
}

// ---- The exits list on the details page ----

/** "Sold 40 shares", "Sold 5 g", "Sold" (Other), "Settled". */
export function exitTitle(
  type: AssetType,
  exit: Pick<ExitRead, "kind" | "quantity">,
): string {
  if (exit.kind === "maturity") return "Settled";
  if (exit.quantity === null) return "Sold";
  return `Sold ${quantityWithUnit(type, exit.quantity)}`;
}

export interface ExitWhere {
  text: string;
}

/** "Into HDFC Savings", "Spent or moved elsewhere". */
export function exitWhere(
  exit: Pick<ExitRead, "destination" | "cash_holding_id">,
  accountName: string | null,
): ExitWhere {
  if (exit.destination === "cash") {
    return { text: accountName ? `Into ${accountName}` : "Into a cash account" };
  }
  return { text: "Spent or moved elsewhere" };
}

/** The gain or loss of an exit as text plus its sign; null when the cost is unknown or zero gain. */
export function exitGain(
  exit: Pick<ExitRead, "amount" | "cost">,
): { text: string; value: number } | null {
  if (exit.cost <= 0) return null;
  const value = round2(exit.amount - exit.cost);
  if (value === 0) return null;
  return {
    text: `${value < 0 ? "Loss" : "Gain"} ${amountText(Math.abs(value))}`,
    value,
  };
}

/** "Paid from HDFC Savings · ₹50,000"; null when the holding wasn't paid from an account. */
export function paidFromText(item: { paid_from?: PaidFrom | null }): string | null {
  const p = item.paid_from;
  if (!p) return null;
  return `Paid from ${p.cash_name ?? "a deleted account"} · ${amountText(p.amount)}`;
}

/** Info line on a Cash & Savings details page. */
export const CASH_PAID_FROM_INFO =
  "Use this account as 'Paid From' when you add a holding bought with this money.";

/** Only the newest exit of a holding can be undone (the list is newest first). */
export function undoableExitId(exits: readonly Pick<ExitRead, "id">[]): number | null {
  return exits.length > 0 ? exits[0].id : null;
}
