import { fireEvent, render, screen } from "@testing-library/react";
import { Tooltip } from "./Tooltip";

test("connects a keyboard-focusable help trigger to its tooltip", () => {
  render(<Tooltip label="Why this matters">A plain-language explanation.</Tooltip>);

  const trigger = screen.getByRole("button", { name: "Help: Why this matters" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  fireEvent.focus(trigger);
  const tooltip = screen.getByRole("tooltip");
  expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
  expect(tooltip).toHaveTextContent("A plain-language explanation.");
  expect(tooltip).toHaveAttribute("aria-hidden", "false");

  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
