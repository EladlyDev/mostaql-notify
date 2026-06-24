/// <reference types="vitest/globals" />
import { render, screen, fireEvent } from "@testing-library/react";

import { Loading } from "@/components/states/Loading";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { Bidi } from "@/components/Bidi";

describe("Loading", () => {
  it("renders without crashing and exposes a status role", () => {
    render(<Loading />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the requested number of skeleton rows", () => {
    const { container } = render(<Loading rows={3} />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBe(3);
  });
});

describe("EmptyState", () => {
  it("shows the title and message", () => {
    render(<EmptyState title="عنوان" message="رسالة" />);
    expect(screen.getByText("عنوان")).toBeInTheDocument();
    expect(screen.getByText("رسالة")).toBeInTheDocument();
  });

  it("renders a clickable action when provided", () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        title="X"
        action={<button onClick={onClick}>افعلها</button>}
      />
    );
    const btn = screen.getByRole("button", { name: "افعلها" });
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("ErrorState", () => {
  it("shows the message and an alert role", () => {
    render(<ErrorState message="حدث خطأ ما" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("حدث خطأ ما")).toBeInTheDocument();
  });

  it("renders a retry control that calls onRetry when clicked", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="x" onRetry={onRetry} />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders no retry button when onRetry is omitted", () => {
    render(<ErrorState message="x" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("Bidi", () => {
  it("renders a <bdi> containing the children", () => {
    const { container } = render(<Bidi>{"١٢٣ test"}</Bidi>);
    const bdi = container.querySelector("bdi");
    expect(bdi).not.toBeNull();
    expect(bdi).toHaveTextContent("١٢٣ test");
  });
});
