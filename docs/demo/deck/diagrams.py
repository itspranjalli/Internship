"""The four architecture diagrams, authored once as node/edge graphs.

Coordinates are a normalized 0-100 space (x right, y down) so the same graph
renders to pptx autoshapes and to inline SVG at whatever size each medium wants.

Edge geometry is solved HERE, by ``edge_points``, not in the renderers — that is
the whole point of the design. Both backends draw the identical polyline, so the
pptx and the web deck can never drift. Paths are straight or orthogonal elbows
only: MSO connectors cannot reproduce beziers.
"""

# node kinds → semantic role; each renderer maps these to its own palette
CORE = "core"        # deterministic pipeline module
SURFACE = "surface"  # UI / API
LLM = "llm"          # model-touching module
DATA = "data"        # persistence
OUT = "out"          # generated artifact
SEAL = "seal"        # the sealed deterministic region
GROUP = "group"      # a container/backdrop, drawn first, no arrows
NOTE = "note"        # caption block


def N(id, label, x, y, w, h, kind=CORE, sub=None):
    return {"id": id, "label": label, "sub": sub, "x": x, "y": y,
            "w": w, "h": h, "kind": kind}


def E(a, b, style="solid", label=None, side=None):
    """side: force a routing side — 'v' (vertical), 'h' (horizontal), or None (auto)."""
    return {"from": a, "to": b, "style": style, "label": label, "side": side}


# --------------------------------------------------------------------------
# 1. Component / layer map — dependency direction and the sealed core
# --------------------------------------------------------------------------
_CORE_W, _CORE_GAP = 16.4, 1.5
_core_x = [6 + i * (_CORE_W + _CORE_GAP) for i in range(5)]

COMPONENT_MAP = {
    "title": "Module map — dependency direction",
    "caption": ("Arrows point the way dependencies flow. Both front-ends converge on one "
                "seam, app/pipeline.py:538 run_pipeline(). Line counts are real."),
    "nodes": [
        # webui sits next to api on purpose: it talks only to the API, and an
        # adjacent pair keeps that edge from crossing the Streamlit box.
        N("streamlit", "app/main.py", 6, 5, 26, 10, SURFACE, "Streamlit shell · 1,356"),
        N("webui", "webui/", 37, 5, 26, 10, SURFACE, "React 18 + Vite + Tailwind · 2,764"),
        N("api", "api/", 68, 5, 26, 10, SURFACE, "FastAPI server 399 · serialize 240"),

        N("pipeline", "app/pipeline.py — run_pipeline()", 6, 21, 88, 8, SEAL,
          "the single orchestration seam · 631 lines"),

        N("domain", "domain/", _core_x[0], 33, _CORE_W, 17, CORE,
          "models 324\ncalendar_utils 113"),
        N("ingest", "ingest/", _core_x[1], 33, _CORE_W, 17, CORE,
          "timesheet 648\nsalary 451\nrse_list 223"),
        N("validate", "validate/", _core_x[2], 33, _CORE_W, 17, CORE,
          "completeness 856\ngates 455\ncrosschecks 338\nverdict 135"),
        N("calc", "calc/", _core_x[3], 33, _CORE_W, 17, CORE,
          "method_a 245\nmethod_b 269\nvariance 149"),
        N("output", "output/", _core_x[4], 33, _CORE_W, 17, CORE,
          "soe 307\nedb_writer 164\nreports 86"),

        # db/ and eval/ are placed to leave the ingest (32.1) and validate (50)
        # vertical lanes clear, so the dashed llm/ edges reach them without
        # crossing an unrelated box.
        N("db", "db/", 6, 57, 24, 10, DATA, "schema 379 · store 842\n16 tables · vec0 provisioned"),
        N("eval", "eval/", 56, 57, 38, 10, DATA, "harness 277 · groundedness 320 · questions 146"),

        N("llm", "llm/", 6, 76, 88, 13, LLM,
          "client 335 · qa 630 · extract 287 · reconcile 224 · "
          "designation 178 · cache 169 · advisories 123"),
    ],
    "edges": [
        E("webui", "api", label="/api"),
        E("api", "pipeline", side="v"),
        E("streamlit", "pipeline", side="v"),
        E("domain", "ingest"),
        E("ingest", "validate"),
        E("validate", "calc"),
        E("calc", "output"),
        E("validate", "db", side="v"),
        E("llm", "ingest", style="dashed", label="proposals only", side="v"),
        E("llm", "validate", style="dashed", side="v"),
    ],
    # the hard boundary, drawn as a labelled rule rather than an edge
    "barrier": {
        "y": 70,
        "label": "HARD BOUNDARY — nothing in calc/ or output/ may import llm/ "
                 "· enforced by 3 subprocess import tests, not by convention",
    },
}


