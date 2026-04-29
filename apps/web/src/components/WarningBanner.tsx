/**
 * WarningBanner — verifier failures, plan_walk failures, turn-cap hits.
 *
 * Spec: design brief §4.8. Inline banner with an ochre left rule, never
 * a destructive red — these are soft warnings the demo wants visible.
 */

import { AlertTriangleIcon } from "./Icon";

type Props = {
  warnings: string[];
};

export function WarningBanner({ warnings }: Props) {
  if (warnings.length === 0) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      className="space-y-1 border-t border-hairline border-l-[3px] border-l-ochre bg-parchment-deep px-4 py-3"
    >
      {warnings.map((w, i) => (
        <p key={i} className="flex items-start gap-2 text-small text-ink">
          <AlertTriangleIcon className="mt-[3px] shrink-0 text-base text-ochre" />
          <span>{w}</span>
        </p>
      ))}
    </div>
  );
}
