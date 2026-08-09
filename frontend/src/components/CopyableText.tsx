import { useState } from "react";
import { Button } from "./Button";

/** A path or address shown as selectable text with a one-click copy button,
 * for someone who wants to work with it directly outside the dashboard. */
export function CopyableText({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return <span className="copyable-text">
    {label && <span className="copyable-text__label">{label}</span>}
    <code>{value}</code>
    <Button type="button" className="button--secondary button--small" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</Button>
  </span>;
}
