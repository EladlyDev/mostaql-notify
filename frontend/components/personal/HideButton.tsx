"use client";

import { Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Hide / unhide toggle. Purely presentational — the parent owns the mutation
 * and passes the current `hidden` state plus an `onToggle` handler.
 */
export function HideButton({
  hidden,
  onToggle,
  size = "sm",
  className,
  disabled,
}: {
  hidden: boolean;
  onToggle: () => void;
  size?: "sm" | "default" | "xs";
  className?: string;
  disabled?: boolean;
}) {
  const label = hidden ? "إظهار" : "إخفاء";

  return (
    <Button
      type="button"
      variant="ghost"
      size={size}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onToggle}
      className={className}
    >
      {hidden ? (
        <Eye className="size-4" aria-hidden />
      ) : (
        <EyeOff className="size-4" aria-hidden />
      )}
      <span>{label}</span>
    </Button>
  );
}
