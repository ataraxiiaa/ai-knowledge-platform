"use client";

import React from "react";
import Link from "next/link";
import { Sparkles, FolderKanban } from "lucide-react";
import { DashboardShell } from "@/components/dashboard-shell";

export default function ResearchOverviewPage() {
  return (
    <DashboardShell>
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900">
            Autonomous Research
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Synthesize information across multiple indexed documents and web sources.
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center shadow-xs">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
            <Sparkles className="h-6 w-6" />
          </div>
          <h3 className="mt-4 text-base font-semibold text-gray-900">
            Autonomous Agentic Research (Phase 5)
          </h3>
          <p className="mx-auto mt-2 max-w-md text-sm text-gray-500">
            Deep agentic workflows, multi-step search synthesis, and citation generation connect in Phase 5. Select a workspace to explore workspace research notes.
          </p>
          <div className="mt-6 flex justify-center">
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs hover:bg-indigo-500 transition"
            >
              <FolderKanban className="h-4 w-4" />
              <span>Go to My Workspaces</span>
            </Link>
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
