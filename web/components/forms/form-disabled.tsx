"use client";

import { createContext, useContext, useEffect } from "react";

/** True while the surrounding form is saving; fields read it to lock themselves. */
export const FormDisabledContext = createContext(false);

export function useFormDisabled(): boolean {
  return useContext(FormDisabledContext);
}

/** Lets a page learn that a form or import below it is busy (e.g. to lock tabs). */
export const FormBusyContext = createContext<(busy: boolean) => void>(
  () => {},
);

/** Reports `busy` to the nearest FormBusyContext provider while mounted. */
export function useReportBusy(busy: boolean) {
  const report = useContext(FormBusyContext);
  useEffect(() => {
    report(busy);
    return () => report(false);
  }, [busy, report]);
}
