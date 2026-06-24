import type { ComponentType, ReactNode } from "react";
import { Inbox } from "lucide-react";

import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon = Inbox,
  title = "لا توجد بيانات",
  message,
  action,
  className,
}: {
  icon?: ComponentType<{ className?: string }>;
  title?: string;
  message?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-12 text-center",
        className
      )}
    >
      <Icon className="size-10 text-muted-foreground" aria-hidden />
      <h2 className="text-base font-semibold">{title}</h2>
      {message && (
        <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      )}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
