import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ApiRequestError } from "../api/client";
import { FieldNotice, useFieldErrors } from "./FieldError";

function Harness() {
  const [directory, setDirectory] = useState("Bad Name!!");
  const fieldErrors = useFieldErrors();
  const error = fieldErrors.get("directory_name");
  return <div>
    <input
      aria-label="Server folder"
      value={directory}
      onChange={event => setDirectory(event.target.value)}
      {...fieldErrors.controlProps("directory_name")}
    />
    {error && <FieldNotice id={fieldErrors.noticeId("directory_name")} error={error} onUseSuggestion={value => setDirectory(value)} />}
    <button onClick={() => fieldErrors.setFromError(new ApiRequestError(
      "Some submitted information was invalid. Review the highlighted fields and try again.",
      422,
      {
        error: {
          code: "REQUEST_INVALID",
          message: "Some submitted information was invalid.",
          recovery: "Review the highlighted fields and try again.",
          fields: [{
            field: "directory_name",
            reason: "INVALID_CHARACTERS",
            message: "Use only lowercase letters, numbers, hyphens and underscores.",
            rule: "Start with a lowercase letter or number, then more lowercase letters, numbers, hyphens or underscores.",
            suggestion: "bad-name",
          }],
        },
      },
    ))}>Trigger error</button>
    <button onClick={() => fieldErrors.clear()}>Clear</button>
  </div>;
}

test("highlights the control named by the error and offers the one-click fix", () => {
  render(<Harness />);
  const input = screen.getByLabelText("Server folder");
  expect(input).not.toHaveAttribute("aria-invalid");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Trigger error" }));

  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input).toHaveClass("field-invalid");
  const notice = screen.getByRole("alert");
  expect(input).toHaveAttribute("aria-describedby", notice.id);
  expect(notice).toHaveTextContent("Use only lowercase letters, numbers, hyphens and underscores.");
  expect(notice).toHaveTextContent("Start with a lowercase letter or number");

  const fixButton = screen.getByRole("button", { name: /Use suggested name.*bad-name/ });
  fireEvent.click(fixButton);
  expect(input).toHaveValue("bad-name");
});

test("clearing the field errors removes the highlight", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Trigger error" }));
  expect(screen.getByLabelText("Server folder")).toHaveAttribute("aria-invalid", "true");

  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.getByLabelText("Server folder")).not.toHaveAttribute("aria-invalid");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("FieldNotice omits the suggestion button when there is no onUseSuggestion handler", () => {
  render(<FieldNotice id="x" error={{ field: "directory_name", reason: "TOO_LONG", message: "Too long.", suggestion: "short-name" }} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Too long.");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
