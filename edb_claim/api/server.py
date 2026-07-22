"""FastAPI server for the EDB RIS(C) claim app.

Wraps the deterministic pipeline behind a small HTTP surface and serves the
built React frontend (``webui/dist``). The headline endpoint, ``POST /api/analyze``,
**streams** newline-delimited JSON progress events while the engine runs, then a
final ``result`` event — this powers the verbose loading screen. All other
endpoints are read-only views over a single in-memory analysis session.

Run:  .venv/bin/uvicorn edb_claim.api.server:app --port 8000
(or use ./run_web.sh, which builds the frontend first).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from edb_claim.api.serialize import result_to_dict
from edb_claim.app.pipeline import SupportingDocs, run_pipeline
from edb_claim.app.preview import excel_sheet_to_grid, parse_cell_ref, resolve_evidence_path
from edb_claim.config import settings

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SAMPLE_DIR = os.path.join(_REPO_ROOT, "sample_data")
_SAMPLE_INTERNAL = [
    os.path.join(_SAMPLE_DIR, "internal_ANS.xlsx"),
    os.path.join(_SAMPLE_DIR, "internal_DSG.xlsx"),
]
_SAMPLE_RSE = os.path.join(_SAMPLE_DIR, "rse_list.xlsx")
_SAMPLE_PAYROLL = os.path.join(_SAMPLE_DIR, "payroll.xlsx")
_TEMPLATE = os.path.join(_REPO_ROOT, "docs", "EDB_Output Template.xlsx")
_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(title="EDB RIS(C) Claim API", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """Never cache index.html / API responses so the browser always loads the
    current build (Vite asset filenames are hashed, but index.html must be fresh
    — otherwise a stale tab references deleted assets and the app looks broken)."""
    resp = await call_next(request)
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("text/html") or request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp

# In-memory sessions: one per analysis run. Holds the live PipelineResult (for
# downloads / serialisation) plus a filename->path registry for evidence preview.
_SESSIONS: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _save_upload(up: UploadFile, workdir: str) -> str:
    safe = os.path.basename(up.filename or "upload.xlsx")
    path = os.path.join(workdir, safe)
    with open(path, "wb") as fh:
        fh.write(up.file.read())
    return path


def _truthy(v: Optional[str]) -> Optional[bool]:
    """Tri-state form flag: 'true'/'false' -> bool, anything else/None -> None."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return None


def _sse(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def _entity_slug(entity: str) -> str:
    name = entity.replace("ST Engineering", "").replace("Pte Ltd", "").replace("Ltd", "")
    words = "".join(c if c.isalnum() else " " for c in name).split()
    return ("_".join(words) or "Entity")[:32]


def _build_pack(res, workdir: str, template_path: Optional[str] = None) -> Dict[str, str]:
    """Generate the three submission documents; return {filename: path}.

    Uses the HR-uploaded EDB output template when provided, else the shipped one.
    """
    from edb_claim.output.edb_writer import fill_edb_template
    from edb_claim.output.reports import build_exclusions_report
    from edb_claim.output.soe import build_soe

    tmpl = template_path if (template_path and os.path.exists(template_path)) else _TEMPLATE
    ts = datetime.now()
    out: Dict[str, str] = {}
    out["Statement_of_Expenditure.xlsx"] = build_soe(
        res, os.path.join(workdir, "Statement_of_Expenditure.xlsx"), timestamp=ts)
    out["Issues_to_fix.xlsx"] = build_exclusions_report(
        res, os.path.join(workdir, "Issues_to_fix.xlsx"), timestamp=ts)
    if os.path.exists(tmpl):
        for ent in res.entities:
            if not any(e.qualifies for e in ent.employees):
                continue
            fname = f"EDB_Submission_{_entity_slug(ent.entity)}.xlsx"
            out[fname] = fill_edb_template(
                ent, os.path.join(workdir, fname), template_path=tmpl, timestamp=ts)
    return out


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "llm_enabled": settings.llm_enabled,
        "sample_available": all(os.path.exists(p) for p in
                                _SAMPLE_INTERNAL + [_SAMPLE_RSE, _SAMPLE_PAYROLL]),
        "support_rate": settings.support_rate,
        "support_rate_is_final": settings.support_rate_is_final,
        "claim_period": [settings.claim_period_start.isoformat(),
                         settings.claim_period_end.isoformat()],
        "application_no": "S26-10249-RIS(C)",
    }


