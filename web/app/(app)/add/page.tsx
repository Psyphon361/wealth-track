import { Suspense } from "react";
import { redirect } from "next/navigation";
import { AssetGallery } from "@/components/add/asset-gallery";
import { getAssetEntry } from "@/lib/asset-catalog";

async function Content({ searchParams }: PageProps<"/add">) {
  const { type } = await searchParams;
  if (typeof type === "string" && getAssetEntry(type)) {
    redirect(`/add/${type}`);
  }
  return <AssetGallery />;
}

export default function AddAssetPage(props: PageProps<"/add">) {
  return (
    <Suspense>
      <Content {...props} />
    </Suspense>
  );
}
