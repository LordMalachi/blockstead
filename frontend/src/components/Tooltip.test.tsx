import { act, fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { Tooltip } from "./Tooltip";

test("connects a keyboard-focusable help trigger to its tooltip", () => {
  render(<Tooltip label="Why this matters">A plain-language explanation.</Tooltip>);

  const trigger = screen.getByRole("button", { name: "Help: Why this matters" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  fireEvent.focus(trigger);
  const tooltip = screen.getByRole("tooltip");
  expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
  expect(tooltip).toHaveTextContent("A plain-language explanation.");
  expect(tooltip).toHaveClass("tooltip__bubble--ready");

  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});

test("keeps a tapped tooltip open until the owner moves elsewhere", () => {
  render(<><Tooltip label="Why this matters">A short answer.</Tooltip><button>Elsewhere</button></>);

  const trigger = screen.getByRole("button", { name: "Help: Why this matters" });
  fireEvent.click(trigger);
  expect(screen.getByRole("tooltip")).toBeVisible();

  fireEvent.pointerDown(screen.getByRole("button", { name: "Elsewhere" }));
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});

test("stays open while the pointer moves from the trigger into the bubble", () => {
  vi.useFakeTimers();
  render(<Tooltip label="Why this matters">A short answer.</Tooltip>);

  const trigger = screen.getByRole("button", { name: "Help: Why this matters" });
  fireEvent.mouseEnter(trigger);
  const tooltip = screen.getByRole("tooltip");
  fireEvent.mouseLeave(trigger);
  fireEvent.mouseEnter(tooltip);
  act(() => { vi.advanceTimersByTime(150); });
  expect(screen.getByRole("tooltip")).toBeVisible();

  fireEvent.mouseLeave(tooltip);
  act(() => { vi.advanceTimersByTime(150); });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  vi.useRealTimers();
});

test("keeps focus and hover independent and lets Escape dismiss hover help", () => {
  vi.useFakeTimers();
  render(<Tooltip label="Why this matters">A short answer.</Tooltip>);
  const trigger = screen.getByRole("button", { name: "Help: Why this matters" });

  fireEvent.mouseEnter(trigger);
  fireEvent.focus(trigger);
  fireEvent.mouseLeave(trigger);
  act(() => { vi.advanceTimersByTime(150); });
  expect(screen.getByRole("tooltip")).toBeVisible();

  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  vi.useRealTimers();
});
