"use client";

import type { PersonalStatusOption } from "@/lib/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Pipeline-stage select. The configured stages are PASSED IN (`statuses`),
 * never fetched here, so the same options drive the feed, board, and detail.
 */
export function StatusSelect({
  value,
  statuses,
  onChange,
  id,
  size = "default",
  className,
  disabled,
}: {
  value: string;
  statuses: PersonalStatusOption[];
  onChange: (key: string) => void;
  id?: string;
  size?: "sm" | "default";
  className?: string;
  disabled?: boolean;
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => onChange(v as string)}
      disabled={disabled}
    >
      <SelectTrigger id={id} size={size} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {statuses.map((s) => (
          <SelectItem key={s.key} value={s.key}>
            {s.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
