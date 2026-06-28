/// <reference types="vitest/globals" />
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import type { AttachmentItem } from "@/lib/types";
import { FileDropzone } from "@/components/workspace/FileDropzone";
import { FileList } from "@/components/workspace/FileList";
import { FilePreviewDialog } from "@/components/workspace/FilePreviewDialog";
import { attachmentDownloadUrl, attachmentPreviewUrl } from "@/lib/api";

// ---------------------------------------------------------------------------
// jsdom polyfills required by the Base UI Dialog internals (FilePreviewDialog).
// ---------------------------------------------------------------------------
beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;

  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });

  Element.prototype.scrollIntoView = () => {};
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

function makeAttachment(
  overrides: Partial<AttachmentItem> = {}
): AttachmentItem {
  return {
    id: 3,
    project_id: 1,
    original_name: "تقرير.pdf",
    file_type: "pdf",
    size_bytes: 2048,
    uploaded_at: "2026-06-27T10:00:00Z",
    can_preview: true,
    ...overrides,
  };
}

// ===========================================================================
// FileDropzone
// ===========================================================================
describe("FileDropzone", () => {
  it("shows the allowed-types and max-size hint from props", () => {
    render(
      <FileDropzone
        allowedTypes={["pdf", "docx", "md"]}
        maxBytes={5 * 1024 * 1024}
        onFiles={() => {}}
      />
    );
    const hint = screen.getByText(/الأنواع المسموحة/);
    expect(hint).toHaveTextContent("PDF");
    expect(hint).toHaveTextContent("DOCX");
    expect(hint).toHaveTextContent("Markdown");
    expect(hint).toHaveTextContent("5 MB");
  });

  it("calls onFiles when a file is selected via the input", () => {
    const onFiles = vi.fn();
    const { container } = render(
      <FileDropzone
        allowedTypes={["pdf", "docx", "md"]}
        maxBytes={1024}
        onFiles={onFiles}
      />
    );
    const input = container.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    const file = new File(["x"], "a.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0][0][0]).toBe(file);
  });

  it("calls onFiles for a dropped file", () => {
    const onFiles = vi.fn();
    render(
      <FileDropzone
        allowedTypes={["pdf"]}
        maxBytes={1024}
        onFiles={onFiles}
      />
    );
    const zone = screen.getByRole("button", {
      name: /اسحب الملفات هنا/,
    });
    const file = new File(["x"], "b.pdf", { type: "application/pdf" });
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0][0][0]).toBe(file);
  });

  it("narrows the native picker via the accept attribute (client-side affordance)", () => {
    const { container } = render(
      <FileDropzone
        allowedTypes={["pdf", "md"]}
        maxBytes={1024}
        onFiles={() => {}}
      />
    );
    const input = container.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    expect(input.getAttribute("accept")).toBe(".pdf,.md");
  });

  it("surfaces the error prop as an alert", () => {
    render(
      <FileDropzone
        allowedTypes={["pdf"]}
        maxBytes={1024}
        onFiles={() => {}}
        error="نوع ملف غير مدعوم."
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("نوع ملف غير مدعوم.");
  });

  // NOTE (by design, not a bug): FileDropzone does NOT reject a disallowed file
  // by extension/content client-side — its own source comments state "The SERVER
  // is the validation authority". It forwards every dropped/selected file to
  // onFiles; the upload mutation then surfaces the server's 400/413 via `error`
  // (covered above and in markdownEditor.test.tsx). The only client affordance
  // is the <input accept> hint asserted above. This skip documents the gap.
  it.skip("rejects a disallowed extension purely client-side", () => {
    /* intentionally unimplemented — server-authoritative validation. */
  });
});

