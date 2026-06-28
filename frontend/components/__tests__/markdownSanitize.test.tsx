/// <reference types="vitest/globals" />
import { render } from "@testing-library/react";

import { Markdown } from "@/components/workspace/Markdown";

// ---------------------------------------------------------------------------
// The Markdown component is the ONE sanitized render path for all user content
// in the workspace (notes preview + .md attachment preview). It must never emit
// an executable script, an inline event handler, a javascript: URL, or raw
// embed elements (iframe/style/object). These are the core XSS guarantees — a
// failure here is a security BUG, not a cosmetic one.
// ---------------------------------------------------------------------------

describe("Markdown XSS sanitization", () => {
  it("drops a raw <script> element", () => {
    const { container } = render(
      <Markdown>{"# عنوان\n\n<script>window.__pwned = 1</script>"}</Markdown>
    );
    expect(container.querySelector("script")).toBeNull();
    // The heading still rendered (sane content survives).
    expect(container.querySelector("h1")).not.toBeNull();
  });

  it("strips inline event-handler attributes from a raw <img onerror>", () => {
    const { container } = render(
      <Markdown>{'<img src="x" onerror="window.__pwned = 1" />'}</Markdown>
    );
    // No onerror (or any on* handler) survives anywhere in the tree.
    expect(container.querySelector("[onerror]")).toBeNull();
    const imgs = container.querySelectorAll("img");
    imgs.forEach((img) => {
      expect(img.getAttribute("onerror")).toBeNull();
    });
  });

  it("does NOT produce an anchor with a javascript: href", () => {
    const { container } = render(
      <Markdown>{"[انقر هنا](javascript:window.__pwned=1)"}</Markdown>
    );
    expect(
      container.querySelector('a[href^="javascript:"]')
    ).toBeNull();
    // If an anchor exists at all, its href must not carry the javascript: scheme.
    container.querySelectorAll("a").forEach((a) => {
      expect((a.getAttribute("href") ?? "").startsWith("javascript:")).toBe(
        false
      );
    });
  });

  it("does not inject a raw <iframe>", () => {
    const { container } = render(
      <Markdown>{'<iframe src="https://evil.example"></iframe>'}</Markdown>
    );
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("does not inject a raw <style> element", () => {
    const { container } = render(
      <Markdown>{"<style>body{display:none}</style>"}</Markdown>
    );
    expect(container.querySelector("style")).toBeNull();
  });

  it("does not inject <object> / <embed> / <form>", () => {
    const { container } = render(
      <Markdown>
        {'<object data="x"></object><embed src="x"><form action="x"></form>'}
      </Markdown>
    );
    expect(container.querySelector("object")).toBeNull();
    expect(container.querySelector("embed")).toBeNull();
    expect(container.querySelector("form")).toBeNull();
  });
});

describe("Markdown GFM rendering (positive coverage)", () => {
  it("renders a GFM table", () => {
    const md = ["| الاسم | القيمة |", "| --- | --- |", "| أ | ١ |"].join("\n");
    const { container } = render(<Markdown>{md}</Markdown>);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(container.querySelectorAll("th").length).toBeGreaterThanOrEqual(2);
    expect(container.querySelectorAll("td").length).toBeGreaterThanOrEqual(2);
  });

  it("renders ~~strikethrough~~ as <del>", () => {
    const { container } = render(<Markdown>{"~~محذوف~~"}</Markdown>);
    const del = container.querySelector("del");
    expect(del).not.toBeNull();
    expect(del).toHaveTextContent("محذوف");
  });

  it("autolinks a bare URL into an anchor with the same href", () => {
    const { container } = render(
      <Markdown>{"تفضل https://example.com لمزيد من المعلومات"}</Markdown>
    );
    const a = container.querySelector("a");
    expect(a).not.toBeNull();
    expect(a?.getAttribute("href")).toBe("https://example.com");
  });
});
