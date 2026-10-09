"use client";

import React, { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  MessageSquare,
  Sparkles,
  Upload,
  Send,
  Loader2,
  Calendar,
  AlertCircle,
  FileCode,
  Bot,
  User as UserIcon,
} from "lucide-react";
import { DashboardShell } from "@/components/dashboard-shell";
import { workspacesApi, ApiRequestError } from "@/lib/api";
import { Workspace } from "@/types";

type TabType = "documents" | "chat" | "research";

interface ChatMessage {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
}

interface MockDoc {
  id: string;
  name: string;
  size: string;
  status: "Ready" | "Processing";
  uploadedAt: string;
}

function WorkspaceContent() {
  const params = useParams();
  const workspaceId = params?.id as string;

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("documents");

  // Documents tab state
  const [documents, setDocuments] = useState<MockDoc[]>([
    {
      id: "doc-1",
      name: "Getting-Started-Guide.pdf",
      size: "1.2 MB",
      status: "Ready",
      uploadedAt: new Date().toLocaleDateString(),
    },
  ]);
  const [isUploading, setIsUploading] = useState(false);

  // Chat tab state
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "msg-1",
      sender: "ai",
      text: "Hello! This is your workspace AI assistant. In Phase 4, questions you ask here will be answered using semantic RAG over your uploaded documents.",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [chatInput, setChatInput] = useState("");

  // Research tab state
  const [researchNotes, setResearchNotes] = useState(
    "### Workspace Research Objectives\n- Synthesize key findings from uploaded documents.\n- Extract core definitions, architectures, and performance benchmarks.\n- Formulate follow-up research questions."
  );
  const [isSaved, setIsSaved] = useState(false);

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

  const handleSimulateUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setTimeout(() => {
      const newDoc: MockDoc = {
        id: `doc-${Date.now()}`,
        name: file.name,
        size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
        status: "Ready",
        uploadedAt: new Date().toLocaleDateString(),
      };
      setDocuments((prev) => [newDoc, ...prev]);
      setIsUploading(false);
    }, 600);
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;

    const userText = chatInput.trim();
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      sender: "user",
      text: userText,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setChatInput("");

    // Simulate AI response preview for Phase 2
    setTimeout(() => {
      const aiReply: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        sender: "ai",
        text: `Received: "${userText}". Full RAG response generation will connect when Phase 4 indexing is enabled!`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, aiReply]);
    }, 500);
  };

  const handleSaveNotes = () => {
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

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
                <div className="flex items-center gap-1 text-xs text-gray-400">
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
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {documents.length}
                  </span>
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
            {activeTab === "documents" && (
              <div className="space-y-6">
                {/* Upload bar */}
                <div className="flex flex-col gap-4 rounded-xl border border-dashed border-gray-300 bg-white p-6 text-center sm:flex-row sm:items-center sm:justify-between sm:text-left">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">
                      Workspace Documents
                    </h3>
                    <p className="mt-0.5 text-xs text-gray-500">
                      Upload PDFs, markdown, or text files to build this workspace&apos;s knowledge base.
                    </p>
                  </div>
                  <div>
                    <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-indigo-500 transition">
                      {isUploading ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Upload className="h-4 w-4" />
                      )}
                      <span>{isUploading ? "Uploading..." : "Upload Document"}</span>
                      <input
                        type="file"
                        className="hidden"
                        onChange={handleSimulateUpload}
                        disabled={isUploading}
                      />
                    </label>
                  </div>
                </div>

                {/* Documents list */}
                <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xs">
                  <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
                    <thead className="bg-gray-50 text-xs font-semibold text-gray-500 uppercase">
                      <tr>
                        <th className="px-6 py-3">Document Name</th>
                        <th className="px-6 py-3">Size</th>
                        <th className="px-6 py-3">Status</th>
                        <th className="px-6 py-3">Uploaded</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {documents.map((doc) => (
                        <tr key={doc.id} className="hover:bg-gray-50 transition">
                          <td className="px-6 py-4 font-medium text-gray-900 flex items-center gap-3">
                            <FileCode className="h-5 w-5 text-indigo-500" />
                            <span>{doc.name}</span>
                          </td>
                          <td className="px-6 py-4 text-gray-500">{doc.size}</td>
                          <td className="px-6 py-4">
                            <span className="inline-flex items-center rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                              {doc.status}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-gray-500">{doc.uploadedAt}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB 2: CHAT */}
            {activeTab === "chat" && (
              <div className="flex h-[550px] flex-col rounded-2xl border border-gray-200 bg-white shadow-xs">
                {/* Messages stream */}
                <div className="flex-1 space-y-4 overflow-y-auto p-6">
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`flex gap-3 ${
                        msg.sender === "user" ? "justify-end" : "justify-start"
                      }`}
                    >
                      {msg.sender === "ai" && (
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
                          <Bot className="h-4 w-4" />
                        </div>
                      )}
                      <div
                        className={`max-w-md rounded-2xl px-4 py-3 text-sm shadow-xs ${
                          msg.sender === "user"
                            ? "bg-indigo-600 text-white"
                            : "bg-gray-100 text-gray-800"
                        }`}
                      >
                        <p className="whitespace-pre-wrap">{msg.text}</p>
                        <span
                          className={`mt-1 block text-right text-[10px] ${
                            msg.sender === "user" ? "text-indigo-200" : "text-gray-400"
                          }`}
                        >
                          {msg.timestamp}
                        </span>
                      </div>
                      {msg.sender === "user" && (
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-gray-600">
                          <UserIcon className="h-4 w-4" />
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {/* Chat input box */}
                <form
                  onSubmit={handleSendMessage}
                  className="flex items-center gap-2 border-t border-gray-200 p-4"
                >
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder={`Ask questions about "${workspace.name}"...`}
                    className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 shadow-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <button
                    type="submit"
                    disabled={!chatInput.trim()}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-indigo-500 disabled:opacity-50 transition"
                  >
                    <Send className="h-4 w-4" />
                    <span>Send</span>
                  </button>
                </form>
              </div>
            )}

            {/* TAB 3: RESEARCH */}
            {activeTab === "research" && (
              <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-xs space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-gray-900">
                      Workspace Research Notes & Synthesis
                    </h3>
                    <p className="text-xs text-gray-500">
                      Take structured notes and capture insights for this workspace.
                    </p>
                  </div>
                  <button
                    onClick={handleSaveNotes}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition"
                  >
                    {isSaved ? "Saved!" : "Save Notes"}
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
