/// <reference types="vitest/globals" />
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { PersonalRecord, PersonalStatusOption } from "@/lib/types";

// ---------------------------------------------------------------------------
// FavoriteToggle calls useToggleFavorite() internally → toggleFavorite from the
// API module. Mock the API so the network call is a spy.
// ---------------------------------------------------------------------------
const { toggleFavoriteSpy, updatePersonalSpy, getPersonalSpy } = vi.hoisted(
  () => ({
    toggleFavoriteSpy: vi.fn(),
    updatePersonalSpy: vi.fn(),
    getPersonalSpy: vi.fn(),
  })
);

vi.mock("@/lib/api", () => ({
  toggleFavorite: toggleFavoriteSpy,
  updatePersonal: updatePersonalSpy,
  getPersonal: getPersonalSpy,
}));

// ---------------------------------------------------------------------------
// StatusSelect renders Base UI Select, which is impractical to open in jsdom.
// Mock the ui/select primitives down to a native <select> so StatusSelect's OWN
// logic (mapping statuses → options, wiring onValueChange → onChange) is still
// the thing under test — only the headless rendering layer is swapped.
// ---------------------------------------------------------------------------
vi.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    disabled,
    children,
  }: {
    value: string;
    onValueChange: (v: string) => void;
    disabled?: boolean;
    children: ReactNode;
  }) => (
    <select
      data-testid="status-native-select"
      value={value}
      disabled={disabled}
      onChange={(e) => onValueChange(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}));

import { FavoriteToggle } from "@/components/personal/FavoriteToggle";
import { StatusSelect } from "@/components/personal/StatusSelect";
import { TagEditor } from "@/components/personal/TagEditor";
import { OutcomeFields } from "@/components/personal/OutcomeFields";
import { HideButton } from "@/components/personal/HideButton";

const RECORD: PersonalRecord = {
  project_id: 1,
  favorite: false,
  status: "lead",
  status_label: "عميل محتمل",
  tags: [],
  applied_at: null,
  won_amount: null,
  lost_reason: null,
  notes: "",
  board_position: 0,
  hidden: false,
  status_changed_at: null,
  reminder_at: null,
  auto_status_from: null,
  auto_status_at: null,
};

function withClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  toggleFavoriteSpy.mockResolvedValue(RECORD);
  updatePersonalSpy.mockResolvedValue(RECORD);
  getPersonalSpy.mockResolvedValue(RECORD);
});

