import type { LucideIcon } from "lucide-react";
import {
  Clock,
  Zap,
  Trophy,
  SlidersHorizontal,
  TrendingDown,
  Lightbulb,
} from "lucide-react";

import type { Tip } from "@/lib/types";
import { Bidi } from "@/components/Bidi";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { NotEnoughData } from "@/components/analytics/NotEnoughData";

// Each derived tip carries a stable key; map it to an at-a-glance icon. Any
// unknown / future key falls back to the generic "insight" bulb.
const TIP_ICONS: Record<string, LucideIcon> = {
  peak_window: Clock,
  bid_speed: Zap,
  win_timing: Trophy,
  score_threshold: SlidersHorizontal,
  budget_fallback: TrendingDown,
};

/**
 * The plain-language takeaways section (Feature 6). Each tip is a full Arabic
 * sentence already backed by its own numbers; we just give it an icon and keep
 * any embedded digits bidi-tidy inside the surrounding RTL text.
 */
export function TipsPanel({ tips }: { tips: Tip[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>نصائح وملاحظات</CardTitle>
        <CardDescription>
          مستخلصة من بياناتك — كل نصيحة مدعومة بأرقامها
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tips.length === 0 ? (
          <NotEnoughData testId="tips-empty" message="لا توجد نصائح كافية بعد" />
        ) : (
          <ol data-testid="tips-panel" className="flex flex-col gap-3">
            {tips.map((tip) => {
              const Icon = TIP_ICONS[tip.key] ?? Lightbulb;
              return (
                <li
                  key={tip.key}
                  data-testid="tip-item"
                  className="flex items-start gap-3 text-sm leading-relaxed"
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <Bidi className="min-w-0 flex-1 pt-1.5">{tip.text}</Bidi>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
