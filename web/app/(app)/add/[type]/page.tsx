import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ASSET_SLUGS, getAssetEntry } from "@/lib/asset-catalog";
import { AddFormPage } from "./add-form-page";

export function generateStaticParams() {
  return ASSET_SLUGS.map((type) => ({ type }));
}

async function Content({ params }: PageProps<"/add/[type]">) {
  const { type } = await params;
  const entry = getAssetEntry(type);
  if (!entry) notFound();
  return <AddFormPage type={entry.type} />;
}

export default function AddTypePage(props: PageProps<"/add/[type]">) {
  return (
    <Suspense>
      <Content {...props} />
    </Suspense>
  );
}
