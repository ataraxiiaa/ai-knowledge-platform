"use client";

import React, { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { FolderKanban, Plus, Loader2, ArrowRight, Trash2, X } from "lucide-react";
import { DashboardShell } from "@/components/dashboard-shell";
import { workspacesApi, ApiRequestError } from "@/lib/api";
import { Workspace } from "@/types";

export default function DashboardPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal / Form state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refreshWorkspaces = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await workspacesApi.list();
      setWorkspaces(data);
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        setError(err.message);
      } else {
        setError("Failed to load workspaces. Please check your connection.");
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    workspacesApi
      .list()
      .then((data) => {
        if (isMounted) {
          setWorkspaces(data);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          if (err instanceof ApiRequestError) {
            setError(err.message);
          } else {
            setError("Failed to load workspaces. Please check your connection.");
          }
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleCreateWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setFormError("Workspace name is required.");
      return;
    }

    setFormError(null);
    setIsSubmitting(true);

    try {
      const newWs = await workspacesApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      setWorkspaces((prev) => [newWs, ...prev]);
      setName("");
      setDescription("");
      setIsModalOpen(false);
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        setFormError(err.message);
      } else {
        setFormError("Could not create workspace. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteWorkspace = async (
    e: React.MouseEvent,
    workspaceId: string
  ) => {
    e.preventDefault();
    e.stopPropagation();

    if (!confirm("Are you sure you want to delete this workspace?")) {
      return;
    }

    setDeletingId(workspaceId);
    try {
      await workspacesApi.delete(workspaceId);
      setWorkspaces((prev) => prev.filter((w) => w.id !== workspaceId));
    } catch (err: unknown) {
      const message =
        err instanceof ApiRequestError ? err.message : "Failed to delete workspace";
      alert(message);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <DashboardShell>
      <div className="mx-auto max-w-4xl space-y-6">
        {/* Header bar with Action */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">
              My Workspaces
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Select an existing workspace or create a new one to organize your research.
            </p>
          </div>

          <button
            onClick={() => {
              setFormError(null);
              setIsModalOpen(true);
            }}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 transition"
          >
            <Plus className="h-4 w-4" />
            <span>New Workspace</span>
          </button>
        </div>

        {/* Global Fetch Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4">
            <p className="text-sm font-medium text-red-800">{error}</p>
            <button
              onClick={refreshWorkspaces}
              className="mt-2 text-xs font-semibold text-red-700 underline hover:text-red-900"
            >
              Try again
            </button>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-24 w-full animate-pulse rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
              />
            ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !error && workspaces.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-gray-300 bg-white p-12 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-600">
              <FolderKanban className="h-6 w-6" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-gray-900">
              No workspaces yet
            </h3>
            <p className="mt-1 max-w-sm text-sm text-gray-500">
              Get started by creating your first workspace to manage documents and research.
            </p>
            <button
              onClick={() => setIsModalOpen(true)}
              className="mt-6 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 transition"
            >
              <Plus className="h-4 w-4" />
              <span>Create Workspace</span>
            </button>
          </div>
        )}

        {/* Workspaces List */}
        {!isLoading && !error && workspaces.length > 0 && (
          <div className="space-y-3">
            {workspaces.map((workspace) => (
              <Link
                key={workspace.id}
                href={`/workspaces/${workspace.id}`}
                className="group flex items-center justify-between rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
              >
                <div className="flex items-start gap-4 min-w-0">
                  <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 group-hover:bg-indigo-100 group-hover:text-indigo-700 transition">
                    <FolderKanban className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-gray-900 truncate group-hover:text-indigo-600 transition">
                      {workspace.name}
                    </h2>
                    {workspace.description ? (
                      <p className="mt-0.5 text-sm text-gray-500 line-clamp-1">
                        {workspace.description}
                      </p>
                    ) : (
                      <p className="mt-0.5 text-xs text-gray-400 italic">
                        No description provided
                      </p>
                    )}
                    <span className="mt-2 inline-block text-xs text-gray-400">
                      Created {new Date(workspace.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0 ml-4">
                  <button
                    type="button"
                    title="Delete workspace"
                    onClick={(e) => handleDeleteWorkspace(e, workspace.id)}
                    disabled={deletingId === workspace.id}
                    className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-600 transition disabled:opacity-50"
                  >
                    {deletingId === workspace.id ? (
                      <Loader2 className="h-4 w-4 animate-spin text-red-600" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </button>
                  <div className="rounded-lg p-2 text-gray-400 group-hover:translate-x-1 group-hover:text-indigo-600 transition">
                    <ArrowRight className="h-4 w-4" />
                  </div>
                </div>
              </Link>
            ))}

            {/* Bottom New Workspace trigger matching wireframe */}
            <div className="pt-2 text-center">
              <button
                onClick={() => setIsModalOpen(true)}
                className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 hover:text-indigo-700 hover:underline"
              >
                <Plus className="h-4 w-4" />
                <span>+ New Workspace</span>
              </button>
            </div>
          </div>
        )}

        {/* Create Workspace Modal */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl border border-gray-200 animate-in fade-in zoom-in-95 duration-150">
              <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                <h3 className="text-lg font-semibold text-gray-900">
                  Create Workspace
                </h3>
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {formError && (
                <div className="mt-4 rounded-lg bg-red-50 p-3 border border-red-200">
                  <p className="text-xs font-medium text-red-800">{formError}</p>
                </div>
              )}

              <form onSubmit={handleCreateWorkspace} className="mt-4 space-y-4">
                <div>
                  <label
                    htmlFor="ws-name"
                    className="block text-sm font-medium text-gray-700"
                  >
                    Workspace Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    id="ws-name"
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. LLM Research"
                    className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="ws-desc"
                    className="block text-sm font-medium text-gray-700"
                  >
                    Description <span className="text-xs text-gray-400">(optional)</span>
                  </label>
                  <textarea
                    id="ws-desc"
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What is this workspace for?"
                    className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus:outline-none disabled:opacity-50 transition"
                  >
                    {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                    <span>{isSubmitting ? "Creating..." : "Create"}</span>
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </DashboardShell>
  );
}
