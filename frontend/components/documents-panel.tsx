"use client";

import { useCallback, useEffect, useState } from "react";
import { documentsApi } from "@/lib/api";
import { Document, SearchResult } from "@/types";

export function DocumentsPanel({ workspaceId }: { workspaceId: string }) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chunkSize, setChunkSize] = useState(1024);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [method, setMethod] = useState<"vector" | "bm25" | "hybrid" | "hybrid_reranked">("vector");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocuments(await documentsApi.list(workspaceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load documents.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    let active = true;
    documentsApi.list(workspaceId).then((data) => {
      if (active) setDocuments(data);
    }).catch((err) => {
      if (active) setError(err instanceof Error ? err.message : "Could not load documents.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [workspaceId]);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const document = await documentsApi.upload(workspaceId, file, chunkSize);
      setDocuments((previous) => [document, ...previous]);
      setResults(null);
      if (document.status === "failed") setError(document.error || "Ingestion failed.");
    } catch (err) {
      setError(`${err instanceof Error ? err.message : "Upload failed."} Refresh the list before retrying; processing may have continued on the server.`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(document: Document) {
    if (!confirm(`Delete ${document.filename} and its searchable chunks?`)) return;
    setBusy(true);
    setError(null);
    try {
      await documentsApi.delete(workspaceId, document.id);
      setDocuments((previous) => previous.filter((item) => item.id !== document.id));
      setResults(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deletion failed.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="space-y-6">
    <section className="rounded-xl border border-gray-200 bg-white p-6 space-y-4">
      <h3 className="text-lg font-semibold">Workspace documents</h3>
      <p className="text-sm text-gray-500">Upload a text-based PDF. Extraction and CPU embedding finish before the upload response. The first upload may take longer while the model downloads. Scanned PDFs need OCR and are not supported yet.</p>
      <div className="flex flex-wrap items-end gap-4">
        <label className="text-sm font-medium">Chunk size (characters)
          <select value={chunkSize} disabled={busy} onChange={(event) => setChunkSize(Number(event.target.value))} className="ml-2 rounded border border-gray-300 p-2">
            {[256, 512, 1024].map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <label className="text-sm font-medium">PDF file
          <input type="file" accept=".pdf,application/pdf" disabled={busy} className="ml-2 block text-sm mt-1" onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void upload(file);
          }} />
        </label>
        <button onClick={refresh} disabled={busy || loading} className="text-sm text-indigo-600 underline disabled:opacity-50">Refresh list</button>
      </div>
      <p className="text-xs text-gray-500">Overlap: 64 characters. Each upload creates a separate document, so you can compare chunk sizes.</p>
      {busy && <p role="status" className="text-sm text-indigo-600">Working… please keep this page open.</p>}
      {error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {loading ? <p role="status">Loading documents…</p> : documents.length === 0 ? <p className="text-sm text-gray-500">No documents yet.</p> :
        <ul className="divide-y divide-gray-100">{documents.map((document) => <li key={document.id} className="py-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-medium break-words">{document.filename}</p>
            <p className="text-xs text-gray-500">{document.status} · {document.chunk_count} chunks · {new Date(document.created_at).toLocaleString()}</p>
            {document.error && <p className="text-sm text-red-700">{document.error}</p>}
          </div>
          <button disabled={busy} onClick={() => remove(document)} className="text-sm text-red-600 disabled:opacity-50">Delete</button>
        </li>)}</ul>}
    </section>

    <section className="rounded-xl border border-gray-200 bg-white p-6 space-y-4">
      <h3 className="text-lg font-semibold">Search document passages</h3>
      <p className="text-sm text-gray-500">Choose meaning-based vector search keyword matching with BM25, or combined hybrid ranking. Results include source passages. Scores rank results within each method; they are not confidence scores or comparable across methods.</p>
      <form className="flex flex-wrap gap-3" onSubmit={async (event) => {
        event.preventDefault();
        setSearching(true); setSearchError(null); setResults(null);
        try { setResults(await documentsApi.search(workspaceId, query, topK, method)); }
        catch (err) { setSearchError(err instanceof Error ? err.message : "Search failed."); }
        finally { setSearching(false); }
      }}>
        <input aria-label="Search query" value={query} maxLength={1024} onChange={(event) => setQuery(event.target.value)} placeholder="What does the document say about…?" className="min-w-48 flex-1 rounded border border-gray-300 p-2" />
        <label className="text-sm">Top-k <select value={topK} onChange={(event) => setTopK(Number(event.target.value))} className="rounded border border-gray-300 p-2">{[1, 3, 5, 10].map((k) => <option key={k}>{k}</option>)}</select></label>
        <label className="text-sm">Method <select value={method} disabled={searching} onChange={(event) => { setMethod(event.target.value as "vector" | "bm25" | "hybrid" | "hybrid_reranked"); setResults(null); }} className="rounded border border-gray-300 p-2"><option value="vector">Vector (meaning)</option><option value="bm25">BM25 (keywords)</option><option value="hybrid">Hybrid (combined)</option><option value="hybrid_reranked">Hybrid + reranker</option></select></label>
        <button disabled={searching || !query.trim()} className="rounded bg-indigo-600 px-4 py-2 text-white disabled:opacity-50">{searching ? "Searching…" : "Search"}</button>
      </form>
      {searchError && <p role="alert" className="text-sm text-red-700">{searchError}</p>}
      {results?.length === 0 && <p className="text-sm text-gray-500">No matching passages found in ready documents.</p>}
      {results?.map((result) => <article key={result.chunk_id} className="rounded border border-gray-200 p-4">
        {result.rerank_status === "fallback" && <p className="text-xs text-amber-700">Reranking unavailable; showing hybrid order.</p>}
        <p className="text-xs font-medium text-indigo-700">{result.filename} · page {result.page} · chunk {result.chunk_index} · {result.retrieval_method === "hybrid_reranked" ? `Reranker ${result.rerank_score?.toFixed(3)}` : result.retrieval_method === "hybrid" ? `RRF ${result.fusion_score?.toFixed(4)}` : result.retrieval_method === "bm25" ? `BM25 ${result.bm25_score?.toFixed(3)}` : `cosine ${result.similarity?.toFixed(3)}`}</p>
        <p className="mt-2 text-sm whitespace-pre-wrap">{result.content}</p>
      </article>)}
    </section>
  </div>;
}
