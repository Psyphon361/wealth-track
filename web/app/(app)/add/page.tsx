import { Suspense } from "react";
import { AddAssetFlow } from "./add-asset-flow";
import type { AssetType } from "@/lib/types";

const TYPES: AssetType[] = ["fd", "rd", "stock", "bond", "mf"];

async function Content({ searchParams }: PageProps<"/add">) {
  const { type } = await searchParams;
  const initial = TYPES.find((t) => t === type) ?? "fd";
  return <AddAssetFlow initialType={initial} />;
}

export default function AddAssetPage(props: PageProps<"/add">) {
  return (
    <Suspense>
      <Content {...props} />
    </Suspense>
  );
}
