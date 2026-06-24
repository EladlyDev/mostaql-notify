"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Home, ListChecks, Settings, LogOut, Menu, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { logout } from "@/lib/api";
import { Button } from "@/components/ui/button";

const NAV_ITEMS = [
  { href: "/", label: "الرئيسية", icon: Home },
  { href: "/projects", label: "المشاريع", icon: ListChecks },
  { href: "/settings", label: "الإعدادات", icon: Settings },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  // Hide the whole shell chrome on the login screen.
  if (pathname === "/login") return null;

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
    } catch {
      // Even if the request fails, push the user to the login screen.
    } finally {
      setSigningOut(false);
      setOpen(false);
      router.push("/login");
      router.refresh();
    }
  }

  const links = NAV_ITEMS.map(({ href, label, icon: Icon }) => {
    const active = isActive(pathname, href);
    return (
      <Link
        key={href}
        href={href}
        onClick={() => setOpen(false)}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          active
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        )}
      >
        <Icon className="size-4" aria-hidden />
        <span>{label}</span>
      </Link>
    );
  });

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-base font-semibold tracking-tight">
            لوحة مراقبة مستقل
          </Link>
          <nav className="hidden items-center gap-1 md:flex" aria-label="التنقل الرئيسي">
            {links}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="hidden md:inline-flex"
            onClick={handleSignOut}
            disabled={signingOut}
          >
            <LogOut className="size-4" aria-hidden />
            <span>تسجيل الخروج</span>
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={open ? "إغلاق القائمة" : "فتح القائمة"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </Button>
        </div>
      </div>

      {open && (
        <nav
          className="flex flex-col gap-1 border-t px-4 py-3 md:hidden"
          aria-label="التنقل الرئيسي"
        >
          {links}
          <Button
            variant="ghost"
            size="sm"
            className="justify-start"
            onClick={handleSignOut}
            disabled={signingOut}
          >
            <LogOut className="size-4" aria-hidden />
            <span>تسجيل الخروج</span>
          </Button>
        </nav>
      )}
    </header>
  );
}
