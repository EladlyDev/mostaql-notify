import type { StatusEvent } from "@/lib/types";
import { Bidi } from "@/components/Bidi";
import { formatAbsolute, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Deduped site-status transitions over a project's life (one stamped entry per
 * change). Arabic status labels; timestamps in the owner timezone. RTL flex list.
 */

const STATUS: Record<string, { label: string; dot: string }> = {
  open: { label: "مفتوح", dot: "bg-emerald-500" },
  closed: { label: "مغلق", dot: "bg-muted-foreground/60" },
  awarded: { label: "تم الإسناد", dot: "bg-sky-500" },
  unknown: { label: "غير معروف", dot: "bg-muted-foreground/40" },
};

export function StatusTimeline({ events }: { events: StatusEvent[] }) {
  const items = events ?? [];

  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        لا توجد تغييرات في الحالة بعد.
      </p>
    );
  }

  return (
    <ol dir="rtl" className="flex flex-col gap-3">
      {items.map((e, i) => {
        const cfg = STATUS[e.status] ?? {
          label: e.status,
          dot: "bg-muted-foreground/40",
        };
        return (
          <li
            key={`${e.at}-${i}`}
            data-testid="status-event"
            className="flex items-center gap-3"
          >
            <span
              className={cn("size-2.5 shrink-0 rounded-full", cfg.dot)}
              aria-hidden
            />
            <span className="text-sm font-medium">{cfg.label}</span>
            <span
              className="ms-auto text-xs text-muted-foreground"
              title={formatAbsolute(e.at)}
            >
              <Bidi>{formatRelative(e.at)}</Bidi>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
