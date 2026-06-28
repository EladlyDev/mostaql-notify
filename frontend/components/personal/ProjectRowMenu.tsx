"use client";

import { Check, Eye, EyeOff, MoreHorizontal, Star } from "lucide-react";

import type { PersonalStatusOption, ProjectListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useHide,
  useSetStatus,
  useToggleFavorite,
  useUnhide,
} from "@/lib/usePersonal";

/**
 * Per-row quick-action menu for the projects feed: favorite, set pipeline
 * status (config-driven submenu), and hide / unhide. Wires the personal
 * mutation hooks directly so a row can be triaged without leaving the list.
 *
 * `defaultOpen` opens the menu (and the status submenu) on mount — used for
 * programmatic/preview surfaces and to make the menu deterministically
 * inspectable in tests.
 */
export function ProjectRowMenu({
  item,
  statuses,
  defaultOpen = false,
}: {
  item: ProjectListItem;
  statuses: PersonalStatusOption[];
  defaultOpen?: boolean;
}) {
  const toggleFavorite = useToggleFavorite();
  const setStatus = useSetStatus();
  const hide = useHide();
  const unhide = useUnhide();

  const favoriteLabel = item.favorite
    ? "إزالة من المفضّلة"
    : "إضافة إلى المفضّلة";
  const hideLabel = item.hidden ? "إظهار المشروع" : "إخفاء المشروع";

  return (
    <DropdownMenu defaultOpen={defaultOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="إجراءات سريعة"
          />
        }
      >
        <MoreHorizontal className="size-4" aria-hidden />
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="min-w-44">
        <DropdownMenuItem
          onClick={() => toggleFavorite.mutate(item.id)}
        >
          <Star
            className={
              item.favorite ? "fill-amber-400 text-amber-400" : undefined
            }
            aria-hidden
          />
          <span>{favoriteLabel}</span>
        </DropdownMenuItem>

        <DropdownMenuSub defaultOpen={defaultOpen}>
          <DropdownMenuSubTrigger>الحالة</DropdownMenuSubTrigger>
          <DropdownMenuContent className="min-w-40">
            {statuses.map((s) => {
              const active = item.personal_status === s.key;
              return (
                <DropdownMenuItem
                  key={s.key}
                  onClick={() =>
                    setStatus.mutate({ projectId: item.id, status: s.key })
                  }
                >
                  <Check
                    className={active ? undefined : "invisible"}
                    aria-hidden
                  />
                  <span>{s.label}</span>
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenuSub>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onClick={() =>
            item.hidden ? unhide.mutate(item.id) : hide.mutate(item.id)
          }
        >
          {item.hidden ? (
            <Eye aria-hidden />
          ) : (
            <EyeOff aria-hidden />
          )}
          <span>{hideLabel}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