# --------------------------------------------------------------------------
# 2. Data-flow pipeline — one upload to a submission pack
# --------------------------------------------------------------------------
DATA_FLOW = {
    "title": "Data flow — upload to submission pack",
    "caption": ("A parse failure never aborts the run: explain_ingest_error() classifies it "
                "and returns an HR-readable why+fix into PipelineResult.errors."),
    "nodes": [
        N("upload", "Upload", 2, 6, 15, 12, SURFACE,
          "xlsx · multipart\nor sample mode"),
        N("ingest", "Ingest ×3", 20, 6, 17, 12, CORE,
          "timesheet · rse_list\npayroll register"),
        N("complete", "Completeness", 40, 6, 17, 12, CORE,
          "19 DocTypes\nperson-month matrix"),
        N("gates", "Gates G1–G7", 60, 6, 17, 12, CORE,
          "+ 4 cross-checks\n(warnings only)"),
        N("verdict", "Verdict", 80, 6, 16, 12, CORE,
          "EXCLUDED >\nBLOCKED > QUALIFIES"),

        # the two engines are one flow stage; slides 11-14 open them up
        N("dual", "calc/ — both engines, every claim", 40, 34, 32, 15, CORE,
          "Method A · EDB pro-ration -> SUBMITTED\n"
          "Method B · internal hours ratio -> CROSS-CHECK ONLY"),
        N("var", "Variance", 76, 34, 20, 15, CORE,
          "Δ$ · Δ%\nNew-Hire B>A flag\n>1% material"),

        N("edb", "EDB template", 3, 70, 21, 13, OUT,
          "official RIS(C) v1.1\nformulas + hidden cols kept"),
        N("soe", "SOE", 26, 70, 21, 13, OUT,
          "6 sheets · evidence trail\nfor the Practitioner"),
        N("issues", "Issues to fix", 49, 70, 21, 13, OUT,
          "everyone not yet\nclaimable, with reasons"),
        N("persist", "SQLite", 72, 70, 21, 13, DATA,
          "persist_result()\nbest-effort, never fatal"),
    ],
    "edges": [
        E("upload", "ingest"),
        E("ingest", "complete"),
        E("complete", "gates"),
        E("gates", "verdict"),
        E("gates", "dual", side="v"),
        E("dual", "var"),
        E("dual", "edb", side="v"),
        E("dual", "soe", side="v"),
        E("verdict", "issues", side="v"),
        E("var", "persist", side="v"),
    ],
}


# --------------------------------------------------------------------------
# 3. LLM trust boundary — the LLM proposes, the engine disposes
# --------------------------------------------------------------------------
TRUST_BOUNDARY = {
    "title": "The LLM proposes, the deterministic engine disposes",
    "caption": ("The boundary is a test, not a docstring: three tests import calc/ and "
                "validate/ in a subprocess and assert no edb_claim.llm* module ever "
                "reaches sys.modules."),
    "nodes": [
        N("lgroup", "llm/ — PROPOSES", 2, 5, 30, 68, GROUP, None),
        N("extract", "extract.py", 4.5, 14, 25, 10, LLM,
          "FR-9 payslip fields\n+ confidence + location"),
        N("desig", "designation.py", 4.5, 27, 25, 10, LLM,
          "FR-10 G5 judging\nborderline only"),
        N("recon", "reconcile.py", 4.5, 40, 25, 10, LLM,
          "FR-11 name variants\nexact-ID auto-accepts"),
        N("qa", "qa.py", 4.5, 53, 25, 10, LLM,
          "FR-12 audit Q&A\nrouter + groundedness"),

        # spans all four llm/ box centres (19/32/45/58) so every dashed edge gets a
        # straight horizontal lane instead of a bus route that overlaps its neighbours
        N("mid", "ingest/ + validate/", 38, 16, 24, 44, CORE,
          "accepts ADVISORIES\n\n· mismatch flags\n· needs_review marks\n"
          "· HR confirmation queue\n\nnever a figure"),

        N("sgroup", "DETERMINISTIC — SEALED", 68, 5, 30, 68, GROUP, None),
        N("calc", "calc/", 70.5, 16, 25, 20, SEAL,
          "method_a · method_b · variance\n\nALL arithmetic happens here"),
        N("out", "output/", 70.5, 40, 25, 20, SEAL,
          "edb_writer · soe · reports\n\nALL figures written here"),
    ],
    "edges": [
        E("extract", "mid", style="dashed"),
        E("desig", "mid", style="dashed"),
        E("recon", "mid", style="dashed"),
        E("qa", "mid", style="dashed", label="reads only"),
        E("mid", "calc"),
        E("calc", "out", side="v"),
    ],
    "vbarrier": {
        "x": 65,
        "label_y": 69,
        "label": "NO IMPORT PATH",
    },
    "footnotes": [
        "temperature = 0.0",
        "response_format = json_schema, strict: True",
        "sha256(prompt, model, schema) cache-and-replay",
        "call() never raises into the pipeline",
        "cache-replay is the determinism guarantee — not temperature (GPU is not bit-exact)",
    ],
}


