/**
 * Composer — the textarea + Ask button that opens an agent session.
 *
 * Per design.md §12.5.2: 44px min height, oxblood CTA, focus rings on parchment,
 * Ctrl/Cmd+Enter submits. Plain Enter inserts a newline so multi-line questions
 * paste cleanly.
 */

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ArrowUpIcon, SpinnerIcon } from "./Icon";

type ComposerProps = {
  busy: boolean;
  onAsk: (question: string) => void;
  onCancel: () => void;
};

const MIN_HEIGHT_PX = 44;
const MAX_HEIGHT_PX = 144; // ~6 lines at our line-height

export function Composer({ busy, onAsk, onCancel }: ComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Autosize textarea: shrink to scrollHeight, capped.
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta === null) return;
    ta.style.height = `${MIN_HEIGHT_PX}px`;
    const next = Math.min(ta.scrollHeight, MAX_HEIGHT_PX);
    ta.style.height = `${Math.max(MIN_HEIGHT_PX, next)}px`;
  }, [value]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (busy) {
      onCancel();
      return;
    }
    const q = value.trim();
    if (q.length === 0) return;
    onAsk(q);
    setValue("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (!busy) {
        const q = value.trim();
        if (q.length > 0) {
          onAsk(q);
          setValue("");
        }
      }
    }
  };

  return (
    <form className="flex items-end gap-2 border-t border-hairline px-4 py-3" onSubmit={handleSubmit}>
      <label htmlFor="palimpsest-composer" className="sr-only">
        Ask Palimpsest a question
      </label>
      <textarea
        ref={textareaRef}
        id="palimpsest-composer"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Take me on a walk near Columbia…"
        rows={1}
        className="flex-1 resize-none rounded border border-hairline bg-parchment px-3 py-2 text-body text-ink placeholder:text-ink-muted focus:border-ink/30 focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment"
        style={{ minHeight: `${MIN_HEIGHT_PX}px`, maxHeight: `${MAX_HEIGHT_PX}px` }}
      />
      <button
        type="submit"
        className={`flex h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded px-4 text-small font-medium transition-colors duration-fast ease-out focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment ${
          busy
            ? "bg-ink-soft text-parchment hover:bg-ink"
            : "bg-oxblood text-parchment hover:bg-oxblood-hover"
        }`}
        aria-label={busy ? "Cancel" : "Ask"}
      >
        {busy ? (
          <>
            <SpinnerIcon className="text-base" />
            <span className="hidden sm:inline">Cancel</span>
          </>
        ) : (
          <>
            <span className="hidden sm:inline">Ask</span>
            <ArrowUpIcon className="text-base" />
          </>
        )}
      </button>
    </form>
  );
}
