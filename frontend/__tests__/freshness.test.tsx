/// <reference types="vitest/globals" />
import { render } from "@testing-library/react";

import type { Freshness } from "@/lib/types";
import { FreshnessBadge } from "@/components/score/FreshnessBadge";

describe("FreshnessBadge", () => {
  const CASES: [Freshness, string][] = [
    ["green", "bg-emerald-500"],
    ["yellow", "bg-amber-500"],
    ["red", "bg-red-500"],
  ];

  it.each(CASES)(
    "renders a %s dot carrying the matching colour + an Arabic title",
    (freshness, colourClass) => {
      const { container } = render(<FreshnessBadge freshness={freshness} />);

      const badge = container.querySelector(`[data-freshness="${freshness}"]`);
      expect(badge).not.toBeNull();
      // Arabic title for hover/accessibility.
      expect(badge?.getAttribute("title")).toBeTruthy();
      // The inner dot swatch carries the colour token.
      const dot = badge?.firstElementChild as HTMLElement | null;
      expect(dot?.className).toContain(colourClass);
    }
  );

  it("renders nothing when freshness is null", () => {
    const { container } = render(<FreshnessBadge freshness={null} />);
    expect(container.firstChild).toBeNull();
  });
});
