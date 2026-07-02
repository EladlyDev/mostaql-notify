import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ProjectListItem } from "@/lib/types";

function item(id: number, title: string): ProjectListItem {
  return {
    id, title, url: `https://mostaql.com/project/${id}`, client_name: "c",
    client_hiring_rate: 50, budget_min: 100, budget_max: 500, currency: "USD",
    tier: 1, tier_label: "Tier 1", bids_count: 3, posted_at: "2026-06-30T10:00:00Z",
    site_status: "open", eval_status: "qualified", qualified: true,
    favorite: false, personal_status: "new", personal_status_label: "جديد",
    tags: [], hidden: false, score: 70, freshness: null,
  };
}

const controller = {
  params: { page: 1, page_size: 20, sort: "posted_at", order: "desc" },
  filtersActive: false,
  data: { items: [item(1, "AAA"), item(2, "BBB")], total: 2, page: 1, page_size: 20 },
  isLoading: false, isError: false, error: null,
  refetch: vi.fn(), setPage: vi.fn(), clearFilters: vi.fn(),
};

vi.mock("@/lib/useProjects", () => ({ useProjects: () => controller }));

import ProjectsPage from "@/app/projects/page";

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ProjectsPage />
    </QueryClientProvider>,
  );
}

describe("projects page view toggle", () => {
  beforeEach(() => window.localStorage.clear());

  it("switches table <-> cards on click and persists the choice", () => {
    renderPage();
    // default is the table view (a real <table> is rendered)
    expect(screen.queryByRole("table")).not.toBeNull();

    // -> cards
    fireEvent.click(screen.getByLabelText("عرض بطاقات"));
    expect(screen.queryByRole("table")).toBeNull();
    expect(window.localStorage.getItem("projects:view")).toBe("cards");

    // -> back to table
    fireEvent.click(screen.getByLabelText("عرض جدول"));
    expect(screen.queryByRole("table")).not.toBeNull();
    expect(window.localStorage.getItem("projects:view")).toBe("table");
  });

  it("restores the persisted view (cards) on mount", () => {
    window.localStorage.setItem("projects:view", "cards");
    renderPage();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
