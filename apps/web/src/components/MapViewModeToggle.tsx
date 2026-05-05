/**
 * MapViewModeToggle — segmented 2D / 3D buttons rendered as an overlay
 * on the map. Persists the choice to localStorage under STORAGE_KEY.
 */

export type MapViewMode = "2d" | "3d";

export const STORAGE_KEY = "palimpsest.map.viewMode";
const DEFAULT_MODE: MapViewMode = "3d";

export function readSavedViewMode(): MapViewMode {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    return raw === "2d" || raw === "3d" ? raw : DEFAULT_MODE;
  } catch {
    return DEFAULT_MODE;
  }
}

export function writeSavedViewMode(mode: MapViewMode): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, mode);
  } catch {
    // Ignore — localStorage may be unavailable (private mode, SSR).
  }
}

type Props = {
  mode: MapViewMode;
  onChange: (next: MapViewMode) => void;
};

export function MapViewModeToggle({ mode, onChange }: Props) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-hairline bg-parchment shadow-md">
      <ModeButton label="2D" mode="2d" active={mode === "2d"} onClick={onChange} />
      <ModeButton label="3D" mode="3d" active={mode === "3d"} onClick={onChange} />
    </div>
  );
}

function ModeButton({
  label,
  mode,
  active,
  onClick,
}: {
  label: string;
  mode: MapViewMode;
  active: boolean;
  onClick: (next: MapViewMode) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => {
        if (!active) onClick(mode);
      }}
      className={`px-3 py-1.5 font-mono text-mono uppercase tracking-wide transition-colors duration-fast focus:outline-none focus:ring-2 focus:ring-ink/40 ${
        active ? "bg-oxblood text-parchment" : "bg-parchment text-ink hover:bg-parchment-deep"
      }`}
    >
      {label}
    </button>
  );
}
