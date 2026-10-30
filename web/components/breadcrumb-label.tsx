"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Ctx = { label: string | null; setLabel: (label: string | null) => void };

const BreadcrumbLabelContext = createContext<Ctx>({ label: null, setLabel: () => {} });

export function BreadcrumbLabelProvider({ children }: { children: ReactNode }) {
  const [label, setLabel] = useState<string | null>(null);
  return (
    <BreadcrumbLabelContext.Provider value={{ label, setLabel }}>
      {children}
    </BreadcrumbLabelContext.Provider>
  );
}

export function useBreadcrumbLabelValue() {
  return useContext(BreadcrumbLabelContext).label;
}

/** Sets the last breadcrumb's label while the calling component is mounted. */
export function useBreadcrumbLabel(label: string | null) {
  const { setLabel } = useContext(BreadcrumbLabelContext);
  useEffect(() => {
    setLabel(label);
    return () => setLabel(null);
  }, [label, setLabel]);
}
