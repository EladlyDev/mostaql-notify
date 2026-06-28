"use client";

import { Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useToggleFavorite } from "@/lib/usePersonal";

const LABEL = "مفضّل";

/**
 * Star toggle that flips a project's `favorite` flag through the dedicated
 * toggle-favorite mutation. Filled star when favorited, outline otherwise.
 */
export function FavoriteToggle({
  projectId,
  favorite,
  size = "icon",
  className,
}: {
  projectId: number;
  favorite: boolean;
  size?: "icon" | "icon-sm" | "icon-xs";
  className?: string;
}) {
  const toggle = useToggleFavorite();

  return (
    <Button
      type="button"
      variant="ghost"
      size={size}
      aria-label={LABEL}
      aria-pressed={favorite}
      title={LABEL}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate(projectId)}
      className={className}
    >
      <Star
        className={cn(
          "size-4 transition-colors",
          favorite
            ? "fill-amber-400 text-amber-400"
            : "text-muted-foreground"
        )}
        aria-hidden
      />
    </Button>
  );
}
