import {
  Landmark,
  LineChart,
  PieChart,
  Repeat,
  ScrollText,
  type LucideIcon,
} from "lucide-react";
import type { AssetType } from "@/lib/types";

export interface AssetCatalogEntry {
  type: AssetType;
  title: string;
  hint: string;
  icon: LucideIcon;
  group: string;
}

export const ASSET_GROUPS = ["Deposits", "Market-linked"] as const;

export const ASSET_CATALOG: AssetCatalogEntry[] = [
  {
    type: "fd",
    title: "Fixed deposit",
    hint: "Bank FD, cumulative or interest payout",
    icon: Landmark,
    group: "Deposits",
  },
  {
    type: "rd",
    title: "Recurring deposit",
    hint: "Fixed monthly instalments",
    icon: Repeat,
    group: "Deposits",
  },
  {
    type: "stock",
    title: "Stocks",
    hint: "NSE/BSE shares",
    icon: LineChart,
    group: "Market-linked",
  },
  {
    type: "mf",
    title: "Mutual funds",
    hint: "Units at average NAV",
    icon: PieChart,
    group: "Market-linked",
  },
  {
    type: "bond",
    title: "Bonds",
    hint: "Govt, corporate, tax-free, SGB",
    icon: ScrollText,
    group: "Market-linked",
  },
];

export const ASSET_SLUGS: AssetType[] = ASSET_CATALOG.map((a) => a.type);

export function getAssetEntry(slug: string): AssetCatalogEntry | undefined {
  return ASSET_CATALOG.find((a) => a.type === slug);
}
