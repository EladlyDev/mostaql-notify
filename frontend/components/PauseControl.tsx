"use client";

import { Pause, Play } from "lucide-react";

import { cn } from "@/lib/utils";
import { useControl, usePause, useResume } from "@/lib/useControl";
import { Switch } from "@/components/ui/switch";

/**
 * Self-contained watcher pause/resume toggle (mirrors Telegram /pause·/resume).
 * The switch is "on" when the watcher is active; turning it off pauses. Shows
 * the state in Arabic ("نشط" / "متوقّف"). No layout assumptions — drop it onto
 * the Home page or the board header.
 */
export function PauseControl({ className }: { className?: string }) {
  const { data, isLoading, isError } = useControl();
  const pause = usePause();
  const resume = useResume();

  const paused = data?.paused ?? false;
  const pending = isLoading || pause.isPending || resume.isPending;

  function handleChange(active: boolean) {
    if (active) {
      resume.mutate();
    } else {
      pause.mutate();
    }
  }

  return (
    <div
      className={cn("inline-flex items-center gap-2", className)}
      dir="rtl"
    >
      {paused ? (
        <Pause className="size-4 text-muted-foreground" aria-hidden />
      ) : (
        <Play className="size-4 text-primary" aria-hidden />
      )}
      <span
        className={cn(
          "text-sm font-medium",
          paused ? "text-muted-foreground" : "text-foreground"
        )}
      >
        {isError ? "غير متاح" : paused ? "متوقّف" : "نشط"}
      </span>
      <Switch
        checked={!paused}
        onCheckedChange={handleChange}
        disabled={pending || isError}
        aria-label={paused ? "استئناف المراقبة" : "إيقاف المراقبة مؤقتًا"}
      />
    </div>
  );
}
