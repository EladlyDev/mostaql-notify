import { cn } from "@/lib/utils";

export type Health = "green" | "red" | "unknown";

const STYLES: Record<Health, { dot: string; ping: string }> = {
  // Healthy: solid green with a gentle live pulse.
  green: { dot: "bg-emerald-500", ping: "bg-emerald-500/60" },
  // Failure: solid red, no calming pulse.
  red: { dot: "bg-red-500", ping: "" },
  // Unknown (no runs yet / in progress): neutral gray — deliberately NOT green
  // so it never reads as a healthy system.
  unknown: { dot: "bg-muted-foreground/50", ping: "" },
};

/**
 * Small status light driven by scraper health. `unknown` is rendered gray
 * (never green) so an unverified system is not mistaken for a healthy one.
 */
export function HealthLight({
  health,
  className,
  label,
}: {
  health: Health;
  className?: string;
  label?: string;
}) {
  const style = STYLES[health];
  return (
    <span
      className={cn("relative inline-flex size-3 shrink-0", className)}
      role="status"
      aria-label={label}
    >
      {style.ping && (
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-full opacity-75",
            style.ping
          )}
          aria-hidden
        />
      )}
      <span
        className={cn(
          "relative inline-flex size-3 rounded-full",
          style.dot
        )}
        aria-hidden
      />
    </span>
  );
}