# --------------------------------------------------------------------------
# 4. Evidence & audit trail — what satisfies the 85% sample
# --------------------------------------------------------------------------
EVIDENCE_TRAIL = {
    "title": "Evidence trail — every figure back to its cell",
    "caption": ("SSRS 4400 agreed-upon procedures: the Practitioner samples at least 85% of "
                "claimed value. That requirement is why EvidenceRef is threaded from the "
                "parser rather than reconstructed at export."),
    "nodes": [
        N("cell", "Source cell", 2, 48, 15, 22, DATA,
          "Time Sheet!G19\npayroll!E7\n\nread once, at parse time"),
        N("ref", "EvidenceRef", 20, 48, 15, 22, CORE,
          "{file, sheet,\ncell_or_row, label}\n\ntravels with the value"),
        N("row", "evidence_ref", 38, 48, 15, 22, DATA,
          "312 live rows\nUNIQUE(employee_id,\nfigure_key)"),
        N("api", "/api/preview", 56, 48, 15, 22, SURFACE,
          "resolves via the\nsession file registry"),
        N("ui", "Evidence.tsx", 74, 48, 15, 22, SURFACE,
          "sheet grid,\nfocus cell highlighted\n\none click from any figure"),

        N("claim", "Claim row figure", 20, 10, 33, 18, OUT,
          "Manpower_Locals col H\nevery figure carries its ref"),
        N("auditor", "Practitioner (SSRS 4400)", 56, 10, 33, 18, OUT,
          "samples ≥ 85% of claimed value\nagainst the Statement of Expenditure"),
    ],
    "edges": [
        E("cell", "ref"),
        E("ref", "row"),
        E("row", "api"),
        E("api", "ui"),
        E("ref", "claim", side="v"),
        E("claim", "auditor"),
    ],
}


# --------------------------------------------------------------------------
# 5. HR journey — the five guided stages, as the user meets them
# --------------------------------------------------------------------------
# Deliberately not DATA_FLOW: that one is the engineering view of the same run.
# This is what HR sees on screen, so the branches are the two places a person
# can be stopped, not the modules that stop them.
_J_W, _J_GAP = 17.5, 1.5
_j_x = [2 + i * (_J_W + _J_GAP) for i in range(5)]