@app.post("/api/analyze")
async def analyze(
    mode: str = Form("upload"),
    edb_template: Optional[UploadFile] = File(default=None),  # HR's EDB output template
    trainee_list: Optional[UploadFile] = File(default=None),  # roster of trainees
    timesheets: List[UploadFile] = File(default=[]),
    rse: Optional[UploadFile] = File(default=None),
    payroll: List[UploadFile] = File(default=[]),
    # supporting-evidence checklist (tri-state form flags)
    risc: Optional[str] = Form(None),
    loa: Optional[str] = Form(None),
    skill: Optional[str] = Form(None),
    trainee: Optional[str] = Form(None),
    artifacts: Optional[str] = Form(None),
    leave: Optional[str] = Form(None),
    cpf: Optional[str] = Form(None),
    pl3: Optional[str] = Form(None),
    cert: Optional[str] = Form(None),
    progress: Optional[str] = Form(None),
    clocking: Optional[str] = Form(None),
):
    """Run the pipeline and stream NDJSON progress, then the final result.

    The browser reads the streamed body with a ReadableStream reader; each line
    is a JSON event of type ``progress`` | ``result`` | ``error``.
    """
    workdir = tempfile.mkdtemp(prefix="edb_api_")
    registry: Dict[str, str] = {}
    docs: List[dict] = []

    template_path: Optional[str] = None  # uploaded EDB template (else shipped one)

    # Resolve inputs up-front (so file reads happen before the stream starts).
    if mode == "sample":
        internal_paths = list(_SAMPLE_INTERNAL)
        rse_path = _SAMPLE_RSE
        payroll_paths = [_SAMPLE_PAYROLL]
        for p in internal_paths + [rse_path] + payroll_paths:
            registry[os.path.basename(p)] = p
        docs = (
            [{"label": "Team timesheet", "name": os.path.basename(p)} for p in internal_paths]
            + [{"label": "ECMF researcher list", "name": os.path.basename(rse_path)},
               {"label": "Payroll / payslips", "name": os.path.basename(_SAMPLE_PAYROLL)}]
        )
    else:
        internal_paths = []
        # 1) EDB output template (provided first); used to fill the submission output
        if edb_template:
            template_path = _save_upload(edb_template, workdir)
            registry[os.path.basename(template_path)] = template_path
            docs.append({"label": "EDB output template", "name": os.path.basename(template_path)})
        # 2) trainee list (roster the documents are tracked against)
        if trainee_list:
            tl = _save_upload(trainee_list, workdir)
            registry[os.path.basename(tl)] = tl
            docs.append({"label": "Trainee list", "name": os.path.basename(tl)})
        for up in timesheets:
            p = _save_upload(up, workdir)
            internal_paths.append(p)
            registry[os.path.basename(p)] = p
            docs.append({"label": "Team timesheet", "name": os.path.basename(p)})
        rse_path = _save_upload(rse, workdir) if rse else None
        if rse_path:
            registry[os.path.basename(rse_path)] = rse_path
            docs.append({"label": "ECMF researcher list", "name": os.path.basename(rse_path)})
        payroll_paths = []
        for up in payroll:  # one OR many payroll/payslip registers — all merged
            pp = _save_upload(up, workdir)
            payroll_paths.append(pp)
            registry[os.path.basename(pp)] = pp
            docs.append({"label": "Payroll / payslips", "name": os.path.basename(pp)})

    supporting = SupportingDocs(
        risc_submission_form=_truthy(risc), letter_of_award=_truthy(loa),
        skill_validation_list=_truthy(skill), trainee_list=_truthy(trainee),
        ai_artifacts=_truthy(artifacts), leave_report=_truthy(leave),
        cpf_bank=_truthy(cpf), pl3_confirmation=_truthy(pl3),
        training_certification=_truthy(cert), monthly_progress_report=_truthy(progress),
        daily_clocking=_truthy(clocking),
    )

    def stream():
        if not internal_paths:
            yield _sse({"type": "error", "message":
                        "Add at least one timesheet workbook to continue."})
            return
        try:
            yield _sse({"type": "progress", "pct": 6, "label": "Saving uploaded documents…",
                        "detail": f"{len(docs)} file(s) received."})
            time.sleep(0.35)
            yield _sse({"type": "progress", "pct": 18, "label": "Reading internal timesheets…",
                        "detail": "Parsing Time Sheet (row 19+) and Staff Costs (row 15+)."})
            time.sleep(0.35)
            yield _sse({"type": "progress", "pct": 32,
                        "label": "Reading ECMF researcher list & payroll…",
                        "detail": "Resolving the qualifying roster and basic monthly salaries."})
            time.sleep(0.3)

            res = run_pipeline(internal_paths, rse_path, payroll_paths, supporting=supporting)

            # per-entity narration from the real result
            pct = 44
            step = max(1, int(36 / max(1, len(res.entities))))
            for ent in res.entities:
                rb = ent.completeness.rollup
                q = sum(1 for e in ent.employees if e.qualifies)
                pct = min(82, pct + step)
                yield _sse({"type": "progress", "pct": pct,
                            "label": f"Checked {ent.entity}",
                            "detail": f"{rb.employee_count} staff · {q} qualify · "
                                      f"{rb.blocker_count} blocker(s) · {rb.warning_count} warning(s)."})
                time.sleep(0.3)

            yield _sse({"type": "progress", "pct": 88,
                        "label": "Calculating claim amounts…",
                        "detail": "Method A (EDB pro-ration) with the internal cross-check."})
            time.sleep(0.3)

            # persist to the evidence store (best-effort, like the Streamlit app)
            try:
                from edb_claim.db.schema import init_db
                from edb_claim.db.store import connect, persist_result
                init_db(settings.db_path)
                conn = connect(settings.db_path)
                try:
                    persist_result(conn, res)
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001 — persistence is additive, never fatal
                pass
            yield _sse({"type": "progress", "pct": 96, "label": "Writing the evidence trail…",
                        "detail": "Every figure linked back to its source cell."})
            time.sleep(0.25)

            session_id = uuid.uuid4().hex
            _SESSIONS[session_id] = {
                "result": res, "registry": registry, "docs": docs, "workdir": workdir,
                "pack": None, "assistant": None, "template": template_path,
            }
            payload = result_to_dict(res)
            payload["session"] = session_id
            payload["docs"] = docs
            yield _sse({"type": "progress", "pct": 100, "label": "Analysis complete", "detail": ""})
            yield _sse({"type": "result", "data": payload})
        except Exception as exc:  # noqa: BLE001 — surface to the UI, don't 500 silently
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class PreviewReq(BaseModel):
    session: str
    file: str
    sheet: Optional[str] = None
    cell: Optional[str] = None
    label: Optional[str] = None


