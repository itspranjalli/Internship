import { useEffect, useState } from "react";
import { fetchPreview, type PreviewGrid } from "../api";
import { Spinner, X } from "./icons";

export interface Cite {
  file: string;
  sheet: string | null;
  cell: string | null;
  label: string | null;
}

export default function Evidence({
  session,
  cite,
  onClose,
}: {
  session: string;
  cite: Cite | null;
  onClose: () => void;
}) {
  const [grid, setGrid] = useState<PreviewGrid | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!cite) return;
    setGrid(null);
    setErr(null);
    setLoading(true);
    fetchPreview(session, cite.file, cite.sheet, cite.cell, cite.label)
      .then(setGrid)
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [session, cite]);

  if (!cite) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        className="card flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink">{cite.label || "Source evidence"}</div>
            <div className="truncate text-xs text-slate-400">
              {cite.file}
              {grid?.sheet_name && ` · sheet ${grid.sheet_name}`}
              {cite.cell && ` · cell ${cite.cell}`}
            </div>
          </div>
          <button className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" onClick={onClose}>
            <X />
          </button>
        </div>

        <div className="overflow-auto p-4">
          {loading && (
            <div className="flex items-center gap-2 p-8 text-sm text-slate-500">
              <Spinner className="text-edb-500" /> Loading the original document…
            </div>
          )}
          {err && (
            <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-800">
              {err} — the original file may not be available in this session.
            </div>
          )}
          {grid && (
            <>
              <div className="mb-2 text-xs text-slate-400">
                The cited cell is highlighted.{grid.truncated && " Showing a window of the sheet."}
              </div>
              <div className="overflow-auto rounded-xl border border-slate-200">
                <table className="border-collapse font-mono text-xs">
                  <tbody>
                    <tr>
                      <th className="sticky left-0 z-10 border border-slate-200 bg-edb-700 px-2 py-1 text-white" />
                      {grid.col_letters.map((c) => (
                        <th
                          key={c}
                          className={
                            "border border-slate-200 px-3 py-1 text-white " +
                            (c === grid.focus_col_letter ? "bg-edb-500" : "bg-edb-700")
                          }
                        >
                          {c}
                        </th>
                      ))}
                    </tr>
                    {grid.rows.map((row, ri) => {
                      const rnum = grid.row_numbers[ri];
                      return (
                        <tr key={rnum}>
                          <th
                            className={
                              "sticky left-0 z-10 border border-slate-200 px-2 py-1 text-white " +
                              (rnum === grid.focus_row ? "bg-edb-500" : "bg-edb-700")
                            }
                          >
                            {rnum}
                          </th>
                          {row.map((val, ci) => {
                            const focus =
                              rnum === grid.focus_row &&
                              grid.col_letters[ci] === grid.focus_col_letter;
                            return (
                              <td
                                key={ci}
                                className={
                                  "max-w-[220px] truncate border px-3 py-1 " +
                                  (focus
                                    ? "border-2 border-amber-500 bg-amber-200 font-semibold"
                                    : "border-slate-100 bg-white text-slate-700")
                                }
                              >
                                {val}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
