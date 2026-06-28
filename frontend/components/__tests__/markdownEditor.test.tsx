/// <reference types="vitest/globals" />
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { AttachmentItem } from "@/lib/types";

// Per-test upload behaviour. We mock `uploadAttachment` with a PLAIN function
// (not a vi.fn() spy): a spy attaches its own promise-settlement tracker to the
// returned promise, which — for a rejecting upload — surfaces as a spurious
// "unhandled rejection" under vitest even though React Query handles it. A plain
// indirection avoids that while still letting each test choose the rejection.
let uploadImpl: (projectId: number, file: File) => Promise<AttachmentItem>;

// Keep the real ApiError class but stub the network call.
vi.mock("@/lib/api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return {
    ...actual,
    uploadAttachment: (projectId: number, file: File) =>
      uploadImpl(projectId, file),
  };
});

import { ApiError } from "@/lib/api";
import { MarkdownEditor } from "@/components/workspace/MarkdownEditor";
import { FileDropzone } from "@/components/workspace/FileDropzone";
import { useUploadAttachment } from "@/lib/useAttachments";

function ControlledEditor({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  return (
    <MarkdownEditor value={value} onChange={setValue} onSave={() => {}} />
  );
}

function showPreview() {
  // Switch to the Preview tab so the sanitized render path mounts.
  fireEvent.click(screen.getByRole("tab", { name: "معاينة" }));
}

describe("MarkdownEditor preview", () => {
  it("renders markdown headings in the preview tab", async () => {
    const { container } = render(<ControlledEditor initial={"# عنوان"} />);
    showPreview();

    await waitFor(() => {
      const h1 = container.querySelector("h1");
      expect(h1).not.toBeNull();
      expect(h1).toHaveTextContent("عنوان");
    });
  });

  it("sanitizes dangerous markup (script / onerror / javascript: links)", async () => {
    const payload = [
      "# مرحبا",
      "",
      "<script>window.__pwned = true</script>",
      "",
      '<img src="x" onerror="window.__pwned = true" />',
      "",
      "[انقر](javascript:window.__pwned=true)",
    ].join("\n");

    const { container } = render(<ControlledEditor initial={payload} />);
    showPreview();

    await waitFor(() => {
      expect(container.querySelector("h1")).not.toBeNull();
    });

    // No executable script element survived sanitization.
    expect(container.querySelector("script")).toBeNull();
    // No inline event-handler attribute survived.
    expect(container.querySelector("[onerror]")).toBeNull();
    // No javascript: URL survived on any link.
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});

function UploadHarness() {
  const upload = useUploadAttachment(1);
  return (
    <FileDropzone
      allowedTypes={["pdf", "docx", "md"]}
      maxBytes={5 * 1024 * 1024}
      onFiles={(files) => upload.mutate(files[0])}
      error={upload.error?.message ?? null}
      uploading={upload.isPending}
    />
  );
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>
  );
}

describe("FileDropzone upload rejection", () => {
  it("shows the server rejection message when the upload is too large (413)", async () => {
    uploadImpl = () =>
      Promise.reject(
        new ApiError(413, "الملف كبير جدًا (الحد الأقصى ٥ ميغابايت).")
      );

    const { container } = renderWithClient(<UploadHarness />);
    const input = container.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    const file = new File(["x".repeat(10)], "big.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(
        screen.getByText("الملف كبير جدًا (الحد الأقصى ٥ ميغابايت).")
      ).toBeInTheDocument();
    });
  });

  it("shows the server rejection message for a wrong file type (400)", async () => {
    uploadImpl = () => Promise.reject(new ApiError(400, "نوع ملف غير مدعوم."));

    const { container } = renderWithClient(<UploadHarness />);
    const input = container.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    const file = new File(["x"], "evil.exe", {
      type: "application/x-msdownload",
    });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("نوع ملف غير مدعوم.")).toBeInTheDocument();
    });
  });
});
