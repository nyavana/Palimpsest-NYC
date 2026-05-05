/**
 * SettingsButton — gear icon that opens the SettingsModal,
 * paired with a small status pill ("server keys" / "your keys" / "no keys").
 */

import { GearIcon } from "./Icon";

export type SettingsStatus = "server" | "user" | "missing";

type Props = {
  status: SettingsStatus;
  onClick: () => void;
};

export function SettingsButton({ status, onClick }: Props) {
  const pill = pillCopy(status);
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-mono uppercase tracking-wide ${pillClass(
          status,
        )}`}
        aria-live="polite"
      >
        {pill}
      </span>
      <button
        type="button"
        onClick={onClick}
        aria-label="LLM settings"
        title="LLM settings"
        className="flex h-8 w-8 items-center justify-center rounded text-ink-muted hover:bg-parchment-deep hover:text-ink focus:outline-none focus:ring-2 focus:ring-ink/40"
      >
        <GearIcon className="text-lg" />
      </button>
    </div>
  );
}

function pillCopy(status: SettingsStatus): string {
  switch (status) {
    case "server":
      return "server keys";
    case "user":
      return "your keys";
    case "missing":
      return "no keys";
  }
}

function pillClass(status: SettingsStatus): string {
  switch (status) {
    case "server":
      return "border-emerald-300 bg-emerald-50 text-emerald-800";
    case "user":
      return "border-sky-300 bg-sky-50 text-sky-800";
    case "missing":
      return "border-oxblood/40 bg-oxblood/10 text-oxblood";
  }
}
