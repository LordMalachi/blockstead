import { render, screen } from "@testing-library/react";
import { AuthPage } from "./AuthPage";
test("labels the first administrator form", () => { render(<AuthPage setup onSuccess={() => undefined} />); expect(screen.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible(); expect(screen.getByLabelText("Username")).toBeRequired(); expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password"); });
