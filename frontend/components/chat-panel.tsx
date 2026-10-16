"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Send } from "lucide-react";
import { ApiRequestError, workspacesApi } from "@/lib/api";
import { ChatResponse } from "@/types";

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  result?: ChatResponse;
}

export function ChatPanel({ workspaceId }: { workspaceId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setBusy(true);
    setError(null);
    setInput("");
    setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: "user", text: message }]);
    try {
      const result = await workspacesApi.chat(workspaceId, message, controller.signal);
      if (controller.signal.aborted) return;
      setMessages((previous) => [...previous, {
        id: crypto.randomUUID(), role: "assistant", text: result.answer, result,
      }]);
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(failure instanceof ApiRequestError ? failure.message : "Could not get an answer. Please try again.");
      setInput(message);
    } finally {
      if (!controller.signal.aborted) {
        activeRequest.current = null;
        setBusy(false);
      }
    }
  }

  return (
    <section className="flex min-h-[550px] flex-col rounded-2xl border border-gray-200 bg-white shadow-xs" aria-label="Document chat">
      <p className="border-b border-gray-200 p-4 text-sm text-gray-500">
        Ask a self-contained question about your uploaded PDFs. Answers include source evidence.
        Each question is independent; this conversation is not saved.
      </p>
      <div className="max-h-[650px] flex-1 space-y-5 overflow-y-auto p-6" aria-live="polite">
        {messages.length === 0 && <p className="text-sm text-gray-500">Upload a PDF in Documents, then ask a question here.</p>}
        {messages.map((message) => (
          <article key={message.id} className={`rounded-xl p-4 text-sm ${message.role === "user" ? "ml-8 bg-indigo-50" : "mr-8 bg-gray-50"}`}>
            <p className="mb-2 font-semibold">{message.role === "user" ? "You" : "Answer"}</p>
            <p className="whitespace-pre-wrap break-words">{message.text}</p>
            {message.result?.retrieved_chunks.some((chunk) => chunk.rerank_status === "fallback") && <p className="mt-2 text-amber-700">Reranking unavailable; evidence uses hybrid order.</p>}
            {!!message.result?.sources.length && (
              <div className="mt-4 border-t border-gray-200 pt-3">
                <p className="font-semibold">Sources</p>
                <ul className="mt-2 space-y-3">
                  {message.result.sources.map((source) => (
                    <li key={source.id}>
                      <p>[{source.id}] {source.document} — Page {source.page}</p>
                      <blockquote className="mt-1 border-l-2 border-indigo-200 pl-3 text-gray-600">{source.quote}</blockquote>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!message.result?.retrieved_chunks.length && (
              <details className="mt-4 text-gray-600">
                <summary className="cursor-pointer">Inspect retrieved passages</summary>
                {message.result.retrieved_chunks.map((chunk, index) => (
                  <div key={chunk.chunk_id} className="mt-3 border-t border-gray-200 pt-2">
                    <p className="font-medium">Rank {index + 1}: {chunk.filename} — Page {chunk.page}</p>
                    <p className="mt-1 whitespace-pre-wrap">{chunk.content}</p>
                  </div>
                ))}
              </details>
            )}
          </article>
        ))}
        {busy && <p role="status" className="flex items-center gap-2 text-sm text-gray-500"><Loader2 className="h-4 w-4 animate-spin" /> Finding evidence and preparing an answer…</p>}
      </div>
      {error && <p role="alert" className="px-4 pb-3 text-sm text-red-700">{error}</p>}
      <form onSubmit={send} className="flex gap-2 border-t border-gray-200 p-4">
        <input aria-label="Question about your documents" value={input} onChange={(event) => setInput(event.target.value)}
          maxLength={1024} disabled={busy} placeholder="What are the main limitations of the proposed approach?"
          className="min-w-0 flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm disabled:opacity-60" />
        <button type="submit" disabled={busy || !input.trim()} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">
          <Send className="h-4 w-4" /> Send
        </button>
      </form>
    </section>
  );
}
