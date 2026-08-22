import { useCallback, useMemo, useState } from "react";
import { fieldErrorsOf, type FieldError } from "../api/client";
import { Button } from "./Button";

/**
 * Inline message for one invalid form control: what's wrong, how to format it, and —
 * whenever a `suggestion` is available — a one-click fix that hands the corrected value
 * back to the caller. `id` must match the control's `aria-describedby`.
 */
export function FieldNotice({ id, error, onUseSuggestion }: { id: string; error: FieldError; onUseSuggestion?: (suggestion: string) => void }) {
  const suggestion = error.suggestion;
  return <p className="field-error" id={id} role="alert">
    <span>{error.message}</span>
    {error.rule && <small>{error.rule}</small>}
    {suggestion && onUseSuggestion && <Button type="button" className="button--secondary button--small" onClick={() => onUseSuggestion(suggestion)}>
      {`Use suggested name: “${suggestion}”`}
    </Button>}
  </p>;
}

export interface FieldControlProps {
  "aria-invalid"?: true;
  "aria-describedby"?: string;
  className: string;
}

/**
 * Tracks the per-field failures from the last failed submit (or a live, pre-submit check)
 * and hands each control the accessible props it needs to highlight itself: `aria-invalid`,
 * `aria-describedby` pointing at the matching `<FieldNotice id={noticeId(field)}>`, and a
 * CSS class for the visual red-border treatment.
 */
export function useFieldErrors() {
  const [fields, setFields] = useState<Map<string, FieldError>>(new Map());

  const setFromError = useCallback((error: unknown) => setFields(fieldErrorsOf(error)), []);
  // `field` is already the map key, so callers (e.g. a local pre-submit check like
  // describeServerDirectoryName) don't need to repeat it inside the error value.
  const setField = useCallback((field: string, error: Omit<FieldError, "field"> | null) => {
    setFields(current => {
      const next = new Map(current);
      if (error) next.set(field, { field, ...error });
      else next.delete(field);
      return next;
    });
  }, []);
  const clear = useCallback(() => setFields(new Map()), []);
  const noticeId = useCallback((field: string) => `field-error-${field.replace(/[^a-zA-Z0-9_-]+/g, "-")}`, []);
  const get = useCallback((field: string) => fields.get(field), [fields]);
  const controlProps = useCallback((field: string): FieldControlProps => {
    const error = fields.get(field);
    return error
      ? { "aria-invalid": true, "aria-describedby": noticeId(field), className: "field-invalid" }
      : { className: "" };
  }, [fields, noticeId]);

  return useMemo(
    () => ({ fields, setFromError, setField, clear, get, noticeId, controlProps }),
    [fields, setFromError, setField, clear, get, noticeId, controlProps],
  );
}
