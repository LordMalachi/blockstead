import { render, screen } from "@testing-library/react";
import { AuthPage } from "./AuthPage";

test("labels the first administrator form", () => {
  render(<AuthPage setup onSuccess={() => undefined} />);
  expect(screen.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible();
  expect(screen.getByLabelText("Username")).toBeRequired();
  expect(screen.getByLabelText("Username")).toHaveAttribute("autocapitalize", "none");
  expect(screen.getByLabelText("Username")).toHaveAttribute("spellcheck", "false");
  expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  expect(screen.queryByText("Forgot your password?")).not.toBeInTheDocument();
});

test("shows local password recovery instructions when signing in", () => {
  render(<AuthPage setup={false} onSuccess={() => undefined} />);
  expect(screen.getByText("Forgot your password?")).toBeVisible();
  expect(screen.getByText("sudo blockstead reset-password")).toBeInTheDocument();
  expect(screen.getByText(/signs out every existing Blockstead session/i)).toBeInTheDocument();
});
