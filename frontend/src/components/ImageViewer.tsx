import { ChevronLeft, ChevronRight, ExternalLink, Minus, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";

const MIN_SCALE = 1;
const MAX_SCALE = 8;
const STEP = 1.5;

type View = { scale: number; x: number; y: number };
const fitted: View = { scale: 1, x: 0, y: 0 };

function clampScale(scale: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

export type ImageViewerProps = {
  images: readonly string[];
  /** The index of the open image, or null when the viewer is closed. */
  index: number | null;
  onIndexChange: (index: number | null) => void;
};

/** Full-screen image viewer: zoom with buttons, wheel, pinch or double click, drag to pan, arrows to move between images. */
export function ImageViewer({ images, index, onIndexChange }: ImageViewerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [view, setView] = useState<View>(fitted);
  // Active pointers by id. One pointer pans; two pointers pinch.
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; scale: number } | null>(null);
  const image = index === null ? null : images[index] ?? null;

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (image && !element.open) element.showModal();
    if (!image && element.open) element.close();
  }, [image]);

  useEffect(() => setView(fitted), [index]);

  function zoomTo(scale: number) {
    setView((current) => {
      const next = clampScale(scale);
      // Keep the same point at the center while the scale changes. At the fitted size, the image sits centered.
      return next === MIN_SCALE ? fitted : { scale: next, x: (current.x * next) / current.scale, y: (current.y * next) / current.scale };
    });
  }

  function move(delta: number) {
    if (index === null || images.length < 2) return;
    onIndexChange((index + delta + images.length) % images.length);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDialogElement>) {
    const actions: Record<string, () => void> = {
      ArrowLeft: () => move(-1),
      ArrowRight: () => move(1),
      "+": () => zoomTo(view.scale * STEP),
      "=": () => zoomTo(view.scale * STEP),
      "-": () => zoomTo(view.scale / STEP),
      "0": () => setView(fitted),
    };
    const action = actions[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  }

  function onWheel(event: ReactWheelEvent<HTMLDivElement>) {
    zoomTo(view.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15));
  }

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale: view.scale };
    }
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const last = pointers.current.get(event.pointerId);
    if (!last) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      zoomTo((pinch.current.scale * Math.hypot(a.x - b.x, a.y - b.y)) / pinch.current.distance);
      return;
    }
    if (view.scale > MIN_SCALE) {
      setView((current) => ({ ...current, x: current.x + event.clientX - last.x, y: current.y + event.clientY - last.y }));
    }
  }

  function onPointerEnd(event: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
  }

  const control = "grid h-11 w-11 place-items-center rounded border-2 border-line bg-surface text-ink shadow-hard-sm hover:bg-raised disabled:opacity-40";

  return (
    <dialog
      aria-label="Image viewer"
      // The viewer renders inside a card, so React passes its pointer events to the card. The card swipe skips this element.
      data-no-swipe=""
      className="image-viewer m-0 h-dvh max-h-none w-screen max-w-none bg-transparent p-0 backdrop:bg-black/95"
      onClose={() => onIndexChange(null)}
      onKeyDown={onKeyDown}
      ref={dialog}
    >
      {image ? (
        <div className="flex h-full flex-col">
          <div className="flex items-center gap-2 p-3">
            <span className="sticker bg-surface text-ink">{(index ?? 0) + 1} / {images.length}</span>
            <span className="sticker bg-surface text-ink">{Math.round(view.scale * 100)}%</span>
            <div className="ml-auto flex gap-2">
              <button aria-label="Zoom out" className={control} disabled={view.scale <= MIN_SCALE} onClick={() => zoomTo(view.scale / STEP)} title="Zoom out (-)" type="button"><Minus className="h-5 w-5" /></button>
              <button aria-label="Zoom in" className={control} disabled={view.scale >= MAX_SCALE} onClick={() => zoomTo(view.scale * STEP)} title="Zoom in (+)" type="button"><Plus className="h-5 w-5" /></button>
              <button aria-label="Fit to screen" className={control} onClick={() => setView(fitted)} title="Fit to screen (0)" type="button"><RotateCcw className="h-5 w-5" /></button>
              <a aria-label="Open the original image" className={control} href={image} rel="noopener noreferrer" target="_blank" title="Open the original image"><ExternalLink className="h-5 w-5" /></a>
              <button aria-label="Close" autoFocus className={control} onClick={() => onIndexChange(null)} title="Close (Esc)" type="button"><X className="h-5 w-5" /></button>
            </div>
          </div>
          <div
            className={`relative min-h-0 flex-1 touch-none overflow-hidden ${view.scale > MIN_SCALE ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"}`}
            onDoubleClick={() => (view.scale > MIN_SCALE ? setView(fitted) : zoomTo(2.5))}
            onPointerCancel={onPointerEnd}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerEnd}
            onWheel={onWheel}
          >
            <img
              alt=""
              className="pointer-events-none absolute inset-0 m-auto max-h-full max-w-full select-none object-contain"
              draggable={false}
              referrerPolicy="no-referrer"
              src={image}
              style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
            />
            {images.length > 1 ? (
              <>
                <button aria-label="Previous image" className={`${control} absolute left-3 top-1/2 -translate-y-1/2`} onClick={() => move(-1)} onPointerDown={(event) => event.stopPropagation()} title="Previous image (←)" type="button"><ChevronLeft className="h-6 w-6" /></button>
                <button aria-label="Next image" className={`${control} absolute right-3 top-1/2 -translate-y-1/2`} onClick={() => move(1)} onPointerDown={(event) => event.stopPropagation()} title="Next image (→)" type="button"><ChevronRight className="h-6 w-6" /></button>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
