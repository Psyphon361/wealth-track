"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { AssetForm } from "@/components/forms/asset-form";
import { CasImport } from "@/components/forms/cas-import/cas-import";
import { FormBusyContext } from "@/components/forms/form-disabled";
import { SipForm } from "@/components/forms/sip-form";
import { Card, CardContent } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { getAssetEntry } from "@/lib/asset-catalog";
import { takeReinvest, type ReinvestPrefill } from "@/lib/reinvest";
import { SIPS_VIEW_HREF } from "@/lib/sip";
import type { AssetType } from "@/lib/types";

type MfTab = "manual" | "cas" | "sip";

export function AddFormPage({ type }: { type: AssetType }) {
  const router = useRouter();
  // `?tab=sip` opens the MF page on the SIP tab (links from the SIPs view).
  const tabParam = useSearchParams().get("tab");
  // The route stays mounted after leaving it (cacheComponents), so bump the
  // key to remount the form blank for the next visit.
  const [formKey, setFormKey] = useState(0);
  // The tab the user picked; until then the link decides (SIP) or Import CAS.
  const [picked, setPicked] = useState<MfTab | null>(null);
  const mfTab: MfTab = picked ?? (tabParam === "sip" ? "sip" : "cas");
  // True while a form save or CAS upload/import is in flight (locks the tabs).
  const [busy, setBusy] = useState(false);
  // Same for the MF tab: the cleanup runs when the route is hidden, so every
  // visit opens on Import CAS (the default tab) unless the link asks for SIP.
  useEffect(() => () => setPicked(null), []);
  // "Reinvest" hands over a one-shot prefill; take it each time the page opens
  // and remount the form so it starts from it.
  const [reinvest, setReinvest] = useState<ReinvestPrefill | null>(null);
  useEffect(() => {
    const taken = takeReinvest(type);
    if (!taken) return;
    // One-shot handoff read from sessionStorage (an external store); it can
    // only be read after mount, so state is set here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReinvest(taken);
    setFormKey((k) => k + 1);
    if (type === "mf") setPicked("manual");
  }, [type]);
  const entry = getAssetEntry(type);
  if (!entry) return null;
  const onSaved = () => {
    setReinvest(null);
    setFormKey((k) => k + 1);
    setPicked("cas");
    router.push(`/portfolio/${type}`);
  };
  const onSipSaved = () => {
    setFormKey((k) => k + 1);
    setPicked("cas");
    router.push(SIPS_VIEW_HREF);
  };
  const onCancel = () => {
    setReinvest(null);
    setFormKey((k) => k + 1);
    setPicked("cas");
    router.push("/add");
  };

  return (
    <FormBusyContext.Provider value={setBusy}>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
        <div className="flex items-center gap-3">
          <AssetTypeIcon icon={entry.icon} />
          <h2 className="text-sm font-medium">{entry.title}</h2>
        </div>
        {type === "mf" && (
          <div className="flex flex-col gap-1.5">
            <ToggleGroup
              value={[mfTab]}
              disabled={busy}
              onValueChange={(v) => {
                if (v[0]) setPicked(v[0] as MfTab);
              }}
              variant="outline"
              size="sm"
              spacing={0}
              className="h-6 self-start"
            >
              <ToggleGroupItem value="cas" className="h-6 px-2 text-xs">
                Import CAS
              </ToggleGroupItem>
              <ToggleGroupItem value="manual" className="h-6 px-2 text-xs">
                Manual entry
              </ToggleGroupItem>
              <ToggleGroupItem value="sip" className="h-6 px-2 text-xs">
                Start a SIP
              </ToggleGroupItem>
            </ToggleGroup>
            <p className="text-xs text-muted-foreground">
              {mfTab === "cas"
                ? "Recommended — pulls every fund and SIP from your CAS statement, for exact XIRR."
                : mfTab === "sip"
                  ? "Adds a fixed amount to a fund on the same day every month, at that day's NAV. A SIP that started earlier is fine too."
                  : "For a single fund or one not in your CAS; XIRR is estimated from the purchase date."}
            </p>
          </div>
        )}
        <Card className="min-w-0 px-5 py-4 md:px-8 md:py-5">
          <CardContent className="min-w-0 px-0">
            {type === "mf" && mfTab === "cas" && (
              <CasImport key={`cas-${formKey}`} onImported={onSaved} />
            )}
            {type === "fd" && (
              <AssetForm
                key={formKey}
                type="fd"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "rd" && (
              <AssetForm
                key={formKey}
                type="rd"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "stock" && (
              <AssetForm
                key={formKey}
                type="stock"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "bond" && (
              <AssetForm
                key={formKey}
                type="bond"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "gold" && (
              <AssetForm
                key={formKey}
                type="gold"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "cash" && (
              <AssetForm
                key={formKey}
                type="cash"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "pf" && (
              <AssetForm
                key={formKey}
                type="pf"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "nps" && (
              <AssetForm
                key={formKey}
                type="nps"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "other" && (
              <AssetForm
                key={formKey}
                type="other"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
            {type === "mf" && mfTab === "sip" && (
              <SipForm
                key={`sip-${formKey}`}
                onSaved={onSipSaved}
                onCancel={onCancel}
              />
            )}
            {type === "mf" && mfTab === "manual" && (
              <AssetForm
                key={formKey}
                type="mf"
                reinvest={reinvest}
                onSaved={onSaved}
                onCancel={onCancel}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </FormBusyContext.Provider>
  );
}
