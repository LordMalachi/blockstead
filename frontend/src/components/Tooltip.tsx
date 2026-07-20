import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface BubblePosition {
  top: number;
  left: number;
  arrowLeft: number;
  below: boolean;
}

const VIEWPORT_GUTTER = 12;
const TRIGGER_GAP = 8;

export function Tooltip({ label, children }: { label: string; children?: ReactNode }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<BubblePosition | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const triggerHovered = useRef(false);
  const bubbleHovered = useRef(false);
  const focused = useRef(false);
  const pinned = useRef(false);
  const closeTimer = useRef<number | null>(null);
  const clearCloseTimer = useCallback(() => {
    if (closeTimer.current != null) window.clearTimeout(closeTimer.current);
    closeTimer.current = null;
  }, []);
  const show = useCallback(() => {
    clearCloseTimer();
    setOpen(true);
  }, [clearCloseTimer]);
  const dismiss = useCallback(() => {
    clearCloseTimer();
    pinned.current = false;
    setOpen(false);
  }, [clearCloseTimer]);
  const closeWhenIdle = useCallback(() => {
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => {
      if (!triggerHovered.current && !bubbleHovered.current && !focused.current && !pinned.current) setOpen(false);
    }, 120);
  }, [clearCloseTimer]);
  const placeBubble = useCallback(() => {
    if (!trigger.current || !bubble.current) return;
    const anchor = trigger.current.getBoundingClientRect();
    const box = bubble.current.getBoundingClientRect();
    if (anchor.bottom < 0 || anchor.top > window.innerHeight || anchor.right < 0 || anchor.left > window.innerWidth) {
      setOpen(false);
      return;
    }
    const aboveSpace = anchor.top - VIEWPORT_GUTTER;
    const belowSpace = window.innerHeight - anchor.bottom - VIEWPORT_GUTTER;
    const below = aboveSpace < box.height + TRIGGER_GAP && belowSpace > aboveSpace;
    const desiredTop = below ? anchor.bottom + TRIGGER_GAP : anchor.top - box.height - TRIGGER_GAP;
    const maxTop = Math.max(VIEWPORT_GUTTER, window.innerHeight - box.height - VIEWPORT_GUTTER);
    const top = Math.min(Math.max(desiredTop, VIEWPORT_GUTTER), maxTop);
    const desiredLeft = anchor.left + anchor.width / 2 - box.width / 2;
    const maxLeft = Math.max(VIEWPORT_GUTTER, window.innerWidth - box.width - VIEWPORT_GUTTER);
    const left = Math.min(Math.max(desiredLeft, VIEWPORT_GUTTER), maxLeft);
    const arrowLeft = Math.min(Math.max(anchor.left + anchor.width / 2 - left, 12), Math.max(12, box.width - 12));
    setPosition({ top, left, arrowLeft, below });
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    placeBubble();
    window.addEventListener("resize", placeBubble);
    window.addEventListener("scroll", placeBubble, true);
    return () => {
      window.removeEventListener("resize", placeBubble);
      window.removeEventListener("scroll", placeBubble, true);
    };
  }, [open, placeBubble]);

  useEffect(() => {
    if (!open) return;
    const dismissFromOutside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !bubble.current?.contains(target)) dismiss();
    };
    const dismissWithEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    document.addEventListener("pointerdown", dismissFromOutside);
    document.addEventListener("keydown", dismissWithEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissFromOutside);
      document.removeEventListener("keydown", dismissWithEscape);
    };
  }, [dismiss, open]);

  useEffect(() => () => clearCloseTimer(), [clearCloseTimer]);
  const style = position ? {
    top: position.top,
    left: position.left,
    "--tooltip-arrow-left": `${position.arrowLeft}px`,
  } as CSSProperties : undefined;
  return <span className="tooltip" onMouseEnter={() => { triggerHovered.current = true; show(); }} onMouseLeave={() => { triggerHovered.current = false; closeWhenIdle(); }}>
    <button
      ref={trigger}
      type="button"
      className="tooltip__trigger"
      aria-label={`Help: ${label}`}
      aria-describedby={open ? id : undefined}
      onFocus={() => { focused.current = true; show(); }}
      onBlur={() => { focused.current = false; closeWhenIdle(); }}
      onClick={() => {
        if (pinned.current && open) dismiss();
        else { pinned.current = true; show(); }
      }}
    >?</button>
    {open && createPortal(<span
      ref={bubble}
      className={`tooltip__bubble${position ? " tooltip__bubble--ready" : ""}${position?.below ? " tooltip__bubble--below" : ""}`}
      id={id}
      role="tooltip"
      style={style}
      onMouseEnter={() => { bubbleHovered.current = true; show(); }}
      onMouseLeave={() => { bubbleHovered.current = false; closeWhenIdle(); }}
    >{children ?? label}</span>, document.body)}
  </span>;
}
