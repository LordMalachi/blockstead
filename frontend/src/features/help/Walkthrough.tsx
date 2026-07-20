import { useCallback, useEffect, useMemo, useRef, useState, type PropsWithChildren } from "react";
import { Button } from "../../components/Button";
import { WalkthroughContext } from "./WalkthroughContext";

interface WalkthroughStep {
  title: string;
  body: string;
  target?: string;
}

const steps: WalkthroughStep[] = [
  {
    title: "A quick tour of Blockstead",
    body: "Blockstead keeps everyday server care in a few predictable workspaces. Nothing in this tour changes your server.",
  },
  {
    title: "Servers is your home base",
    body: "Open Servers to create or import a server, check its state, and enter its workspace. Each server keeps its own console, players, backups, schedule, mods, and settings.",
    target: "servers",
  },
  {
    title: "Watch the computer too",
    body: "System shows host CPU, memory, disk space, Java discovery, recent errors, and the diagnostic report you can save when asking for help.",
    target: "system",
  },
  {
    title: "Help stays close",
    body: "Return to Help for task guides, quick answers, recovery commands, and this walkthrough. Contextual question marks explain technical choices without opening another page.",
    target: "help",
  },
  {
    title: "Local by design",
    body: "Blockstead manages files and processes on this computer. It does not open your router, expose a browser shell, or send diagnostic data by itself.",
    target: "privacy",
  },
];

export function WalkthroughProvider({ children }: PropsWithChildren) {
  const [index, setIndex] = useState<number | null>(null);
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const active = index != null;
  const step = index == null ? null : steps[index];
  const close = useCallback(() => setIndex(null), []);
  const start = useCallback(() => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setIndex(0);
  }, []);
  const value = useMemo(() => ({ active, start, close }), [active, close, start]);

  useEffect(() => {
    if (!active) return;
    const shell = document.querySelector<HTMLElement>(".app-shell");
    const wasInert = shell?.hasAttribute("inert") ?? false;
    shell?.setAttribute("inert", "");
    panel.current?.focus();
    return () => {
      if (!wasInert) shell?.removeAttribute("inert");
      previousFocus.current?.focus();
    };
  }, [active]);

  useEffect(() => {
    if (active) heading.current?.focus();
  }, [active, index]);

  useEffect(() => {
    if (!step?.target) return;
    const target = document.querySelector<HTMLElement>(`[data-walkthrough="${step.target}"]`);
    target?.classList.add("walkthrough-target");
    target?.scrollIntoView?.({ block: "nearest" });
    return () => target?.classList.remove("walkthrough-target");
  }, [step]);

  useEffect(() => {
    if (!active) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key !== "Tab" || !panel.current) return;
      const controls = [...panel.current.querySelectorAll<HTMLElement>("button")];
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === heading.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [active, close]);

  return <WalkthroughContext.Provider value={value}>
    {children}
    {step && <>
      <div className="walkthrough-backdrop" aria-hidden="true" />
      <section
        className="walkthrough-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="walkthrough-title"
        tabIndex={-1}
        ref={panel}
      >
        <div className="walkthrough-copy">
          <p className="eyebrow">Quick tour · {index! + 1} of {steps.length}</p>
          <h2 id="walkthrough-title" tabIndex={-1} ref={heading}>{step.title}</h2>
          <p>{step.body}</p>
        </div>
        <div className="walkthrough-progress" aria-hidden="true">
          {steps.map((_, dot) => <i className={dot <= index! ? "complete" : ""} key={dot} />)}
        </div>
        <div className="walkthrough-actions">
          <Button className="button--quiet" onClick={close}>Exit tour</Button>
          <span />
          {index! > 0 && <Button className="button--secondary" onClick={() => setIndex(index! - 1)}>Back</Button>}
          <Button onClick={() => index === steps.length - 1 ? close() : setIndex(index! + 1)}>
            {index === steps.length - 1 ? "Finish" : "Next"}
          </Button>
        </div>
      </section>
    </>}
  </WalkthroughContext.Provider>;
}
