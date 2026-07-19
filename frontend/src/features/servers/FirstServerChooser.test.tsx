import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { FirstServerChooser } from "./FirstServerChooser";

test("recommends the simplest setup and lets the owner choose another path", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<FirstServerChooser value="create" onChange={onChange} />);

  expect(screen.getByText("Recommended")).toBeVisible();
  expect(screen.getByRole("button", { name: /Create a new server/ })).toHaveAttribute("aria-pressed", "true");

  await user.click(screen.getByRole("button", { name: /Use an existing server/ }));
  expect(onChange).toHaveBeenCalledWith("import");
});
