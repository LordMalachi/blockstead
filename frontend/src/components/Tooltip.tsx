import { useId, useState, type KeyboardEvent, type ReactNode } from "react";

export function Tooltip({ label, children }: { label: string; children?: ReactNode }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const closeWithEscape = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    setOpen(false);
  };
  return <span className={`tooltip${open ? " tooltip--open" : ""}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button
      type="button"
      className="tooltip__trigger"
      aria-label={`Help: ${label}`}
      aria-describedby={id}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={closeWithEscape}
    >?</button>
    <span className="tooltip__bubble" id={id} role="tooltip" aria-hidden={!open}>
      {children ?? label}
    </span>
  </span>;
}
