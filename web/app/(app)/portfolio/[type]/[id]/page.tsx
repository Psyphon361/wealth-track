import { Suspense } from "react";
import { notFound } from "next/navigation";
import {
  HoldingDetail,
  HoldingDetailSkeleton,
} from "@/components/holding-detail/holding-detail";
import { getAssetEntry } from "@/lib/asset-catalog";

type Props = { params: Promise<{ type: string; id: string }> };

async function Content({ params }: Props) {
  const { type, id } = await params;
  const entry = getAssetEntry(type);
  const numericId = Number(id);
  if (!entry || !Number.isInteger(numericId) || numericId < 1) notFound();
  return (
    <div className="mx-auto w-full max-w-4xl">
      <HoldingDetail key={`${entry.type}-${numericId}`} type={entry.type} id={numericId} />
    </div>
  );
}

export default function HoldingDetailPage(props: Props) {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-4xl">
          <HoldingDetailSkeleton />
        </div>
      }
    >
      <Content {...props} />
    </Suspense>
  );
}
