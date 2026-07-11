import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";
test("pairs status color with readable text", () => { render(<StatusBadge state="CRASHED" />); expect(screen.getByText("Crashed")).toBeVisible(); });
