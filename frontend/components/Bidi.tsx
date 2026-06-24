import type { ReactNode } from "react";

/**
 * Renders its children inside a `<bdi>` element so mixed-direction content
 * (numbers, URLs, Latin in Arabic text) stays isolated and readable in RTL.
 */
export function Bidi({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <bdi className={className}>{children}</bdi>;
}
