"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { Bidi } from "@/components/Bidi";
import { Input } from "@/components/ui/input";

const ADD_LABEL = "أضف وسمًا";

/** Normalize + dedupe so we never store blank or duplicate tags. */
function addTag(tags: string[], raw: string): string[] {
  const t = raw.trim();
  if (t === "" || tags.includes(t)) return tags;
  return [...tags, t];
}

/**
 * Free-form tag chips. Enter (or comma) commits the draft; the × on a chip
 * removes it. Tag text is wrapped in <bdi> so Arabic / mixed tags stay readable
 * in an RTL layout.
 */
export function TagEditor({
  value,
  onChange,
  placeholder = "أضف وسمًا ثم اضغط Enter",
  className,
  disabled,
}: {
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const next = addTag(value, draft);
    if (next !== value) onChange(next);
    setDraft("");
  };

  const remove = (tag: string) => {
    onChange(value.filter((t) => t !== tag));
  };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="الوسوم">
          {value.map((tag) => (
            <li key={tag}>
              <span className="inline-flex items-center gap-1 rounded-full border bg-muted/50 py-0.5 pe-1 ps-2 text-xs">
                <Bidi className="max-w-40 truncate">{tag}</Bidi>
                {!disabled && (
                  <button
                    type="button"
                    onClick={() => remove(tag)}
                    aria-label={`إزالة الوسم ${tag}`}
                    className="inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
                  >
                    <X className="size-3" aria-hidden />
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Input
        type="text"
        value={draft}
        disabled={disabled}
        aria-label={ADD_LABEL}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (
            e.key === "Backspace" &&
            draft === "" &&
            value.length > 0
          ) {
            // Quick-remove the last chip when the input is empty.
            remove(value[value.length - 1]);
          }
        }}
      />
    </div>
  );
}
