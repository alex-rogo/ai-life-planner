import type { ReactNode } from "react";
export type IconName =
  | "calendar"
  | "grid"
  | "check"
  | "sparkles"
  | "plus"
  | "left"
  | "right"
  | "close"
  | "arrow"
  | "clock"
  | "panel"
  | "sun"
  | "home"
  | "bell"
  | "send"
  | "edit"
  | "trash"
  | "settings";
const paths: Record<IconName, ReactNode> = {
  settings: (
    <>
      <path d="m9 3 1-2h4l1 2 3 2 2 0 2 4-2 2v3l2 2-2 4-3-1-2 2-1 2h-4l-1-2-3-2-2 1-2-4 2-2v-3L2 9l2-4 2 0Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  home: <path d="m3 10 9-7 9 7v11h-6v-7H9v7H3Z" />,
  bell: (
    <>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
    </>
  ),
  send: <path d="m3 3 18 9-18 9 4-9Zm4 9h14" />,
  edit: (
    <>
      <path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-4-4L5 15Z" />
    </>
  ),
  trash: (
    <>
      <path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M7 3v4m10-4v4M3 11h18" />
    </>
  ),
  grid: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M9 3v18M3 9h6" />
    </>
  ),
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  sparkles: (
    <>
      <path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z" />
      <path d="M20 2v4m-2-2h4M3 18v4m-2-2h4" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  left: <path d="m14 5-7 7 7 7" />,
  right: <path d="m10 5 7 7-7 7" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  panel: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M15 3v18" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1" />
    </>
  ),
};
export default function Icon({
  name,
  size = 20,
}: {
  name: IconName;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
