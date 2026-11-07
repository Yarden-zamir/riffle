import { useEffect, useRef, type ReactNode } from "react";

/**
 * A button in the top bar that opens a panel below the bar. A click outside or Escape closes it.
 * The panel aligns to the nearest positioned ancestor, so all header menus open at the right edge of the bar.
 */
export function HeaderMenu({ label, summary, summaryClassName = "", onOpenChange, children }: {
  label: string;
  summary: ReactNode;
  summaryClassName?: string;
  onOpenChange?: (open: boolean) => void;
  children: (close: () => void) => ReactNode;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) menu.current.open = false;
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);
  const close = () => { if (menu.current) menu.current.open = false; };

  return (
    <details ref={menu} onToggle={(event) => onOpenChange?.(event.currentTarget.open)} onKeyDown={(event) => {
      if (event.key !== "Escape") return;
      event.currentTarget.open = false;
      event.currentTarget.querySelector("summary")?.focus();
    }}>
      <summary aria-label={label} className={`flex h-11 min-w-11 cursor-pointer list-none items-center justify-center gap-1.5 rounded border-2 border-line bg-surface px-2 text-ink shadow-hard-sm [&::-webkit-details-marker]:hidden ${summaryClassName}`}>{summary}</summary>
      <div className="absolute right-0 top-full z-30 mt-2 grid w-[min(19rem,calc(100vw-2rem))] gap-3 rounded border-2 border-line bg-surface p-4 text-sm text-ink shadow-hard">
        {children(close)}
      </div>
    </details>
  );
}
