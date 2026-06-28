"use client";

import Link from "next/link";
import { GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import type { BoardCard as BoardCardData } from "@/lib/types";
import {
  formatAbsolute,
  formatBudget,
  formatHiringRate,
  formatNumber,
  formatRelative,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { Bidi } from "@/components/Bidi";
import { Badge } from "@/components/ui/badge";

const DASH = "—";

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[0.7rem] text-muted-foreground">{label}</span>
      <span className="truncate text-xs">{value}</span>
    </div>
  );
}

/**
 * A single draggable pipeline card. The whole card is keyboard-reachable via
 * the grip handle (it carries dnd-kit's listeners + ARIA attributes so it can
 * be picked up and moved with the keyboard — FR-034).
 */
export function BoardCard({ card }: { card: BoardCardData }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: card.project_id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group/board-card flex flex-col gap-2 rounded-lg bg-card p-3 text-card-foreground ring-1 ring-foreground/10",
        isDragging && "opacity-50 shadow-lg"
      )}
    >
      <div className="flex items-start gap-1.5">
        <button
          type="button"
          className="-ms-1 mt-0.5 cursor-grab touch-none rounded text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring active:cursor-grabbing"
          aria-label="اسحب لإعادة الترتيب"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" aria-hidden />
        </button>
        <Link
          href={`/projects/${card.project_id}`}
          className="min-w-0 flex-1 text-sm font-medium leading-snug hover:underline"
        >
          <Bidi className="line-clamp-2 break-words">{card.title ?? DASH}</Bidi>
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-2 ps-6">
        <Meta
          label="نسبة التوظيف"
          value={<Bidi>{formatHiringRate(card.client_hiring_rate)}</Bidi>}
        />
        <Meta
          label="العروض"
          value={
            card.bids_count != null ? (
              <Bidi>{formatNumber(card.bids_count)}</Bidi>
            ) : (
              DASH
            )
          }
        />
        <Meta
          label="الميزانية"
          value={
            <Bidi>
              {formatBudget(card.budget_min, card.budget_max, card.currency)}
            </Bidi>
          }
        />
        <Meta
          label="النشر"
          value={
            <span title={formatAbsolute(card.posted_at)}>
              <Bidi>{formatRelative(card.posted_at)}</Bidi>
            </span>
          }
        />
      </div>

      {card.tier_label || card.tags.length > 0 ? (
        <div className="flex flex-wrap gap-1 ps-6">
          {card.tier_label ? (
            <Badge variant="secondary" className="text-[0.7rem]">
              <Bidi>{card.tier_label}</Bidi>
            </Badge>
          ) : null}
          {card.tags.map((tag) => (
            <Badge key={tag} variant="outline" className="text-[0.7rem]">
              <Bidi>{tag}</Bidi>
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}