// ===========================================================================
// FileList
// ===========================================================================
describe("FileList", () => {
  const noop = () => {};

  it("shows the empty state when there are no files", () => {
    render(
      <FileList
        items={[]}
        onPreview={noop}
        onRename={noop}
        onDelete={noop}
      />
    );
    expect(
      screen.getByText(/لا توجد ملفات مرفقة بعد/)
    ).toBeInTheDocument();
  });

  it("renders an item's name and type label", () => {
    render(
      <FileList
        items={[makeAttachment({ original_name: "خطة.pdf" })]}
        onPreview={noop}
        onRename={noop}
        onDelete={noop}
      />
    );
    expect(screen.getByText("خطة.pdf")).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
  });

  it("fires onPreview with the item for a previewable file", () => {
    const onPreview = vi.fn();
    const item = makeAttachment({ can_preview: true });
    render(
      <FileList
        items={[item]}
        onPreview={onPreview}
        onRename={noop}
        onDelete={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "معاينة" }));
    expect(onPreview).toHaveBeenCalledWith(item);
  });

  it("hides the preview control when a file is not previewable", () => {
    render(
      <FileList
        items={[makeAttachment({ can_preview: false })]}
        onPreview={noop}
        onRename={noop}
        onDelete={noop}
      />
    );
    expect(
      screen.queryByRole("button", { name: "معاينة" })
    ).not.toBeInTheDocument();
  });

  it("commits a rename with the id and the trimmed new name", () => {
    const onRename = vi.fn();
    const item = makeAttachment({ id: 12, original_name: "old.pdf" });
    render(
      <FileList
        items={[item]}
        onPreview={noop}
        onRename={onRename}
        onDelete={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "إعادة تسمية" }));
    const input = screen.getByLabelText("اسم الملف");
    fireEvent.change(input, { target: { value: "  new.pdf  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith(12, "new.pdf");
  });

  it("does not call onRename when the name is unchanged", () => {
    const onRename = vi.fn();
    const item = makeAttachment({ id: 12, original_name: "same.pdf" });
    render(
      <FileList
        items={[item]}
        onPreview={noop}
        onRename={onRename}
        onDelete={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "إعادة تسمية" }));
    const input = screen.getByLabelText("اسم الملف");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).not.toHaveBeenCalled();
  });

  it("confirms then fires onDelete with the id", () => {
    const onDelete = vi.fn();
    const item = makeAttachment({ id: 7 });
    render(
      <FileList
        items={[item]}
        onPreview={noop}
        onRename={noop}
        onDelete={onDelete}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "حذف" }));
    // Confirmation step appears.
    expect(screen.getByText("حذف؟")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "تأكيد" }));
    expect(onDelete).toHaveBeenCalledWith(7);
  });

  it("disables the row's controls while a rename is in flight", () => {
    const item = makeAttachment({ id: 5 });
    render(
      <FileList
        items={[item]}
        onPreview={noop}
        onRename={noop}
        onDelete={noop}
        renamingId={5}
      />
    );
    expect(screen.getByRole("button", { name: "إعادة تسمية" })).toBeDisabled();
  });

  it("shows the deleting busy label while a delete is in flight (confirm open)", () => {
    const item = makeAttachment({ id: 9 });
    const { rerender } = render(
      <FileList
        items={[item]}
        onPreview={noop}
        onRename={noop}
        onDelete={noop}
      />
    );
    // Open the confirm step first (trash is enabled when not busy).
    fireEvent.click(screen.getByRole("button", { name: "حذف" }));
    // Now the parent marks this row's delete in flight.
    rerender(
      <FileList
        items={[item]}
        onPreview={noop}
        onRename={noop}
        onDelete={noop}
        deletingId={9}
      />
    );
    expect(screen.getByText("جارٍ الحذف…")).toBeInTheDocument();
  });
});

// ===========================================================================
// FilePreviewDialog
// ===========================================================================
describe("FilePreviewDialog", () => {
  it("renders nothing when closed", () => {
    render(
      <FilePreviewDialog
        attachment={makeAttachment()}
        open={false}
        onOpenChange={() => {}}
      />
    );
    expect(screen.queryByText("تقرير.pdf")).not.toBeInTheDocument();
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("shows an inline iframe to the preview stream for a PDF", () => {
    render(
      <FilePreviewDialog
        attachment={makeAttachment({ id: 3, file_type: "pdf" })}
        open
        onOpenChange={() => {}}
      />
    );
    const iframe = document.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe(attachmentPreviewUrl(3));
  });

  it("shows a download link (and no preview) for a non-previewable docx", () => {
    render(
      <FilePreviewDialog
        attachment={makeAttachment({
          id: 4,
          file_type: "docx",
          original_name: "عقد.docx",
        })}
        open
        onOpenChange={() => {}}
      />
    );
    expect(
      screen.getByText("لا تتوفّر معاينة لهذا الملف.")
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /تنزيل الملف/ });
    expect(link).toHaveAttribute("href", attachmentDownloadUrl(4));
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("fetches and renders the sanitized markdown for an .md file", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("# تقرير المعاينة", { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      render(
        <FilePreviewDialog
          attachment={makeAttachment({
            id: 6,
            file_type: "md",
            original_name: "ملاحظات.md",
          })}
          open
          onOpenChange={() => {}}
        />
      );
      await waitFor(() => {
        expect(screen.getByText("تقرير المعاينة")).toBeInTheDocument();
      });
      // It fetched the gated preview stream with the session cookie.
      expect(fetchMock).toHaveBeenCalledWith(
        attachmentPreviewUrl(6),
        expect.objectContaining({ credentials: "include" })
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
