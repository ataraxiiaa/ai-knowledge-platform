"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FolderKanban, FileText, Sparkles } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    {
      label: "Workspaces",
      href: "/",
      icon: FolderKanban,
      isActive: pathname === "/" || pathname.startsWith("/workspaces"),
    },
    {
      label: "Documents",
      href: "/documents",
      icon: FileText,
      isActive: pathname.startsWith("/documents"),
    },
    {
      label: "Research",
      href: "/research",
      icon: Sparkles,
      isActive: pathname.startsWith("/research"),
    },
  ];

  return (
    <aside className="w-56 shrink-0 border-r border-gray-200 bg-white min-h-[calc(100vh-4rem)] p-4 flex flex-col justify-between">
      <nav className="space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.label}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                item.isActive
                  ? "bg-indigo-50 text-indigo-700 font-semibold"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="rounded-lg bg-gray-50 p-3 border border-gray-100 text-xs text-gray-500">
        <p className="font-medium text-gray-700">Phase 2: Frontend</p>
        <p className="mt-0.5">Production foundation</p>
      </div>
    </aside>
  );
}
