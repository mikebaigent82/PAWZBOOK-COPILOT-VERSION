"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Logo, SessionProvider, useSession } from "./session";
import { cx, Disclaimer } from "./ui";

const NAV = [
  { href: "/", label: "Am I on track?", icon: "◎" },
  { href: "/money", label: "My money", icon: "$" },
  { href: "/income-spending", label: "Income & spending", icon: "⇄" },
  { href: "/plan", label: "Year by year", icon: "▤" },
  { href: "/what-if", label: "What if...?", icon: "?" },
  { href: "/taxes", label: "Taxes", icon: "%" },
  { href: "/stress", label: "Bad-market tests", icon: "↯" },
  { href: "/assistant", label: "Ask a question", icon: "✎" },
  { href: "/reports", label: "Reports", icon: "⎙" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <Frame>{children}</Frame>
    </SessionProvider>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const { user, household, signOut } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const needsSetup = household.member_count === 0 && !household.onboarding_complete;

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (needsSetup && pathname !== "/setup" && pathname !== "/settings") router.replace("/setup");
  }, [needsSetup, pathname, router]);

  return (
    <div className="min-h-screen lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        Skip to content
      </a>
      <aside
        className={cx(
          "no-print border-line bg-card lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-64 lg:shrink-0 lg:flex-col lg:border-r",
          menuOpen ? "fixed inset-0 z-40 flex flex-col" : "hidden",
        )}
        aria-label="Main menu"
      >
        <div className="flex items-center justify-between px-5 py-5">
          <Link href="/"><Logo /></Link>
          <button className="text-2xl lg:hidden" onClick={() => setMenuOpen(false)} aria-label="Close menu">×</button>
        </div>
        <nav className="flex-1 overflow-y-auto px-3">
          <ul className="flex flex-col gap-1">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "flex min-h-11 items-center gap-3 rounded-lg px-3 font-medium",
                      active ? "bg-brand text-white" : "text-ink hover:bg-brand-soft",
                    )}
                  >
                    <span aria-hidden className={cx("w-5 text-center", active ? "text-white" : "text-brand")}>{item.icon}</span>
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-line p-4 text-sm">
          <p className="truncate font-medium">{user.display_name}</p>
          <p className="truncate text-muted">{user.email}</p>
          <button onClick={signOut} className="mt-2 font-medium text-brand-dark underline">Sign out</button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="no-print flex items-center justify-between border-b border-line bg-card px-4 py-3 lg:hidden">
          <Logo />
          <button onClick={() => setMenuOpen(true)} className="min-h-11 rounded-lg border border-line px-4 font-medium">
            Menu
          </button>
        </div>
        {household.is_demo && (
          <div className="no-print border-b border-[#efd59c] bg-warn-soft px-4 py-2 text-center text-sm">
            You are looking at <strong>made-up sample data</strong> for a fictional couple.{" "}
            <Link href="/settings#data" className="font-semibold underline">Clear it and enter your own</Link>
          </div>
        )}
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
        <footer className="mx-auto w-full max-w-6xl px-4 pb-6 sm:px-6 lg:px-8">
          <Disclaimer />
        </footer>
      </div>
    </div>
  );
}
