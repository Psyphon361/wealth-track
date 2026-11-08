"use client";

import { createContext, useContext, useEffect } from "react";

/** True while the surrounding form is saving; fields read it to lock themselves. */
export const FormDisabledContext = createContext(false);

export function useFormDisabled(): boolean {
  return useContext(FormDisabledContext);
}

/** Names of the fields locked on their own (a holding sold in part); the rest stay editable. */
export const ReadOnlyFieldsContext = createContext<readonly string[]>([]);

/** True when this field is read-only because the holding was sold in part. */
export function useFieldReadOnly(name: string): boolean {
  return useContext(ReadOnlyFieldsContext).includes(name);
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
