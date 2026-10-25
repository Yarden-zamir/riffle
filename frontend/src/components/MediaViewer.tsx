import { ChevronLeft, ChevronRight, ExternalLink, Minus, Pause, Play, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";

import type { CardMedia } from "../lib/changes";

const MIN_SCALE = 1;
const MAX_SCALE = 8;
const STEP = 1.5;
// A GIF frame without a duration plays for this long, as browsers do.
const DEFAULT_FRAME_MS = 100;

type View = { scale: number; x: number; y: number };
const fitted: View = { scale: 1, x: 0, y: 0 };

function clampScale(scale: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

function clock(seconds: number) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** The position of a video or GIF, and the commands that move it. */
type Playback = {
  playing: boolean;
  position: number;
  end: number;
  /** The text next to the scrubber, such as "0:03 / 0:12" or "Frame 4 / 40". */
  label: string;
  toggle: () => void;
  seek: (position: number) => void;
  step: (delta: number) => void;
};

const control = "grid h-11 w-11 shrink-0 place-items-center rounded border-2 border-line bg-surface text-ink shadow-hard-sm hover:bg-raised disabled:opacity-40";

function Scrubber({ playback }: { playback: Playback }) {
  return (
    <div className="flex items-center gap-3 p-3">
      <button aria-label={playback.playing ? "Pause" : "Play"} className={control} onClick={playback.toggle} title={playback.playing ? "Pause (Space)" : "Play (Space)"} type="button">
        {playback.playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
      </button>
      <input
        aria-label="Position"
        className="h-2 min-w-0 flex-1 cursor-pointer accent-accent"
        max={playback.end}
        min={0}
        onChange={(event) => playback.seek(Number(event.target.value))}
        step="any"
        type="range"
        value={playback.position}
      />
      <span className="sticker shrink-0 bg-surface text-ink tabular-nums">{playback.label}</span>
    </div>
  );
}

function VideoStage({ url, onPlayback }: { url: string; onPlayback: (playback: Playback | null) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState({ playing: false, position: 0, end: 0 });

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    const sync = () => setState({ playing: !element.paused, position: element.currentTime, end: Number.isFinite(element.duration) ? element.duration : 0 });
    const events = ["play", "pause", "timeupdate", "loadedmetadata", "seeked"] as const;
    for (const name of events) element.addEventListener(name, sync);
    // The click that opened the viewer allows playback. If the browser still refuses, the video waits paused.
    element.play().catch(sync);
    return () => { for (const name of events) element.removeEventListener(name, sync); };
  }, [url]);

  useEffect(() => {
    const element = video.current;
    if (!element) return onPlayback(null);
    onPlayback({
      ...state,
      label: `${clock(state.position)} / ${clock(state.end)}`,
      toggle: () => void (element.paused ? element.play().catch(() => undefined) : element.pause()),
      seek: (position) => { element.currentTime = position; },
      step: (delta) => { element.pause(); element.currentTime = Math.min(state.end, Math.max(0, element.currentTime + delta / 10)); },
    });
  }, [state, onPlayback]);

  return <video className="max-h-full max-w-full" loop playsInline preload="auto" ref={video} src={url} />;
}

function GifStage({ item, loadGif, onPlayback }: { item: CardMedia; loadGif: (item: CardMedia) => Promise<Blob>; onPlayback: (playback: Playback | null) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const decoder = useRef<ImageDecoder | null>(null);
  const durations = useRef<number[]>([]);
  const [frames, setFrames] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setFrames(null);
    setFailed(false);
    setFrame(0);
    setPlaying(true);
    if (typeof ImageDecoder === "undefined") {
      setFailed(true);
      return;
    }
    (async () => {
      try {
        const data = await loadGif(item);
        const next = new ImageDecoder({ data: await data.arrayBuffer(), type: "image/gif" });
        await next.tracks.ready;
        const count = next.tracks.selectedTrack?.frameCount ?? 0;
        if (cancelled) return next.close();
        if (count < 1) throw new Error("The GIF has no frames");
        decoder.current = next;
        durations.current = Array.from({ length: count }, () => DEFAULT_FRAME_MS);
        setFrames(count);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      decoder.current?.close();
      decoder.current = null;
    };
  }, [item, loadGif]);

  // Draw the current frame. Decoding also gives the frame duration, which playback uses.
  useEffect(() => {
    const source = decoder.current;
    const target = canvas.current;
    if (!source || !target || frames === null) return;
    let cancelled = false;
    source.decode({ frameIndex: frame }).then(({ image }) => {
      if (!cancelled) {
        if (target.width !== image.displayWidth || target.height !== image.displayHeight) {
          target.width = image.displayWidth;
          target.height = image.displayHeight;
        }
        target.getContext("2d")?.drawImage(image, 0, 0);
        if (image.duration) durations.current[frame] = Math.max(20, image.duration / 1000);
      }
      image.close();
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [frame, frames]);

  useEffect(() => {
    if (!playing || frames === null) return;
    const timer = window.setTimeout(() => setFrame((current) => (current + 1) % frames), durations.current[frame] ?? DEFAULT_FRAME_MS);
    return () => window.clearTimeout(timer);
  }, [playing, frame, frames]);

  useEffect(() => {
    if (frames === null) return onPlayback(null);
    onPlayback({
      playing,
      position: frame,
      end: frames - 1,
      label: `Frame ${frame + 1} / ${frames}`,
      toggle: () => setPlaying((current) => !current),
      seek: (position) => { setPlaying(false); setFrame(Math.round(position)); },
      step: (delta) => { setPlaying(false); setFrame((current) => (current + delta + frames) % frames); },
    });
  }, [playing, frame, frames, onPlayback]);

  // Without frame access, the GIF plays as an ordinary image and has no scrubber.
  if (failed) return <img alt="" className="max-h-full max-w-full select-none" draggable={false} referrerPolicy="no-referrer" src={item.url} />;
  return <canvas className="max-h-full max-w-full" ref={canvas} />;
}

export type MediaViewerProps = {
  media: readonly CardMedia[];
  /** The position of the open item in `media`, or null when the viewer is closed. */
  index: number | null;
  onIndexChange: (index: number | null) => void;
  /** The bytes of a GIF from this site, so its frames can be read. */
  loadGif: (item: CardMedia) => Promise<Blob>;
};

/**
 * Full-screen viewer for the images, GIFs and videos of a card. Zoom with buttons, wheel, pinch or double click,
 * drag to pan, and move between items with arrows. Videos and GIFs have a play button and a scrubber.
 */
export function MediaViewer({ media, index, onIndexChange, loadGif }: MediaViewerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [view, setView] = useState<View>(fitted);
  const [playback, setPlayback] = useState<Playback | null>(null);
  // Active pointers by id. One pointer pans; two pointers pinch.
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; scale: number } | null>(null);
  const item = index === null ? null : media[index] ?? null;

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (item && !element.open) element.showModal();
    if (!item && element.open) element.close();
  }, [item]);

  useEffect(() => {
    setView(fitted);
    setPlayback(null);
  }, [index]);

  function zoomTo(scale: number) {
    setView((current) => {
      const next = clampScale(scale);
      // Keep the same point at the center while the scale changes. At the fitted size, the item sits centered.
      return next === MIN_SCALE ? fitted : { scale: next, x: (current.x * next) / current.scale, y: (current.y * next) / current.scale };
    });
  }

  function move(delta: number) {
    if (index === null || media.length < 2) return;
    onIndexChange((index + delta + media.length) % media.length);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDialogElement>) {
    // The scrubber is a range input: it takes its own arrow keys.
    if (event.target instanceof HTMLInputElement) return;
    const actions: Record<string, () => void> = {
      ArrowLeft: () => move(-1),
      ArrowRight: () => move(1),
      "+": () => zoomTo(view.scale * STEP),
      "=": () => zoomTo(view.scale * STEP),
      "-": () => zoomTo(view.scale / STEP),
      "0": () => setView(fitted),
      ...(playback ? { " ": playback.toggle, ",": () => playback.step(-1), ".": () => playback.step(1) } : {}),
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

  return (
    <dialog
      aria-label="Media viewer"
      // The viewer renders inside a card, so React passes its pointer events to the card. The card swipe skips this element.
      data-no-swipe=""
      className="image-viewer m-0 h-dvh max-h-none w-screen max-w-none bg-[#0b0a12] p-0 text-ink backdrop:bg-black"
      onClose={() => onIndexChange(null)}
      onKeyDown={onKeyDown}
      ref={dialog}
    >
      {item ? (
        <div className="flex h-full flex-col">
          <div className="flex items-center gap-2 p-3">
            <span className="sticker bg-surface text-ink">{(index ?? 0) + 1} / {media.length}</span>
            <span className="sticker bg-surface text-ink">{Math.round(view.scale * 100)}%</span>
            <div className="ml-auto flex gap-2">
              <button aria-label="Zoom out" className={control} disabled={view.scale <= MIN_SCALE} onClick={() => zoomTo(view.scale / STEP)} title="Zoom out (-)" type="button"><Minus className="h-5 w-5" /></button>
              <button aria-label="Zoom in" className={control} disabled={view.scale >= MAX_SCALE} onClick={() => zoomTo(view.scale * STEP)} title="Zoom in (+)" type="button"><Plus className="h-5 w-5" /></button>
              <button aria-label="Fit to screen" className={control} onClick={() => setView(fitted)} title="Fit to screen (0)" type="button"><RotateCcw className="h-5 w-5" /></button>
              <a aria-label="Open the original" className={control} href={item.url} rel="noopener noreferrer" target="_blank" title="Open the original"><ExternalLink className="h-5 w-5" /></a>
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
            <div
              className="pointer-events-none absolute inset-0 grid select-none place-items-center [&>*]:object-contain"
              style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
            >
              {item.kind === "video" ? (
                <VideoStage key={item.url} onPlayback={setPlayback} url={item.url} />
              ) : item.kind === "gif" ? (
                <GifStage item={item} key={item.url} loadGif={loadGif} onPlayback={setPlayback} />
              ) : (
                <img alt="" className="max-h-full max-w-full" draggable={false} referrerPolicy="no-referrer" src={item.url} />
              )}
            </div>
            {media.length > 1 ? (
              <>
                <button aria-label="Previous" className={`${control} absolute left-3 top-1/2 -translate-y-1/2`} onClick={() => move(-1)} onPointerDown={(event) => event.stopPropagation()} title="Previous (←)" type="button"><ChevronLeft className="h-6 w-6" /></button>
                <button aria-label="Next" className={`${control} absolute right-3 top-1/2 -translate-y-1/2`} onClick={() => move(1)} onPointerDown={(event) => event.stopPropagation()} title="Next (→)" type="button"><ChevronRight className="h-6 w-6" /></button>
              </>
            ) : null}
          </div>
          {playback ? <Scrubber playback={playback} /> : null}
        </div>
      ) : null}
    </dialog>
  );
}