HR_JOURNEY = {
    "title": "How a claim flows — five guided stages",
    "caption": ("Every stage is reversible and nothing is silently dropped: the doc check "
                "blocks until the gap is fixed or explicitly acknowledged, and anyone "
                "excluded leaves with a reason and a source cell."),
    "nodes": [
        N("s1", "1 · Upload documents", _j_x[0], 6, _J_W, 20, SURFACE,
          "internal timesheet workbooks\nECMF RSE list · payroll register\nsupporting evidence ticked"),
        N("s2", "2 · Document check", _j_x[1], 6, _J_W, 20, CORE,
          "FR-2 completeness matrix\n19 doc types, scoped\nper person and per month"),
        N("s3", "3 · Eligibility", _j_x[2], 6, _J_W, 20, CORE,
          "gates G1–G7 + 4 cross-checks\nverdict per person:\nQUALIFIES / BLOCKED / EXCLUDED"),
        N("s4", "4 · Claim amount", _j_x[3], 6, _J_W, 20, CORE,
          "Method A — submitted\nMethod B — cross-check\nevery month shown in full"),
        N("s5", "5 · Submission pack", _j_x[4], 6, _J_W, 20, CORE,
          "one click, three workbooks\nevery figure carries its cell"),

        N("gate", "Fix or acknowledge", _j_x[1], 40, _J_W, 18, OUT,
          "Continue stays disabled until\nthe document is re-uploaded or\nthe gap is signed off"),
        N("excl", "Excluded / blocked", _j_x[2], 40, _J_W, 18, OUT,
          "reason + authority + source cell\nreported, never dropped"),
        N("var", "Variance A vs B", _j_x[3], 40, _J_W, 18, OUT,
          "Δ$ · Δ% · New-Hire isolation\nsurfaced before the auditor sees it"),
        N("pack", "EDB template · SOE · Issues", _j_x[4], 40, _J_W, 18, OUT,
          "official RIS(C) v1.1 export,\nthe Practitioner's evidence pack,\nHR's action list"),

        N("assist", "Grant & Verification Assistant — on every screen", 2, 72, 93.5, 14, NOTE,
          "figures answered by exact SQL over the computed rows  ·  scheme questions answered from the "
          "knowledge base  ·  \"fetch the evidence for <name>\" returns files and cells  ·  read-only, "
          "and every answer is groundedness-checked before it is shown"),
    ],
    "edges": [
        E("s1", "s2"),
        E("s2", "s3"),
        E("s3", "s4"),
        E("s4", "s5"),
        E("s2", "gate", style="dashed", side="v", label="if anything is missing"),
        E("s3", "excl", style="dashed", side="v"),
        E("s4", "var", side="v"),
        E("s5", "pack", side="v"),
    ],
}


# --------------------------------------------------------------------------
# 6. Deployment — one on-prem host, the model endpoint optional
# --------------------------------------------------------------------------
DEPLOYMENT = {
    "title": "Deployment — on-prem, offline-capable, one host",
    "caption": ("Shipped as scripts, not containers: run_web.sh builds webui/dist and serves "
                "it from the same uvicorn process as /api, so the SPA is same-origin and no "
                "claim data ever leaves the host. The db carries a vec0 table for future "
                "semantic retrieval; today retrieval is lexical (T23 open)."),
    "nodes": [
        N("zone", "ST ENGINEERING ON-PREM HOST  —  SALARY DATA NEVER LEAVES THE MACHINE",
          1, 0.5, 98, 77, GROUP),

        N("browser", "HR browser", 3, 8, 19, 15, SURFACE,
          "React 18 SPA\nsame origin, relative /api"),
        N("api", "uvicorn + FastAPI  ·  127.0.0.1:8010", 26, 8, 28, 15, SURFACE,
          "run_web.sh — serves webui/dist at /\nNDJSON progress stream on /api/analyze"),
        N("pipeline", "run_pipeline()", 58, 8, 22, 15, SEAL,
          "the deterministic core\nno network calls, ever"),

        N("db", "edb_claim.db", 3, 32, 26, 17, DATA,
          "one SQLite file · 16 tables\n312 evidence refs · 238 gate results\nEDB_DB_PATH"),
        N("files", "xlsx artifacts", 58, 32, 22, 17, OUT,
          "EDB template · SOE\nIssues to fix\nwritten to disk, never uploaded"),

        N("vllm", "vLLM  ·  OpenAI-compatible  ·  :8000", 26, 58, 34, 17, LLM,
          "Qwen 3.6 35B A3B on the NVIDIA DGX\nEDB_LLM_BASE_URL · EDB_LLM_MODEL\n"
          "36 responses cached from this endpoint"),
        N("offline", "Offline is a supported mode", 64, 58, 32, 17, NOTE,
          "unset EDB_LLM_BASE_URL and the pipeline\nis unchanged — every figure is Python.\n"
          "The assistant still answers from stored rows"),

        N("proposed", "PROPOSED — not shipped in the POC", 3, 85, 93, 9, NOTE,
          "systemd unit or container image for restart-on-boot  ·  nightly copy of the single .db file  ·  "
          "reverse proxy + SSO if the app is ever opened beyond localhost"),
    ],
    "edges": [
        E("browser", "api", label="/api"),
        E("api", "pipeline"),
        E("pipeline", "files", side="v"),
        E("pipeline", "db", side="v"),
        E("api", "vllm", style="dashed", side="v", label="optional  ·  temperature 0"),
    ],
    "barrier": {
        "y": 78.8,
        "label": "EVERYTHING ABOVE IS SHIPPED AND RUNNING — everything below is hardening we "
                 "would add for a production pilot",
    },
}


