/**
 * LoadingSkeleton — three pulsing hairline bars shown while the narration
 * is streaming but text hasn't arrived yet. Honors prefers-reduced-motion.
 */

export function LoadingSkeleton() {
  return (
    <div role="status" aria-label="Generating narration" className="space-y-2">
      <span className="block h-3 w-11/12 rounded bg-hairline motion-safe:animate-pulse" />
      <span className="block h-3 w-10/12 rounded bg-hairline motion-safe:animate-pulse" />
      <span className="block h-3 w-9/12 rounded bg-hairline motion-safe:animate-pulse" />
    </div>
  );
}
