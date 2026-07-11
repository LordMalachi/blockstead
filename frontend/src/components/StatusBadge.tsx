import type { ProcessState } from "../api/client";
export function StatusBadge({ state }: { state: ProcessState["state"] }) {
  return <span className={`status status--${state.toLowerCase()}`}><span aria-hidden="true" className="status__dot" />{state.charAt(0) + state.slice(1).toLowerCase()}</span>;
}