ALL = {
    "component_map": COMPONENT_MAP,
    "data_flow": DATA_FLOW,
    "trust_boundary": TRUST_BOUNDARY,
    "evidence_trail": EVIDENCE_TRAIL,
    "hr_journey": HR_JOURNEY,
    "deployment": DEPLOYMENT,
}


# --------------------------------------------------------------------------
# shared edge-geometry solver — the single source both renderers consume
# --------------------------------------------------------------------------
def node_index(diagram):
    return {n["id"]: n for n in diagram["nodes"]}


def _sides(n):
    return {
        "cx": n["x"] + n["w"] / 2.0,
        "cy": n["y"] + n["h"] / 2.0,
        "l": n["x"], "r": n["x"] + n["w"],
        "t": n["y"], "b": n["y"] + n["h"],
    }


def edge_points(diagram, edge):
    """Return an orthogonal polyline [(x, y), ...] of 2 or 4 points for one edge.

    Three cases, in order of preference:

      1. The two nodes share a lane (one spans the other's centre on the cross
         axis) -> one straight segment down that shared line.
      2. Otherwise -> a 4-point "bus" route: leave the source's near face, run
         to a midline, traverse, then enter the TARGET'S NEAR FACE.

    Case 2 replaces the obvious single elbow on purpose. An elbow has to arrive
    on a node's left/right face, which means a misaligned edge crosses whatever
    sits between the two nodes and lands on the far side — so the arrowhead
    points back the way it came and the diagram reads backwards. Entering the
    near face always reads forwards. Never a curve: MSO connectors cannot
    reproduce one, and the pptx and SVG backends must draw identical paths.
    """
    idx = node_index(diagram)
    a, b = _sides(idx[edge["from"]]), _sides(idx[edge["to"]])
    dx = b["cx"] - a["cx"]
    dy = b["cy"] - a["cy"]

    forced = edge.get("side")
    horizontal = abs(dx) >= abs(dy) if forced is None else forced == "h"

    def spans(outer, inner_c, axis):
        lo, hi = (outer["l"], outer["r"]) if axis == "x" else (outer["t"], outer["b"])
        return lo <= inner_c <= hi

    if not horizontal:
        down = dy > 0
        # a shared vertical lane?
        lane = None
        if spans(b, a["cx"], "x"):
            lane = a["cx"]
        elif spans(a, b["cx"], "x"):
            lane = b["cx"]
        if lane is not None:
            return _gap([(lane, a["b"]), (lane, b["t"])] if down
                        else [(lane, a["t"]), (lane, b["b"])])
        y0 = a["b"] if down else a["t"]
        y3 = b["t"] if down else b["b"]
        mid = (y0 + y3) / 2.0
        return _gap([(a["cx"], y0), (a["cx"], mid), (b["cx"], mid), (b["cx"], y3)])

    right = dx > 0
    lane = None
    if spans(b, a["cy"], "y"):
        lane = a["cy"]
    elif spans(a, b["cy"], "y"):
        lane = b["cy"]
    if lane is not None:
        return _gap([(a["r"], lane), (b["l"], lane)] if right
                    else [(a["l"], lane), (b["r"], lane)])
    x0 = a["r"] if right else a["l"]
    x3 = b["l"] if right else b["r"]
    mid = (x0 + x3) / 2.0
    return _gap([(x0, a["cy"]), (mid, a["cy"]), (mid, b["cy"]), (x3, b["cy"])])


# small standoff so an arrowhead never sits on a node's border text
GAP = 1.4


def _gap(pts):
    """Pull both endpoints back from the node faces along their own segment.

    Skipped on short segments: neighbouring boxes sit only ~1.5 units apart, and
    trimming 0.9 off each end would invert the segment and flip the arrowhead.
    """
    pts = [list(p) for p in pts]
    for idx, other in ((0, 1), (-1, -2)):
        ax = 0 if abs(pts[other][0] - pts[idx][0]) > abs(pts[other][1] - pts[idx][1]) else 1
        span = pts[other][ax] - pts[idx][ax]
        if abs(span) > 2.4 * GAP:
            pts[idx][ax] += GAP * (1 if span > 0 else -1)
    return [tuple(p) for p in pts]
