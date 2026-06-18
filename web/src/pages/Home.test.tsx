import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import Home from "@/pages/Home";

vi.stubGlobal(
  "fetch",
  vi.fn(async (input: string) => {
    const body =
      input.includes("/failure-cases")
        ? JSON.stringify({ items: [] })
        : JSON.stringify({ items: [] });
    return new Response(body, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }),
);

describe("Home", () => {
  it("renders the debug console shell", async () => {
    render(<Home />);

    expect(await screen.findByText("MES NL2SQL Test Console")).toBeInTheDocument();
    expect(screen.getByText("NL2SQL 调试")).toBeInTheDocument();
    expect(screen.getByText("Harness 控制台")).toBeInTheDocument();
  });
});
