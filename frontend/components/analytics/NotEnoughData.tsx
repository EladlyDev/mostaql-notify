import { cn } from "@/lib/utils";

/**
 * The honest "not enough data yet" state shown by an analytics section whose
 * support is below threshold (Feature 6). A fresh system is upfront about thin
 * data rather than drawing a misleading conclusion from a handful of rows.
 */
export function NotEnoughData({
  message = "لا توجد بيانات كافية بعد",
  testId,
  className,
}: {
  message?: string;
  testId?: string;
  className?: string;
}) {
  return (
    <p
      data-testid={testId}
      className={cn(
        "py-8 text-center text-sm text-muted-foreground",
        className
      )}
    >
      {message}
    </p>
  );
}
