"use client";

import { AlertTriangle, RotateCw } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function ErrorState({
  title = "تعذّر الاتصال بالخادم",
  message = "حدث خطأ أثناء جلب البيانات. تأكد من تشغيل الخادم ثم أعد المحاولة.",
  onRetry,
  retryLabel = "إعادة المحاولة",
  className,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-12 text-center",
        className
      )}
      role="alert"
    >
      <AlertTriangle className="size-10 text-destructive" aria-hidden />
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
          <RotateCw className="size-4" aria-hidden />
          <span>{retryLabel}</span>
        </Button>
      )}
    </div>
  );
}