// ---------------------------------------------------------------------------
// FavoriteToggle
// ---------------------------------------------------------------------------
describe("FavoriteToggle", () => {
  it("exposes an accessible label and reflects the inactive state", () => {
    withClient(<FavoriteToggle projectId={9} favorite={false} />);
    const btn = screen.getByRole("button", { name: "مفضّل" });
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("reflects the active (favorited) state", () => {
    const { container } = withClient(
      <FavoriteToggle projectId={9} favorite />
    );
    expect(screen.getByRole("button", { name: "مفضّل" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    // Filled star when favorited.
    expect(container.querySelector("svg")?.getAttribute("class")).toContain(
      "fill-amber-400"
    );
  });

  it("calls the toggle-favorite mutation with the project id on click", async () => {
    withClient(<FavoriteToggle projectId={9} favorite={false} />);
    fireEvent.click(screen.getByRole("button", { name: "مفضّل" }));
    await waitFor(() => expect(toggleFavoriteSpy).toHaveBeenCalledWith(9));
  });
});

// ---------------------------------------------------------------------------
// StatusSelect
// ---------------------------------------------------------------------------
describe("StatusSelect", () => {
  const STATUSES: PersonalStatusOption[] = [
    { key: "lead", label: "عميل محتمل" },
    { key: "applied", label: "تم التقديم" },
    { key: "won", label: "فاز" },
  ];

  it("renders every provided status as an option", () => {
    render(
      <StatusSelect value="lead" statuses={STATUSES} onChange={() => {}} />
    );
    for (const s of STATUSES) {
      expect(screen.getByRole("option", { name: s.label })).toBeInTheDocument();
    }
  });

  it("fires onChange with the chosen stage key", () => {
    const onChange = vi.fn();
    render(
      <StatusSelect value="lead" statuses={STATUSES} onChange={onChange} />
    );
    fireEvent.change(screen.getByTestId("status-native-select"), {
      target: { value: "won" },
    });
    expect(onChange).toHaveBeenCalledWith("won");
  });
});

// ---------------------------------------------------------------------------
// TagEditor
// ---------------------------------------------------------------------------
describe("TagEditor", () => {
  it("adds a tag on Enter", () => {
    const onChange = vi.fn();
    render(<TagEditor value={[]} onChange={onChange} />);
    const input = screen.getByLabelText("أضف وسمًا");
    fireEvent.change(input, { target: { value: "عاجل" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["عاجل"]);
  });

  it("trims surrounding whitespace before adding", () => {
    const onChange = vi.fn();
    render(<TagEditor value={[]} onChange={onChange} />);
    const input = screen.getByLabelText("أضف وسمًا");
    fireEvent.change(input, { target: { value: "   spaced   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["spaced"]);
  });

  it("de-dupes — adding an existing tag is a no-op", () => {
    const onChange = vi.fn();
    render(<TagEditor value={["a"]} onChange={onChange} />);
    const input = screen.getByLabelText("أضف وسمًا");
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores a blank (whitespace-only) tag", () => {
    const onChange = vi.fn();
    render(<TagEditor value={[]} onChange={onChange} />);
    const input = screen.getByLabelText("أضف وسمًا");
    fireEvent.change(input, { target: { value: "    " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a tag via its × control", () => {
    const onChange = vi.fn();
    render(<TagEditor value={["a", "b"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "إزالة الوسم a" }));
    expect(onChange).toHaveBeenCalledWith(["b"]);
  });
});

// ---------------------------------------------------------------------------
// OutcomeFields — stage-gated outcome capture
// ---------------------------------------------------------------------------
describe("OutcomeFields", () => {
  it("shows the won-amount field only for the 'won' stage and reports the typed amount", () => {
    const onChange = vi.fn();
    render(
      <OutcomeFields
        status="won"
        wonAmount={null}
        lostReason={null}
        onChange={onChange}
      />
    );
    const input = screen.getByLabelText("قيمة الصفقة");
    expect(screen.queryByLabelText("سبب الخسارة")).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "500" } });
    expect(onChange).toHaveBeenCalledWith({ won_amount: 500 });
  });

  it("shows the lost-reason field for the 'lost' stage and reports the typed reason", () => {
    const onChange = vi.fn();
    render(
      <OutcomeFields
        status="lost"
        wonAmount={null}
        lostReason={null}
        onChange={onChange}
      />
    );
    const area = screen.getByLabelText("سبب الخسارة");
    expect(screen.queryByLabelText("قيمة الصفقة")).not.toBeInTheDocument();
    fireEvent.change(area, { target: { value: "السعر مرتفع" } });
    expect(onChange).toHaveBeenCalledWith({ lost_reason: "السعر مرتفع" });
  });

  it("renders nothing for a non-terminal stage", () => {
    const { container } = render(
      <OutcomeFields
        status="lead"
        wonAmount={null}
        lostReason={null}
        onChange={() => {}}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// ---------------------------------------------------------------------------
// HideButton — presentational toggle
// ---------------------------------------------------------------------------
describe("HideButton", () => {
  it("labels itself 'إخفاء' when the project is visible", () => {
    render(<HideButton hidden={false} onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "إخفاء" })).toBeInTheDocument();
  });

  it("labels itself 'إظهار' when the project is hidden", () => {
    render(<HideButton hidden onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "إظهار" })).toBeInTheDocument();
  });

  it("calls onToggle when clicked", () => {
    const onToggle = vi.fn();
    render(<HideButton hidden={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button", { name: "إخفاء" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
