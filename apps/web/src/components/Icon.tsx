/**
 * Inline SVG icons used by the V1 UI.
 *
 * Kept dependency-free and small — adding lucide-react means another
 * bundle. The icons here all share a 1.5-stroke style on a 24×24 viewbox so
 * they sit inside `1em` without distorting.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const baseProps = {
  width: "1em",
  height: "1em",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export function ExternalLinkIcon(props: IconProps) {
  return (
    <svg {...baseProps} aria-hidden="true" {...props}>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
    </svg>
  );
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <svg {...baseProps} aria-hidden="true" {...props}>
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </svg>
  );
}

export function AlertTriangleIcon(props: IconProps) {
  return (
    <svg {...baseProps} aria-hidden="true" {...props}>
      <path d="M12 4 2 20h20L12 4Z" />
      <path d="M12 10v4" />
      <path d="M12 18h.01" />
    </svg>
  );
}

export function SpinnerIcon(props: IconProps) {
  return (
    <svg {...baseProps} aria-hidden="true" className={`animate-spin ${props.className ?? ""}`} {...props}>
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

export function MapPinIcon(props: IconProps) {
  return (
    <svg {...baseProps} aria-hidden="true" {...props}>
      <path d="M12 22s7-7.5 7-13a7 7 0 0 0-14 0c0 5.5 7 13 7 13Z" />
      <circle cx="12" cy="9" r="2.5" />
    </svg>
  );
}

export function CrosshairIcon(props: IconProps) {
  return (
    <svg {...baseProps} aria-hidden="true" {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
    </svg>
  );
}
