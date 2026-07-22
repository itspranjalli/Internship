import type { AnalysisResult, ChatAnswer, Health, StreamEvent, Supporting } from "./types";

export async function getHealth(): Promise<Health> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health check failed");
  return r.json();
}

export interface AnalyzeInputs {
  mode: "sample" | "upload";
  edbTemplate: File | null;
  trainee: File | null;
  timesheets: File[];
  rse: File | null;
  payroll: File[];
  supporting: Supporting;
}

/**
 * POST the documents and consume the streamed NDJSON progress feed. Each parsed
 * line is handed to `onEvent`; the promise resolves once the stream ends.
 */
export async function analyzeStream(
  inputs: AnalyzeInputs,
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const fd = new FormData();
  fd.append("mode", inputs.mode);
  if (inputs.mode === "upload") {
    if (inputs.edbTemplate) fd.append("edb_template", inputs.edbTemplate);
    if (inputs.trainee) fd.append("trainee_list", inputs.trainee);
    inputs.timesheets.forEach((f) => fd.append("timesheets", f));
    if (inputs.rse) fd.append("rse", inputs.rse);
    inputs.payroll.forEach((f) => fd.append("payroll", f));
  }
  const s = inputs.supporting;
  (Object.keys(s) as (keyof Supporting)[]).forEach((k) => fd.append(k, String(s[k])));

  const resp = await fetch("/api/analyze", { method: "POST", body: fd, signal });
  if (!resp.ok || !resp.body) throw new Error(`analyze failed (${resp.status})`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as StreamEvent);
    }
  }
  const tail = buffer.trim();
  if (tail) onEvent(JSON.parse(tail) as StreamEvent);
}

export interface PreviewGrid {
  sheet_name: string;
  col_letters: string[];
  row_numbers: number[];
  rows: string[][];
  focus_col_letter: string | null;
  focus_row: number | null;
  truncated: boolean;
  file: string;
  cell: string | null;
  label: string | null;
}

export async function fetchPreview(
  session: string,
  file: string,
  sheet: string | null,
  cell: string | null,
  label: string | null
): Promise<PreviewGrid> {
  const r = await fetch("/api/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session, file, sheet, cell, label }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "preview failed");
  return r.json();
}

export async function listDownloads(session: string): Promise<string[]> {
  const r = await fetch(`/api/downloads/${session}`);
  if (!r.ok) throw new Error("downloads list failed");
  return (await r.json()).files as string[];
}

export function downloadUrl(session: string, filename: string): string {
  return `/api/download/${session}/${encodeURIComponent(filename)}`;
}

export async function sendChat(session: string, question: string): Promise<ChatAnswer> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session, question }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "assistant error");
  return r.json();
}

export type { AnalysisResult };
