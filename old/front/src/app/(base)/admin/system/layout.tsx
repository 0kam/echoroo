"use client";

import classnames from "classnames";
import { usePathname, useRouter } from "next/navigation";
import { useContext, useEffect, useMemo } from "react";
import type { ReactNode } from "react";

import Header from "@/lib/components/ui/Header";
import { H1 } from "@/lib/components/ui/Headings";
import Link from "@/lib/components/ui/Link";

import UserContext from "@/app/contexts/user";

type NavItem = {
  href: string;
  label: string;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/admin/system/users", label: "Users" },
  { href: "/admin/system/projects", label: "Projects" },
  { href: "/admin/system/recorders", label: "Recorders" },
  { href: "/admin/system/licenses", label: "Licenses" },
];

export default function SystemAdminLayout({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const user = useContext(UserContext);
  const isSuperuser = Boolean(user?.is_superuser);

  useEffect(() => {
    if (user && !user.is_superuser) {
      router.replace("/");
    }
  }, [user, router]);

  const navItems = useMemo(() => NAV_ITEMS, []);

  if (!isSuperuser) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4">
        <p className="text-center text-stone-500 dark:text-stone-400">
          You need administrator privileges to access this page.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 pb-12">
      <Header>
        <div className="flex flex-col gap-4">
          <div>
            <H1>System Administration</H1>
            <p className="mt-1 text-sm text-stone-600 dark:text-stone-300">
              Manage system-wide resources: user accounts, recorder catalogue, and license catalogue.
              Only superusers can access this area.
            </p>
          </div>
          <nav className="flex flex-wrap gap-2">
            {navItems.map((item) => {
              const isActive = pathname?.startsWith(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  mode="text"
                  variant={isActive ? "primary" : "secondary"}
                  padding="px-3 py-2"
                  className={classnames(
                    "text-sm font-semibold transition-colors",
                    isActive
                      ? "border border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200"
                      : "border border-transparent text-stone-600 dark:text-stone-300 hover:border-stone-300 dark:hover:border-stone-700",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </Header>
      <div className="px-2 sm:px-3 lg:px-6 space-y-4">
        {children}
      </div>
    </div>
  );
}
