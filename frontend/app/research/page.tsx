"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { BookOpenText, Loader2 } from "lucide-react";
import { DashboardShell } from "@/components/dashboard-shell";
import { researchApi, workspacesApi } from "@/lib/api";
import type { ResearchJobDetail, ResearchJobSummary, ResearchStage, Workspace } from "@/types";

const stages: ResearchStage[] = ["PLANNING", "RETRIEVING", "SYNTHESIZING", "VERIFYING", "SAVING", "COMPLETED"];
const activeStatuses = new Set(["queued", "running", "retrying"]);

function ResearchConsole() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [jobs, setJobs] = useState<ResearchJobSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<ResearchJobDetail | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const hasActive = jobs.some((job) => activeStatuses.has(job.status));

  useEffect(() => {
    let cancelled = false;
    workspacesApi.list().then((items) => {
      if (cancelled) return;
      setWorkspaces(items);
      setWorkspaceId((current) => current || items[0]?.id || "");
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load workspaces.");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!workspaceId) return;
    const [summaries, detail] = await Promise.all([
      researchApi.list(workspaceId, signal),
      selectedId ? researchApi.get(workspaceId, selectedId, signal) : Promise.resolve(null),
    ]);
    if (signal?.aborted) return;
    setJobs(summaries);
    if (detail) setSelected(detail);
  }, [workspaceId, selectedId]);

  useEffect(() => {
    const controller = new AbortController();
    if (!workspaceId) return () => controller.abort();
    const load = () => {
      if (document.hidden) return;
      refresh(controller.signal).catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not refresh research jobs.");
      });
    };
    load();
    const interval = hasActive ? window.setInterval(load, 2500) : undefined;
    document.addEventListener("visibilitychange", load);
    return () => {
      controller.abort();
      if (interval !== undefined) window.clearInterval(interval);
      document.removeEventListener("visibilitychange", load);
    };
  }, [workspaceId, refresh, hasActive]);

  const chooseWorkspace = (id: string) => {
    generation.current += 1;
    setWorkspaceId(id);
    setJobs([]);
    setSelectedId("");
    setSelected(null);
    setError(null);
  };

  const chooseJob = async (id: string) => {
    const request = ++generation.current;
    setSelectedId(id);
    setSelected(null);
    setError(null);
    try {
      const detail = await researchApi.get(workspaceId, id);
      if (request === generation.current) setSelected(detail);
    } catch (reason) {
      if (request === generation.current) setError(reason instanceof Error ? reason.message : "Could not open research job.");
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!workspaceId || !query.trim() || submitting) return;
    const request = ++generation.current;
    setSubmitting(true);
    setError(null);
    try {
      const job = await researchApi.create(workspaceId, query.trim());
      if (request !== generation.current) return;
      setQuery("");
      setSelectedId(job.id);
      setSelected(job);
      setJobs((current) => [job, ...current]);
    } catch (reason) {
      if (request === generation.current) setError(reason instanceof Error ? reason.message : "Could not start research.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-gray-900">Research jobs</h1>
        <p className="mt-1 text-sm text-gray-500">Compare evidence across indexed documents in one workspace.</p>
      </div>
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {loading ? <p className="text-sm text-gray-500">Loading workspaces...</p> : workspaces.length === 0 ? (
        <div className="rounded-xl border bg-white p-6 text-sm text-gray-600">
          Create a workspace and index documents first. <Link href="/" className="font-semibold text-indigo-700">Go to workspaces</Link>
        </div>
      ) : (
        <>
          <form onSubmit={submit} className="space-y-4 rounded-xl border border-gray-200 bg-white p-5 shadow-xs">
            <label className="block text-sm font-medium text-gray-700" htmlFor="research-workspace">Workspace</label>
            <select id="research-workspace" value={workspaceId} onChange={(event) => chooseWorkspace(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
              {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
            </select>
            <label className="block text-sm font-medium text-gray-700" htmlFor="research-query">Research request</label>
            <textarea id="research-query" value={query} onChange={(event) => setQuery(event.target.value)}
              maxLength={1024} rows={3} placeholder="Compare the approaches in these papers for reducing LLM inference memory usage."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            <button type="submit" disabled={submitting || !query.trim()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
              {submitting ? "Starting..." : "Start research"}
            </button>
          </form>
          <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
            <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-xs">
              <h2 className="mb-3 font-semibold text-gray-900">Recent jobs</h2>
              {jobs.length === 0 ? <p className="text-sm text-gray-500">No research jobs yet.</p> : (
                <ul className="space-y-2">
                  {jobs.map((job) => <li key={job.id}>
                    <button type="button" onClick={() => chooseJob(job.id)}
                      className={`w-full rounded-lg border p-3 text-left text-sm ${selectedId === job.id ? "border-indigo-300 bg-indigo-50" : "border-gray-200 hover:bg-gray-50"}`}>
                      <span className="line-clamp-2 font-medium text-gray-900">{job.query}</span>
                      <span className="mt-1 block text-xs capitalize text-gray-500">{job.status} · {job.current_stage.toLowerCase()}</span>
                    </button>
                  </li>)}
                </ul>
              )}
            </section>
            <section className="min-h-80 rounded-xl border border-gray-200 bg-white p-5 shadow-xs">
              {!selected ? <div className="flex h-full flex-col items-center justify-center text-center text-gray-500">
                <BookOpenText className="mb-3 h-9 w-9 text-indigo-500" />
                <p className="text-sm">Choose a job or start a new research request.</p>
              </div> : (
                <div className="space-y-6">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">{selected.query}</h2>
                    <p className="mt-1 text-xs text-gray-500">{selected.status} · attempt {selected.attempt_count}/{selected.max_attempts} · {selected.retrieval_method} retrieval</p>
                    {selected.status === "retrying" && selected.next_retry_at &&
                      <p className="mt-1 text-xs text-amber-700">Retry scheduled for {new Date(selected.next_retry_at).toLocaleString()}</p>}
                    {selected.error && <p className="mt-2 text-sm text-red-700">{selected.error}</p>}
                  </div>
                  <ol className="flex flex-wrap gap-2" aria-label="Research progress">
                    {stages.map((stage) => {
                      const current = stages.indexOf(selected.current_stage);
                      const index = stages.indexOf(stage);
                      return <li key={stage} className={`rounded-full px-3 py-1 text-xs font-medium ${selected.status === "failed" && index === current ? "bg-red-100 text-red-700" : index <= current ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500"}`}>
                        {stage === selected.current_stage && activeStatuses.has(selected.status) && <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />}
                        {stage.toLowerCase()}
                      </li>;
                    })}
                  </ol>
                  {selected.steps.length > 0 && <div className="text-xs text-gray-600">
                    {selected.steps.map((step) => <p key={step.stage}>
                      {step.stage.toLowerCase()}: {step.status} after {step.attempt_count} attempt{step.attempt_count === 1 ? "" : "s"}
                    </p>)}
                  </div>}
                  {selected.plan && <div>
                    <h3 className="font-semibold text-gray-900">Planned questions</h3>
                    <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-gray-700">
                      {selected.plan.questions.map((question, index) => <li key={index}>{question}</li>)}
                    </ol>
                  </div>}
                  {selected.result && <div className="space-y-5">
                    {selected.result.sections.map((section, index) => <section key={index}>
                      <h3 className="font-semibold text-gray-900">{section.question}</h3>
                      {section.claims.length === 0 ? <p className="mt-2 text-sm text-gray-500">Insufficient evidence in the indexed documents.</p> :
                        section.claims.map((claim, claimIndex) => <p key={claimIndex} className="mt-2 text-sm leading-6 text-gray-700">
                          {claim.text} {claim.citation_ids.map((id) => <a key={id} href={`#research-source-${id}`} className="font-semibold text-indigo-700">[{id}]</a>)}
                        </p>)}
                    </section>)}
                    {selected.result.sources.length > 0 && <section>
                      <h3 className="font-semibold text-gray-900">Sources</h3>
                      <ol className="mt-2 space-y-2 text-sm text-gray-700">
                        {selected.result.sources.map((source) => <li id={`research-source-${source.id}`} key={source.id}>
                          [{source.id}] {source.document} · page {source.page}: “{source.quote}”
                        </li>)}
                      </ol>
                    </section>}
                  </div>}
                  {selected.evidence && <details className="text-sm text-gray-600">
                    <summary className="cursor-pointer font-medium">Inspect retrieved evidence ({selected.evidence.length})</summary>
                    <ul className="mt-2 space-y-3">
                      {selected.evidence.map((item) => <li key={item.source_id} className="rounded-lg bg-gray-50 p-3">
                        <strong>[{item.source_id}] {item.filename} · page {item.page}</strong>
                        <p className="mt-1 whitespace-pre-wrap">{item.content}</p>
                      </li>)}
                    </ul>
                  </details>}
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

export default function ResearchOverviewPage() {
  return <DashboardShell><ResearchConsole /></DashboardShell>;
}
