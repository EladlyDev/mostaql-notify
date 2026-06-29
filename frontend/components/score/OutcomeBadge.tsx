import { Badge } from "@/components/ui/badge";

/**
 * Final-disposition pill for a project's `outcome`
 * (`open | closed_no_hire | hired | unknown`). Arabic-first labels with a
 * colour that reads at a glance; `null` (never scored / tracked) renders nothing.
 */

const OUTCOME: Record<string, { label: string; className: string }> = {
  open: {
    label: "مفتوح",
    className:
      "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  },
  hired: {
    label: "تم التوظيف",
    className:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  },
  closed_no_hire: {
    label: "أُغلق دون توظيف",
    className:
      "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  },
  unknown: {
    label: "غير معروف",
    className: "bg-muted text-muted-foreground",
  },
};

export function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return null;

  const cfg = OUTCOME[outcome] ?? {
    label: outcome,
    className: "bg-muted text-muted-foreground",
  };

  return (
    <Badge className={cfg.className} aria-label={`المصير: ${cfg.label}`}>
      {cfg.label}
    </Badge>
  );
}
