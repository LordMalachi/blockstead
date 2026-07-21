import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type UpdateStatus } from "../../api/client";
import { Button } from "../../components/Button";

/** Slow on purpose: nothing here changes minute to minute. */
const POLL_MS = 60_000;
/** While an update is installing the dashboard is about to restart, so watch closely. */
const INSTALLING_POLL_MS = 5_000;

function banner(status: UpdateStatus): { tone: string; message: string } | null {
  if (status.installing) {
    return {
      tone: "success",
      message:
        "Blockstead is installing an update. The dashboard will restart on its own "
        + "in a few minutes — your worlds and settings are kept.",
    };
  }
  if (status.decision === "waiting_for_players") {
    return {
      tone: "warning",
      message:
        `A newer Blockstead (${status.latest?.short_commit ?? "update"}) is ready. `
        + "It will install once the Minecraft server is empty, so nobody is "
        + "disconnected mid-game.",
    };
  }
  const currentFailure = status.last_result?.state === "failed"
    && (!status.latest || status.last_result.commit === status.latest.commit);
  if (status.decision === "failed" || currentFailure) {
    if (status.last_result?.retryable) {
      const retryAt = status.last_result.retry_after
        ? ` Next automatic try: ${new Date(status.last_result.retry_after).toLocaleString()}.`
        : " Blockstead will try again automatically.";
      return {
        tone: "warning",
        message: `${status.last_result.detail}${retryAt}`,
      };
    }
    return {
      tone: "error",
      message: `${status.last_result?.detail ?? "The latest Blockstead update was rolled back."} Open System to review it or retry when you are ready.`,
    };
  }
  if (status.decision === "manual" && status.latest) {
    return {
      tone: "warning",
      message: status.supported
        ? `A newer Blockstead (${status.latest.short_commit}) is available. Automatic updates are off; open System when you are ready to install it.`
        : `A newer Blockstead (${status.latest.short_commit}) is available. This copy cannot update itself, so install it the way you set it up.`,
    };
  }
  return null;
}

/**
 * The app-wide update notice: a quiet banner while something is pending, and a
 * dialog after an update has landed telling the owner which version they are on.
 *
 * The dialog only ever follows a real update. A first-ever start records the
 * build it is already running without saying anything, so nobody is greeted by
 * a changelog for software they just installed.
 */
export function UpdateNotice() {
  const client = useQueryClient();
  const status = useQuery({
    queryKey: ["updates"],
    queryFn: () => api<UpdateStatus>("/updates/status"),
    refetchInterval: query =>
      query.state.data?.installing ? INSTALLING_POLL_MS : POLL_MS,
  });
  const acknowledge = useMutation({
    mutationFn: () => api<UpdateStatus>("/updates/acknowledge", { method: "POST" }),
    onSuccess: data => client.setQueryData(["updates"], data),
  });

  const announcement = status.data?.announcement ?? null;
  const dismiss = useCallback(() => acknowledge.mutate(), [acknowledge]);

  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  // Same handling as the guided tour: the rest of the page is made inert while
  // the dialog is open, and focus goes back where it came from afterwards.
  useEffect(() => {
    if (!announcement) return;
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const shell = document.querySelector<HTMLElement>(".app-shell");
    const wasInert = shell?.hasAttribute("inert") ?? false;
    shell?.setAttribute("inert", "");
    heading.current?.focus();
    return () => {
      if (!wasInert) shell?.removeAttribute("inert");
      previousFocus.current?.focus();
    };
  }, [announcement]);

  useEffect(() => {
    if (!announcement) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { dismiss(); return; }
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
  }, [announcement, dismiss]);

  if (!status.data) return null;
  const notice = banner(status.data);

  return <>
    {notice && <div className={`${notice.tone} page-notice`} role="status">{notice.message}</div>}
    {/* The dialog is portalled out of the shell on purpose. Making the shell
        inert is what keeps the page behind a modal unreachable, and a dialog
        rendered inside the shell would silently disable its own buttons. */}
    {announcement && createPortal(<>
      <div className="walkthrough-backdrop" aria-hidden="true" />
      <section
        className="walkthrough-panel update-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="update-title"
        tabIndex={-1}
        ref={panel}
      >
        <div className="walkthrough-copy">
          <p className="eyebrow">Blockstead updated itself</p>
          <h2 id="update-title" tabIndex={-1} ref={heading}>You are on {announcement.label}</h2>
          <p>
            Blockstead found a newer version and installed it. Your worlds, settings,
            administrator accounts, and backups were all kept.
          </p>
          {announcement.summary && <p><strong>What changed:</strong> {announcement.summary}</p>}
        </div>
        <div className="walkthrough-actions">
          <span />
          <Button onClick={dismiss} disabled={acknowledge.isPending}>
            {acknowledge.isPending ? "Closing…" : "Got it"}
          </Button>
        </div>
      </section>
    </>, document.body)}
  </>;
}
