"use client";

import React, { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  MessageSquare,
  Sparkles,
  Loader2,
  Calendar,
  AlertCircle,
} from "lucide-react";
import { ChatPanel } from "@/components/chat-panel";
import { DocumentsPanel } from "@/components/documents-panel";
import { DashboardShell } from "@/components/dashboard-shell";
import { workspacesApi, ApiRequestError } from "@/lib/api";
import { Workspace } from "@/types";

type TabType = "documents" | "chat" | "research";

function WorkspaceContent() {
  const params = useParams();
  const workspaceId = params?.id as string;

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("documents");

  // Research tab state
  const [researchNotes, setResearchNotes] = useState(
    "### Workspace Research Objectives\n- Synthesize key findings from uploaded documents.\n- Extract core definitions, architectures, and performance benchmarks.\n- Formulate follow-up research questions."
  );

  useEffect(() => {
    if (!workspaceId) return;

    let isMounted = true;
    workspacesApi
      .get(workspaceId)
      .then((data) => {
        if (isMounted) {
          setWorkspace(data);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          if (err instanceof ApiRequestError) {
            setError(err.message);
          } else {
            setError("Failed to load workspace details.");
          }
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [workspaceId]);

  return (
    <DashboardShell>
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Top Back Link */}
        <div>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-500 hover:text-indigo-600 transition"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Back to Workspaces</span>
          </Link>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-gray-200 bg-white p-8">
            <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
            <p className="mt-3 text-sm text-gray-500">Loading workspace...</p>
          </div>
        )}

        {/* Error State */}
        {error && !isLoading && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <AlertCircle className="mx-auto h-8 w-8 text-red-600" />
            <h3 className="mt-2 text-base font-semibold text-red-900">
              Workspace Error
            </h3>
            <p className="mt-1 text-sm text-red-700">{error}</p>
            <Link
              href="/"
              className="mt-4 inline-block rounded-lg bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-700 transition"
            >
              Return to Workspaces
            </Link>
          </div>
        )}

        {/* Workspace Loaded Content */}
        {!isLoading && workspace && (
          <div className="space-y-6">
            {/* Workspace Banner */}
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-xs">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h1 className="text-2xl font-bold tracking-tight text-gray-900">
                    {workspace.name}
                  </h1>
                  <p className="mt-1 text-sm text-gray-500">
                    {workspace.description || "No description provided for this workspace."}
                  </p>
                </div>
                <div className="flex items-center gap-1 text-xs text-gray-600">
                  <Calendar className="h-3.5 w-3.5" />
                  <span>Created {new Date(workspace.created_at).toLocaleDateString()}</span>
                </div>
              </div>

              {/* Navigation Tabs */}
              <div className="mt-6 flex border-b border-gray-200">
                <button
                  onClick={() => setActiveTab("documents")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold transition ${
                    activeTab === "documents"
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                  }`}
                >
                  <FileText className="h-4 w-4" />
                  <span>Documents</span>
                </button>

                <button
                  onClick={() => setActiveTab("chat")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold transition ${
                    activeTab === "chat"
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                  }`}
                >
                  <MessageSquare className="h-4 w-4" />
                  <span>Chat</span>
                </button>

                <button
                  onClick={() => setActiveTab("research")}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-semibold transition ${
                    activeTab === "research"
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                  }`}
                >
                  <Sparkles className="h-4 w-4" />
                  <span>Research</span>
                </button>
              </div>
            </div>

            {/* TAB 1: DOCUMENTS */}
            {activeTab === "documents" && <DocumentsPanel key={workspaceId} workspaceId={workspaceId} />}

            {/* TAB 2: CHAT */}
            {activeTab === "chat" && <ChatPanel key={workspaceId} workspaceId={workspaceId} />}

            {/* TAB 3: RESEARCH */}
            {activeTab === "research" && (
              <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-xs space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-gray-900">
                      Workspace Research Notes & Synthesis
                    </h3>
                    <p className="text-xs text-gray-500">
                      Preview only: notes are not saved and will be lost when you leave or reload this page.
                    </p>
                  </div>
                  <button
                    disabled
                    className="rounded-lg bg-gray-200 px-4 py-2 text-xs font-semibold text-gray-700 cursor-not-allowed"
                  >
                    Saving unavailable
                  </button>
                </div>

                <textarea
                  rows={12}
                  value={researchNotes}
                  onChange={(e) => setResearchNotes(e.target.value)}
                  className="w-full rounded-xl border border-gray-300 p-4 font-mono text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            )}
          </div>
        )}
      </div>
    </DashboardShell>
  );
}

export default function WorkspaceDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
        </div>
      }
    >
      <WorkspaceContent />
    </Suspense>
  );
}
