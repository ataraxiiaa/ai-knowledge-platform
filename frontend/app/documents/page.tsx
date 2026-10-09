"use client";

import React from "react";
import Link from "next/link";
import { FileText, ArrowLeft, FolderKanban } from "lucide-react";
import { DashboardShell } from "@/components/dashboard-shell";

export default function DocumentsOverviewPage() {
  return (
    <DashboardShell>
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-900">
            All Documents
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Documents are scoped to specific workspaces. Select a workspace to view and upload files.
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center shadow-xs">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
            <FileText className="h-6 w-6" />
          </div>
          <h3 className="mt-4 text-base font-semibold text-gray-900">
            Workspace Document Ingestion (Phase 3)
          </h3>
          <p className="mx-auto mt-2 max-w-md text-sm text-gray-500">
            Document extraction, chunking, and embedding will be connected in Phase 3. You can browse documents directly within each workspace.
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
