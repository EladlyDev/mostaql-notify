import type { ComponentType, ReactNode } from "react";

import { cn } from "@/lib/utils";
import { Bidi } from "@/components/Bidi";
import { Card, CardContent } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";

/**
 * At-a-glance figure card. The numeric value is bidi-isolated via
 * `formatNumber` so Arabic-Indic digits sit correctly in RTL text.
 */
export function StatCard({
  label,
  value,
  icon: Icon,
  hint,
  className,
}: {
  label: string;
  value: number;
  icon?: ComponentType<{ className?: string }>;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("justify-between", className)}>
      <CardContent className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-3xl font-semibold tracking-tight tabular-nums">
            <Bidi>{formatNumber(value)}</Bidi>
          </p>
          {hint && (
            <p className="text-xs text-muted-foreground">{hint}</p>
          )}
        </div>
        {Icon && (
          <span className="rounded-lg bg-muted/60 p-2 text-muted-foreground">
            <Icon className="size-5" />
          </span>
        )}
      </CardContent>
    </Card>
  );
}