@app.post("/api/preview")
def preview(req: PreviewReq) -> JSONResponse:
    """Return a cited Excel sheet as a grid (the evidence-traceability view)."""
    sess = _SESSIONS.get(req.session)
    if not sess:
        raise HTTPException(404, "session not found")
    path = resolve_evidence_path(req.file, sess["registry"])
    if not path or not os.path.exists(path):
        raise HTTPException(404, "source file not available in this session")
    sheet_ref, col, row = parse_cell_ref(req.cell)
    try:
        grid = excel_sheet_to_grid(path, sheet_ref or req.sheet, focus_col=col, focus_row=row)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"could not render sheet: {exc}")
    return JSONResponse({
        "sheet_name": grid.sheet_name,
        "col_letters": list(grid.col_letters),
        "row_numbers": list(grid.row_numbers),
        "rows": [list(r) for r in grid.rows],
        "focus_col_letter": grid.focus_col_letter,
        "focus_row": grid.focus_row,
        "truncated": grid.truncated,
        "file": os.path.basename(req.file),
        "cell": req.cell,
        "label": req.label,
    })


class ChatReq(BaseModel):
    session: str
    question: str


@app.post("/api/chat")
def chat(req: ChatReq) -> JSONResponse:
    """Answer an audit/scheme question grounded in the session's claim data.

    Delegates to the existing :class:`AuditAssistant` (FR-9→FR-12): exact-SQL
    retrieval for figures, evidence citations for "fetch the evidence for X",
    scheme knowledge otherwise. Works offline (no model needed); when the local
    model endpoint is configured it phrases the grounded facts. Never invents a
    figure — citations point back to the source cells the UI can preview.
    """
    sess = _SESSIONS.get(req.session)
    if not sess:
        raise HTTPException(404, "session not found")
    asst = sess.get("assistant")
    if asst is None:
        from edb_claim.llm.qa import AuditAssistant
        asst = AuditAssistant(db_path=settings.db_path)
        sess["assistant"] = asst
    try:
        ans = asst.answer(req.question, sess["result"])
    except Exception as exc:  # noqa: BLE001 — never 500 the chat; report gracefully
        raise HTTPException(500, f"assistant error: {exc}")
    return JSONResponse({
        "text": ans.text,
        "citations": ans.citations,
        "offline": ans.offline,
        "used_model": ans.used_model,
        "mode": ans.mode,
        "confidence": ans.confidence,
    })


@app.get("/api/downloads/{session}")
def downloads(session: str) -> JSONResponse:
    """List the generated submission-pack files for a session."""
    sess = _SESSIONS.get(session)
    if not sess:
        raise HTTPException(404, "session not found")
    if sess["pack"] is None:
        sess["pack"] = _build_pack(sess["result"], sess["workdir"], sess.get("template"))
    return JSONResponse({"files": list(sess["pack"].keys())})


@app.get("/api/download/{session}/{filename}")
def download(session: str, filename: str) -> FileResponse:
    sess = _SESSIONS.get(session)
    if not sess:
        raise HTTPException(404, "session not found")
    if sess["pack"] is None:
        sess["pack"] = _build_pack(sess["result"], sess["workdir"], sess.get("template"))
    path = sess["pack"].get(os.path.basename(filename))
    if not path or not os.path.exists(path):
        raise HTTPException(404, "file not found")
    return FileResponse(path, media_type=_MIME_XLSX, filename=os.path.basename(filename))


# --- static frontend (built by Vite into webui/dist) -----------------------
_DIST = os.path.join(_REPO_ROOT, "webui", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
