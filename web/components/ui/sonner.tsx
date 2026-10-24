"use client"

import { Toaster as Sonner, type ToasterProps } from "sonner"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  TriangleAlertIcon,
} from "lucide-react"

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      visibleToasts={3}
      gap={8}
      duration={3500}
      closeButton
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4 text-gain" />,
        info: <InfoIcon className="size-4 text-primary" />,
        warning: <TriangleAlertIcon className="size-4 text-amber-400" />,
        error: <CircleAlertIcon className="size-4 text-loss" />,
        loading: <Loader2Icon className="size-4 animate-spin text-muted-foreground" />,
      }}
      style={
        {
          "--normal-bg": "var(--card)",
          "--normal-text": "var(--card-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius-lg)",
          "--width": "320px",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast:
            "!rounded-lg !border !border-border !bg-card !px-3 !py-2.5 !gap-2.5 !font-sans !shadow-lg !shadow-black/30",
          title: "!text-sm !font-medium !leading-tight !text-card-foreground",
          description: "!text-xs !leading-snug !text-muted-foreground",
          icon: "!mr-0 !size-4",
          closeButton:
            "!border-border !bg-card !text-muted-foreground hover:!bg-muted hover:!text-foreground",
          success: "!border-l-2 !border-l-gain",
          error: "!border-l-2 !border-l-loss",
          info: "!border-l-2 !border-l-primary",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
