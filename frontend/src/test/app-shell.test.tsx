import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

describe("AppShell", () => {
  it("lets desktop users collapse and restore the workspace navigation", () => {
    vi.spyOn(api, "health").mockResolvedValue({ meta_configured: true, meta_model: "test-model" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><AppShell><div>Workspace content</div></AppShell></QueryClientProvider>);

    const navigation = screen.getByRole("navigation", { name: "Clinical workspaces" });
    expect(screen.getByRole("link", { name: "SDTM" })).not.toHaveTextContent("Experimental");
    expect(screen.getByRole("link", { name: "TLF (Experimental)" })).toBeInTheDocument();
    expect(screen.getAllByText("Experimental")).toHaveLength(5);
    const toggle = screen.getByRole("button", { name: "Collapse navigation sidebar" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(navigation.closest("aside")).toHaveClass("lg:flex");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Expand navigation sidebar" })).toHaveAttribute("aria-expanded", "false");
    expect(navigation.closest("aside")).toHaveClass("hidden");

    fireEvent.click(screen.getByRole("button", { name: "Expand navigation sidebar" }));
    expect(screen.getByRole("button", { name: "Collapse navigation sidebar" })).toHaveAttribute("aria-expanded", "true");
    expect(navigation.closest("aside")).toHaveClass("lg:flex");
  });
});
