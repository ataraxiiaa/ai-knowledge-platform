"use client";

import React from "react";
import Link from "next/link";
import { LogOut, User as UserIcon } from "lucide-react";
import { useAuth } from "@/context/auth-context";

export function Header() {
  const { userEmail, logout } = useAuth();
  const displayName = userEmail ? userEmail.split("@")[0] : "User";

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-gray-200 bg-white px-6 shadow-sm">
      <div className="flex items-center gap-3">
        <Link href="/" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white font-bold text-sm">
            KP
          </div>
          <span className="text-lg font-semibold tracking-tight text-gray-900">
            Knowledge Platform
          </span>
        </Link>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gray-100 text-gray-600">
            <UserIcon className="h-4 w-4" />
          </div>
          <span className="hidden sm:inline capitalize">{displayName}</span>
        </div>

        <button
          onClick={logout}
          title="Sign out"
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Logout</span>
        </button>
      </div>
    </header>
  );
}
