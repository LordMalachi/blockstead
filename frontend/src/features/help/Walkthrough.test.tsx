import { fireEvent, render, screen } from "@testing-library/react";
import { WalkthroughProvider } from "./Walkthrough";
import { useWalkthrough } from "./WalkthroughContext";

function StartTour() {
  const tour = useWalkthrough();
  return <button onClick={tour.start}>Start tour</button>;
}

test("runs and closes the replayable walkthrough", () => {
  render(<WalkthroughProvider><div className="app-shell"><StartTour /><a data-walkthrough="servers" href="/servers">Servers</a></div></WalkthroughProvider>);

  const launcher = screen.getByRole("button", { name: "Start tour" });
  launcher.focus();
  fireEvent.click(launcher);
  const firstHeading = screen.getByRole("heading", { name: "A quick tour of Blockstead" });
  expect(screen.getByRole("dialog", { name: "A quick tour of Blockstead" })).toBeVisible();
  expect(screen.getByRole("img", { name: /Overview showing a running server/ })).toBeVisible();
  expect(firstHeading).toHaveFocus();
  expect(launcher.closest(".app-shell")).toHaveAttribute("inert");

  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByRole("heading", { name: "Servers is your home base" })).toBeVisible();
  const target = document.querySelector('[data-walkthrough="servers"]');
  expect(target).toHaveClass("walkthrough-target");

  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(target).not.toHaveClass("walkthrough-target");
  expect(launcher.closest(".app-shell")).not.toHaveAttribute("inert");
  expect(launcher).toHaveFocus();
});
