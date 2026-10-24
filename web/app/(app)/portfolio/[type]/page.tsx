import { Suspense } from "react";
import { notFound } from "next/navigation";
import { TableSkeleton } from "@/components/portfolio/grid/data-table";
import { Portfolio } from "@/components/portfolio/portfolio";
import { ASSET_SLUGS, getAssetEntry } from "@/lib/asset-catalog";

export function generateStaticParams() {
  return ASSET_SLUGS.map((type) => ({ type }));
}

type Props = { params: Promise<{ type: string }> };

const ENTER =
  "animate-in fade-in slide-in-from-bottom-1 duration-200 motion-reduce:animate-none";

async function Content({ params }: Props) {
  const { type } = await params;
  const entry = getAssetEntry(type);
  if (!entry) notFound();
  return (
    <div key={entry.type} className={`min-w-0 space-y-4 ${ENTER}`}>
      <Suspense fallback={<TableSkeleton />}>
        <Portfolio key={entry.type} type={entry.type} />
      </Suspense>
    </div>
  );
}

export default function PortfolioTypePage(props: Props) {
  return (
    <Suspense
      fallback={
        <div className={`min-w-0 ${ENTER}`}>
          <TableSkeleton />
        </div>
      }
    >
      <Content {...props} />
    </Suspense>
  );
}
