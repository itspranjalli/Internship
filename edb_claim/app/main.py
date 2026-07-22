"""EDB RIS(C) grant-claim preparation — official-style guided web app (FR-8, T20).

Designed from the HR user's point of view as a clean, progressive workflow that
unwinds the deterministic backend one stage at a time:

    Documents  →  Document check (FR-2)  →  Eligibility (FR-6)
              →  Claim amounts (FR-4)     →  Submission pack (FR-5/SOE/FR-7)

Each stage is a single focused screen with Back / Continue navigation, so the
system reveals itself step by step instead of all at once. The app computes
nothing — every figure comes from ``app.pipeline``. It runs fully offline; salary
data never leaves the machine.

Run:  .venv/bin/streamlit run edb_claim/app/main.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime
from typing import Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd
import streamlit as st

from edb_claim.config import settings
from edb_claim.app.pipeline import EmployeeResult, PipelineResult, SupportingDocs, run_pipeline
from edb_claim.app.preview import excel_sheet_to_grid, parse_cell_ref, resolve_evidence_path
from edb_claim.output.edb_writer import fill_edb_template
from edb_claim.output.soe import build_soe
from edb_claim.output.reports import build_exclusions_report

_SAMPLE_DIR = os.path.join(_REPO_ROOT, "sample_data")
_SAMPLE_INTERNAL = [
    os.path.join(_SAMPLE_DIR, "internal_ANS.xlsx"),
    os.path.join(_SAMPLE_DIR, "internal_DSG.xlsx"),
]
_SAMPLE_RSE = os.path.join(_SAMPLE_DIR, "rse_list.xlsx")
_SAMPLE_PAYROLL = os.path.join(_SAMPLE_DIR, "payroll.xlsx")

_STEPS = ["Documents", "Document check", "Eligibility", "Claim amount", "Submission pack"]

_CHECK_NAMES = {
    "G1": "Singapore Citizen or PR",
    "G2": "ECMF-validated researcher",
    "G3": "Not funded by another government grant",
    "G4": "Meets the minimum salary ($5,000/month)",
    "G5": "Eligible R&D role (not Marketing / HR / Sales / etc.)",
    "G6": "Active during the claim period",
    "G7": "Payslip provided for each month",
}
_STATUS = {
    "QUALIFIES": ("Qualifies", "#1a7f37", "#e9f5ec"),
    "EXCLUDED": ("Not eligible", "#b42318", "#fdeceb"),
    "BLOCKED": ("Needs a document", "#b54708", "#fdf4e7"),
}

_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# styling — a clean, corporate shell
# ---------------------------------------------------------------------------
def _inject_css() -> None:
    st.markdown(
        """
        <style>
          #MainMenu, footer {visibility: hidden;}
          header[data-testid="stHeader"] {background: transparent;}
          .block-container {padding-top: 1.2rem; max-width: 1080px;}

          .gov-header {
            background: linear-gradient(90deg,#13355e 0%,#1F4E79 60%,#2E75B6 100%);
            color: #fff; border-radius: 10px; padding: 18px 24px; margin-bottom: 8px;
            display: flex; justify-content: space-between; align-items: center;
          }
          .gov-header .title {font-size: 1.35rem; font-weight: 700; letter-spacing:.2px;}
          .gov-header .sub {font-size: .82rem; opacity:.85; margin-top:2px;}
          .gov-header .ref {font-size:.78rem; opacity:.9; text-align:right; line-height:1.5;}

          .stepper {display:flex; gap:6px; margin:18px 0 10px;}
          .stepper .seg {flex:1; text-align:center; font-size:.74rem; color:#8a929e;
            padding:8px 4px 10px; border-top:3px solid #e3e8ef;}
          .stepper .seg.done {color:#1F4E79; border-top-color:#2E75B6;}
          .stepper .seg.active {color:#13355e; font-weight:700; border-top-color:#13355e;}
          .stepper .seg .n {display:inline-block; width:20px; height:20px; line-height:20px;
            border-radius:50%; background:#e3e8ef; color:#5a6472; font-size:.72rem; margin-right:4px;}
          .stepper .seg.done .n {background:#2E75B6; color:#fff;}
          .stepper .seg.active .n {background:#13355e; color:#fff;}

          .pill {display:inline-block; padding:2px 12px; border-radius:14px;
            font-size:.78rem; font-weight:600;}
          .hero h2 {color:#13355e; margin-bottom:.2rem;}
          .muted {color:#5a6472;}
          div[data-testid="stExpander"] {border-radius:8px;}
          .stButton button {border-radius:7px;}

          /* progress bar label */
          .progress-label {font-size:.8rem; color:#5a6472; margin:2px 0 -6px;}

          /* floating chat button (FAB), fixed bottom-right */
          .st-key-chat_fab {position: fixed; bottom: 22px; right: 24px; z-index: 1002;}
          .st-key-chat_fab button {
            border-radius: 50% !important; width: 58px; height: 58px;
            font-size: 1.45rem; line-height: 1; padding: 0 !important;
            background: #1F4E79 !important; color: #fff !important; border: none !important;
            box-shadow: 0 6px 18px rgba(19,53,94,.35);
          }
          .st-key-chat_fab button:hover {background:#13355e !important;}

          /* floating chat panel, docked bottom-right above the FAB */
          .st-key-chat_panel {
            position: fixed; bottom: 92px; right: 24px; width: 390px; max-width: 92vw;
            max-height: 74vh; overflow: auto; z-index: 1001;
            background: #fff; border: 1px solid #d7dee8; border-radius: 14px;
            box-shadow: 0 14px 36px rgba(19,53,94,.22); padding: 6px 14px 12px;
          }
          .st-key-chat_panel [data-testid="stChatMessage"] {padding:.25rem .25rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _header() -> None:
    final = "Confirmed" if settings.support_rate_is_final else "Assumed " + f"{settings.support_rate:.0%} rate"
    st.markdown(
        f"""
        <div class="gov-header">
          <div>
            <div class="title">RIS(C) Claim Preparation &amp; Verification Portal</div>
            <div class="sub">Economic Development Board · Research Incentive Scheme for Companies (RIS(C))</div>
          </div>
          <div class="ref">Application No. S26-10249-RIS(C)<br>
            Claim period {settings.claim_period_start:%d %b %Y} – {settings.claim_period_end:%d %b %Y}<br>
            <span style="opacity:.8">Support rate: {final}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _stepper(active: int) -> None:
    segs = ""
    for i, name in enumerate(_STEPS):
        cls = "done" if i < active else ("active" if i == active else "")
        mark = "✓" if i < active else str(i + 1)
        segs += f"<div class='seg {cls}'><span class='n'>{mark}</span>{name}</div>"
    st.markdown(f"<div class='stepper'>{segs}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _money(x: Optional[float]) -> str:
    return "—" if x is None else f"${x:,.2f}"


def _persist(uploaded, suffix=".xlsx") -> Optional[str]:
    if uploaded is None:
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="edb_")
    tmp.write(uploaded.getbuffer())
    tmp.flush()
    tmp.close()
    # Register so the evidence preview can map a citation's filename back to this
    # real path (uploads land under temp names; citations keep the original name).
    reg = st.session_state.setdefault("file_registry", {})
    reg[os.path.basename(tmp.name)] = tmp.name
    name = getattr(uploaded, "name", None)
    if name:
        reg[name] = tmp.name
        reg[os.path.basename(name)] = tmp.name
    return tmp.name


def _entity_slug(entity: str) -> str:
    name = entity.replace("ST Engineering", "").replace("Pte Ltd", "").replace("Ltd", "")
    words = "".join(c if c.isalnum() else " " for c in name).split()
    return ("_".join(words) or "Entity")[:32]


def _crosscheck_note(e: EmployeeResult) -> str:
    if e.method_b is None:
        return "No internal cross-check available."
    if e.crosscheck_ok:
        return "Internal cross-check agrees with the EDB figure."
    if e.method_b.new_hire and e.method_b.claim_amount > e.method_a.claim_amount:
        return ("New Hire with no recorded project hours: EDB's method gives $0, the "
                "internal method assumes 100% time — confirm the hours before claiming.")
    return ("The EDB figure and the internal hours-based figure differ noticeably — "
            "usually the recorded hours don't match the involvement period.")


def _go(step: int) -> None:
    st.session_state["step"] = max(0, min(step, len(_STEPS) - 1))
    st.rerun()


def _counts(res: PipelineResult):
    e = res.all_employees
    return (
        [x for x in e if x.verdict.status.value == "QUALIFIES"],
        [x for x in e if x.verdict.status.value == "BLOCKED"],
        [x for x in e if x.verdict.status.value == "EXCLUDED"],
        [x for x in e if x.needs_review],
    )


# ---------------------------------------------------------------------------
# document pack (generated lazily, cached per run)
# ---------------------------------------------------------------------------
def _build_pack(res: PipelineResult) -> Dict[str, bytes]:
    ts = datetime.now()
    out: Dict[str, bytes] = {}
    workdir = tempfile.mkdtemp(prefix="edb_pack_")
    soe = build_soe(res, os.path.join(workdir, "Statement_of_Expenditure.xlsx"), timestamp=ts)
    out["Statement_of_Expenditure.xlsx"] = open(soe, "rb").read()
    iss = build_exclusions_report(res, os.path.join(workdir, "Issues_to_fix.xlsx"), timestamp=ts)
    out["Issues_to_fix.xlsx"] = open(iss, "rb").read()
    template = os.path.join(_REPO_ROOT, "docs", "EDB_Output Template.xlsx")
    if os.path.exists(template):
        for ent in res.entities:
            if not any(e.qualifies for e in ent.employees):
                continue
            fname = f"EDB_Submission_{_entity_slug(ent.entity)}.xlsx"
            p = fill_edb_template(ent, os.path.join(workdir, fname), template_path=template, timestamp=ts)
            out[fname] = open(p, "rb").read()
    return out


def _pack(res: PipelineResult) -> Dict[str, bytes]:
    if "pack" not in st.session_state:
        with st.spinner("Preparing your documents…"):
            st.session_state["pack"] = _build_pack(res)
    return st.session_state["pack"]


# ---------------------------------------------------------------------------
# supporting evidence checklist (the wider HR document set; FR-2)
# ---------------------------------------------------------------------------
def _supporting_evidence_section(*, sample: bool) -> SupportingDocs:
    """Presence checklist for the wider HR evidence set (presence-checked only).

    The three core inputs above drive the calculation; these are the remaining
    documents an HR officer assembles per UEN (PRD §4/FR-2). Ticked = attached.
    Everything here is flagged-but-not-blocking (presence-checked only). Defaults to attached so the
    baseline isn't a wall of warnings — untick whatever you don't yet have.
    """
    st.markdown("##### 2b · Supporting evidence")
    st.caption("Presence-checked only (not parsed). Tick what you're attaching for this "
               "submission; untick anything still outstanding. All are flagged for audit if "
               "missing but none block the claim.")
    # entity-once (per UEN) | per-person (whole roster)
    ent = (
        ("RISC submission form (per company)", "sd_risc"),
        ("EDB Letter of Award / offer letter", "sd_loa"),
        ("Skill validation list", "sd_skill"),
        ("List of trainees (emp. no + training dates)", "sd_trainee"),
        ("Supporting AI artifacts (codebase / app)", "sd_artifacts"),
        ("Leave report", "sd_leave"),
    )
    per = (
        ("CPF & bank statements (proof of payment)", "sd_cpf"),
        ("Formal PL3 status confirmation", "sd_pl3"),
        ("Training certification (CLT / external)", "sd_cert"),
        ("Signed monthly progress reports", "sd_progress"),
        ("Daily clocking records (actual days)", "sd_clocking"),
    )
    suffix = "_s" if sample else "_u"  # unique widget keys per source mode
    vals: Dict[str, bool] = {}
    with st.expander("Supporting evidence checklist", expanded=False):
        ca, cb = st.columns(2)
        with ca:
            st.markdown("**Per company**")
            for label, key in ent:
                vals[key] = st.checkbox(label, value=True, key=key + suffix)
        with cb:
            st.markdown("**Per person**")
            for label, key in per:
                vals[key] = st.checkbox(label, value=True, key=key + suffix)

    def v(key: str) -> bool:
        return bool(vals.get(key))

    return SupportingDocs(
        risc_submission_form=v("sd_risc"),
        letter_of_award=v("sd_loa"),
        skill_validation_list=v("sd_skill"),
        trainee_list=v("sd_trainee"),
        ai_artifacts=v("sd_artifacts"),
        leave_report=v("sd_leave"),
        cpf_bank=v("sd_cpf"),
        pl3_confirmation=v("sd_pl3"),
        training_certification=v("sd_cert"),
        monthly_progress_report=v("sd_progress"),
        daily_clocking=v("sd_clocking"),
    )


# ---------------------------------------------------------------------------
# STEP 0 — landing + documents
# ---------------------------------------------------------------------------
def _step_documents() -> None:
    st.markdown(
        "<div class='hero'><h2>Prepare, review and verify a RIS(C) manpower claim</h2>"
        "<p class='muted'>This portal takes the supporting HR records, applies EDB's "
        "eligibility rules, calculates each person's claim, and produces the submission "
        "template, the auditor's Statement of Expenditure, and a full evidence trail. "
        "Every figure is traceable to its source document — open the assistant on the "
        "right to query the claim or fetch supporting documents for verification.</p></div>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown("##### 1 · Add your documents")
        mode = st.radio("Document source", ["Use sample data", "Upload my files"],
                        horizontal=True, label_visibility="collapsed")

        internal_paths: List[str] = []
        rse_path = payroll_path = None
        docs: List[dict] = []  # {label, path, name} for the document viewer
        if mode == "Use sample data":
            if any(not os.path.exists(p) for p in _SAMPLE_INTERNAL + [_SAMPLE_RSE, _SAMPLE_PAYROLL]):
                st.error("Sample data missing. Run `python sample_data/generate.py`.")
                return
            internal_paths = list(_SAMPLE_INTERNAL)
            rse_path, payroll_path = _SAMPLE_RSE, _SAMPLE_PAYROLL
            reg = st.session_state.setdefault("file_registry", {})
            for p in internal_paths + [rse_path, payroll_path]:
                reg[os.path.basename(p)] = p  # citations cite the basename
            docs = ([{"label": "Team timesheet", "path": p, "name": os.path.basename(p)} for p in internal_paths]
                    + [{"label": "ECMF researcher list", "path": rse_path, "name": os.path.basename(rse_path)},
                       {"label": "Payroll / payslips", "path": payroll_path, "name": os.path.basename(payroll_path)}])
            st.caption("Loaded a worked example: 2 companies · 20 staff covering the full range of cases.")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                ups = st.file_uploader("Team timesheet workbook(s)", type=["xlsx"],
                                       accept_multiple_files=True)
            with c2:
                rse_up = st.file_uploader("ECMF researcher list", type=["xlsx"])
            with c3:
                pay_up = st.file_uploader("Payroll / payslips", type=["xlsx"])
            for u in (ups or []):
                p = _persist(u)
                if p:
                    internal_paths.append(p)
                    docs.append({"label": "Team timesheet", "path": p, "name": u.name})
            rse_path = _persist(rse_up)
            if rse_path:
                docs.append({"label": "ECMF researcher list", "path": rse_path, "name": rse_up.name})
            payroll_path = _persist(pay_up)
            if payroll_path:
                docs.append({"label": "Payroll / payslips", "path": payroll_path, "name": pay_up.name})

        # 2 · view what was added (preview in original form before analysing)
        if docs:
            st.markdown("##### 2 · Review your documents")
            st.caption("Open any file to check it's the right one before analysing.")
            for i, d in enumerate(docs):
                cap, btn = st.columns([6, 1], vertical_alignment="center")
                with cap:
                    st.markdown(f"📄 **{d['label']}** — <span class='muted'>{d['name']}</span>",
                                unsafe_allow_html=True)
                with btn:
                    if st.button("👁 View", key=f"viewdoc_{i}"):
                        _preview_dialog({"file": d["path"], "sheet": None,
                                         "cell": None, "label": d["label"]})

        # 2b · supporting evidence (presence-checked — the wider HR checklist)
        supporting = _supporting_evidence_section(sample=mode == "Use sample data")

        st.write("")
        st.markdown("##### 3 · Analyse")
        if st.button("Analyse documents  →", type="primary"):
            if not internal_paths:
                st.warning("Add at least one timesheet workbook to continue.")
            else:
                bar = st.progress(0, text="Starting…")
                with st.status("Processing your claim…", expanded=True) as status:
                    st.write("Reading documents…")
                    bar.progress(20, text="Reading documents…")
                    res = run_pipeline(internal_paths, rse_path, payroll_path,
                                       supporting=supporting)
                    st.write("Checking document completeness…")
                    bar.progress(50, text="Checking document completeness…")
                    time.sleep(0.1)
                    st.write("Running eligibility checks…")
                    bar.progress(70, text="Running eligibility checks…")
                    time.sleep(0.1)
                    st.write("Calculating claim amounts…")
                    bar.progress(90, text="Calculating claim amounts…")
                    _persist_to_store(res, docs)  # FR-13: write-through + store the source files
                    bar.progress(100, text="Analysis complete")
                    status.update(label="Analysis complete", state="complete", expanded=False)
                st.session_state["result"] = res
                st.session_state["rse_path"] = rse_path
                st.session_state["payroll_path"] = payroll_path
                st.session_state["uploaded_docs"] = docs
                st.session_state.pop("pack", None)
                st.session_state.pop("ack_blockers", None)
                st.session_state.pop("advisories", None)
                st.session_state.pop("assistant", None)  # rebind with the freshly populated store
                _go(1)

    with st.expander("What documents do I need?"):
        st.markdown(
            "**Three core documents drive the calculation:**\n"
            "- **Team timesheet workbook** — the internal AI COE timesheet (hours, roles, dates), one file per company.\n"
            "- **ECMF researcher list** — confirms who is an ECMF-validated local researcher.\n"
            "- **Payroll / payslips** — the basic monthly salary for each person.\n\n"
            "**Supporting evidence (presence-checked, section 2b)** — the wider set an HR officer "
            "assembles per company: completed RISC submission form, EDB Letter of Award, skill "
            "validation list, list of trainees, supporting AI artifacts, leave report, CPF/bank "
            "statements (proof of payment), PL3 confirmation, training certificates, signed monthly "
            "progress reports, and daily clocking records. These are checked for presence only — not "
            "parsed — and none of them block the claim (all are flagged for audit only).\n\n"
            "Everything is processed on this machine; no claim or salary data is sent anywhere."
        )


# ---------------------------------------------------------------------------
# STEP 1 — document check (FR-2)
# ---------------------------------------------------------------------------
def _step_doccheck(res: PipelineResult) -> bool:
    """Render the document-check stage. Returns True if the user may continue."""
    st.markdown("#### Document check")
    st.markdown("<p class='muted'>Before anything is calculated, we confirm the required documents "
                "are present for each company and person. Missing documents must be resolved or "
                "explicitly acknowledged before the claim can proceed.</p>", unsafe_allow_html=True)

    total_blockers = sum(ent.completeness.rollup.blocker_count for ent in res.entities)
    blocked_people = [e for e in res.all_employees if e.verdict.status.value == "BLOCKED"]

    if total_blockers == 0:
        st.success("All required documents are present. Nothing is blocking the claim.")
    else:
        st.error(
            f"**{total_blockers} document(s) are missing**, affecting "
            f"**{len(blocked_people)}** {'person' if len(blocked_people)==1 else 'people'}. "
            "The claim cannot proceed until these are resolved.",
            icon="⛔",
        )
        st.markdown("**Recommended:** upload the missing documents, then re-run the analysis.")
        st.button("←  Back to documents to upload the missing files", key="back_to_docs",
                  on_click=_reset)
        st.markdown("**Or**, proceed now and **exclude** the affected people from this claim "
                    "(they can be claimed in a later submission once documents are available):")
        st.checkbox(
            f"I acknowledge the {total_blockers} missing document(s) and want to continue "
            f"with the complete records only ({len(blocked_people)} person(s) will be excluded).",
            key="ack_blockers",
        )

    for ent in res.entities:
        rb = ent.completeness.rollup
        with st.container(border=True):
            st.markdown(f"**{ent.entity}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Staff", rb.employee_count)
            c2.metric("Documents complete", rb.ready_count)
            c3.metric("Waiting on a document", rb.blocked_count)
            blockers = ent.completeness.blocker_cells
            if blockers:
                st.dataframe(pd.DataFrame([{
                    "Employee": c.employee_id or "—",
                    "Missing": c.doc_type.value.replace("_", " "),
                    "Month": str(c.month) if c.month else "—",
                    "Detail": c.reason,
                } for c in blockers]), hide_index=True, width="stretch")
            warnings = ent.completeness.warning_cells
            if warnings:
                with st.expander(f"⚠ {len(warnings)} supporting item(s) flagged for audit "
                                 "(non-blocking)"):
                    st.caption("Presence-checked evidence and consistency notes. These don't "
                               "stop the claim, but the auditor expects them on file.")
                    st.dataframe(pd.DataFrame([{
                        "Scope": c.employee_id or "company",
                        "Document / check": c.doc_type.value.replace("_", " "),
                        "Month": str(c.month) if c.month else "—",
                        "Detail": c.reason,
                    } for c in warnings]), hide_index=True, width="stretch")
    if res.errors:
        st.error("Some files could not be read:\n\n" + "\n".join(f"- {e}" for e in res.errors))

    return total_blockers == 0 or bool(st.session_state.get("ack_blockers"))


# ---------------------------------------------------------------------------
# STEP 2 — eligibility (FR-6)
# ---------------------------------------------------------------------------
def _step_eligibility(res: PipelineResult) -> None:
    q, blocked, excluded, review = _counts(res)
    st.markdown("#### Eligibility")
    st.markdown("<p class='muted'>Every person is checked against EDB's eligibility criteria. "
                "Nobody is silently dropped — those not claimed are shown with the reason.</p>",
                unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Qualify", len(q))
    c2.metric("Needs a document", len(blocked))
    c3.metric("Not eligible", len(excluded))
    c4.metric("Needs review", len(review))

    adv = _advisories()
    if adv.enabled:
        st.caption("🟢 Local model assisting — borderline roles judged and identities "
                   "reconciled across documents below. Every suggestion is yours to accept "
                   "or override; no figure is changed by the model.")
        _render_reconciliation_queue(adv)
    else:
        st.caption("⚪ Local model offline — showing the automated checks only. "
                   "Connect the model for borderline-role judgements and name-variant matching.")

    flt = st.radio("Show", ["Everyone", "Qualifying", "Not claimed", "Needs review"],
                   horizontal=True)
    for e in res.all_employees:
        s = e.verdict.status.value
        if flt == "Qualifying" and s != "QUALIFIES":
            continue
        if flt == "Not claimed" and s == "QUALIFIES":
            continue
        if flt == "Needs review" and not e.needs_review:
            continue
        label_txt, color, bg = _STATUS.get(s, ("", "#555", "#eee"))
        pill = f"<span class='pill' style='background:{bg};color:{color}'>{label_txt}</span>"
        review_tag = " · review" if e.needs_review else ""
        with st.expander(f"{e.employee.name}  ·  {e.employee.designation}"):
            st.markdown(pill + f"&nbsp;&nbsp;<span class='muted'>{e.employee.id}{review_tag}</span>",
                        unsafe_allow_html=True)
            if e.needs_review:
                st.warning("This role is borderline — please confirm it is an eligible R&D role.")
                if adv.enabled:
                    _render_designation_advisory(e.employee.id, adv)
            rows = []
            for code in ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]:
                evs = [ev for ev in e.gate_evaluations if ev.gate.value == code]
                if not evs:
                    continue
                passed = all(ev.passed for ev in evs)
                fail = next((ev for ev in evs if not ev.passed), None)
                rows.append({
                    "Check": _CHECK_NAMES[code],
                    "Result": "OK" if passed else "Not met",
                    "Detail": (fail.reason if fail and fail.reason else "") if not passed else "",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            if s != "QUALIFIES":
                st.markdown(f"**Why not claimed:** {'; '.join(e.verdict.reasons)}")


# ---------------------------------------------------------------------------
# STEP 3 — claim amount (FR-4)
# ---------------------------------------------------------------------------
def _render_advanced_calc(res: PipelineResult, qualifying) -> None:
    """Advanced view — expose the full month-by-month workings so the claim is
    never a black box: every figure that feeds Method A (and the Method B
    cross-check) is shown with the exact formula and inputs."""
    with st.container(border=True):
        st.markdown("##### 🔬 Advanced — the full workings")
        st.markdown(
            "<p class='muted'>Each qualifying person's claim, month by month. "
            "Method A (submitted): <code>capped salary × month fraction × time on project</code>, "
            "summed, then × the support rate. Nothing is rounded until the final EDB column.</p>",
            unsafe_allow_html=True,
        )
        for e in qualifying:
            a = e.method_a
            with st.expander(f"{e.employee.name} · {e.employee.id} — {_money(a.claim_amount)}"):
                rows = [{
                    "Month": f"{m.year}-{m.month:02d}",
                    "Capped salary": _money(m.capped_salary),
                    "Month fraction": f"{m.month_fraction:.4f}",
                    "Time on project": f"{m.time_contribution:.4f}",
                    "Qualifying cost": _money(m.qualifying_cost),
                } for m in a.monthly]
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                st.markdown(
                    f"**Qualifying cost (sum):** {_money(a.qualifying_cost_total)} "
                    f"&nbsp;×&nbsp; support rate **{a.support_rate:.0%}** "
                    f"&nbsp;=&nbsp; **{_money(a.claim_amount)}**"
                )
                if e.method_b is not None:
                    b = e.method_b
                    note = "agrees" if e.crosscheck_ok else "differs — verify"
                    st.caption(f"Internal cross-check (Method B): {_money(b.claim_amount)} "
                               f"({note}). Method B is never submitted.")


def _step_claim(res: PipelineResult) -> None:
    q, _, _, _ = _counts(res)
    st.markdown("#### Claim amount")
    st.markdown(f"<p class='muted'>Calculated for the {len(q)} qualifying staff using EDB's "
                "monthly pro-ration. You don't enter any numbers — the workings are shown for each "
                "person and exported for the auditor.</p>", unsafe_allow_html=True)

    if not res.support_rate_is_final:
        st.info(f"Figures use an assumed {res.support_rate:.0%} support rate (EDB confirms the exact "
                "rate in the Letter of Award), so they are marked non-final.", icon="ℹ️")

    st.metric("Total claim", _money(res.total_claim_a))
    st.dataframe(pd.DataFrame([{
        "Employee": e.employee.id,
        "Name": e.employee.name,
        "Monthly salary": _money(e.monthly_basic_salary),
        "Claim amount": _money(e.method_a.claim_amount),
        "Cross-check": "OK" if e.crosscheck_ok else "Review",
    } for e in q]), hide_index=True, width="stretch")

    if st.session_state.get("advanced"):
        _render_advanced_calc(res, q)

    with st.expander("How is the claim calculated?"):
        st.markdown(
            "For each month a person works on the project:\n\n"
            "> capped monthly salary  ×  portion of the month involved  ×  portion of full-time on the project\n\n"
            f"Summed across the claim period and multiplied by the **{res.support_rate:.0%}** support rate. "
            f"Salary is capped at {_money(settings.salary_cap)}/month."
        )

    with st.expander("Why is there a second 'internal' figure? (cross-check)"):
        st.markdown(
            "**Method A** (above) is EDB's official method — the number we submit. "
            "**Method B** is your team's existing internal hours-ratio calculation, run quietly as a "
            "**second opinion**. When the two disagree a lot it usually points to a data problem "
            "(e.g. a New Hire with no timesheet), so you can fix it before the auditor sees it. "
            "EDB hasn't ruled which method applies to every edge case, so both are kept and differences "
            "are flagged — never hidden. **You only ever submit Method A.**"
        )
        v = res.variance
        if v.rows:
            name = {e.employee.id: e.employee.name for e in res.all_employees}
            st.dataframe(pd.DataFrame([{
                "Name": name.get(r.employee_id, r.employee_id),
                "EDB method (A)": _money(r.amount_a),
                "Internal method (B)": _money(r.amount_b),
                "Difference": _money(r.delta_abs),
                "Status": ("Verify (New Hire)" if r.new_hire_flag
                           else "Differs" if r.material else "Consistent"),
            } for r in v.rows]), hide_index=True, width="stretch")

    _render_extraction_crosscheck()


def _render_extraction_crosscheck() -> None:
    """On-demand FR-9 payslip extraction vs the deterministic basic salary."""
    if not settings.llm_enabled:
        return
    with st.expander("🤖 AI payslip cross-check (read the salaries straight from the payslips)"):
        st.markdown("<p class='muted'>The local model reads each payslip independently and we "
                    "compare its basic-salary reading against the figure the pipeline used. "
                    "Agreement is audit assurance; a mismatch is flagged for you to check. "
                    "The pipeline's figure is always the one claimed — the model never changes it.</p>",
                    unsafe_allow_html=True)
        if st.button("Run payslip cross-check"):
            with st.spinner("Reading payslips with the local model…"):
                st.session_state.pop("advisories_x", None)
                adv = _advisories(run_extraction=True)
            checks = adv.extraction_checks
            if not checks:
                st.info("No payslip rows could be cross-checked.")
                return
            mism = adv.extraction_mismatches
            (st.success if not mism else st.warning)(
                f"{len(checks)} payslip(s) read · "
                f"{len(checks) - len(mism)} agree, {len(mism)} to review.")
            st.dataframe(pd.DataFrame([{
                "Employee": c.employee_id,
                "Month": c.month,
                "Pipeline basic": _money(c.deterministic_basic),
                "Model read": _money(c.extracted_basic) if c.extracted_basic is not None else "—",
                "Result": "Agrees" if c.agrees else "Review",
                "Confidence": f"{c.confidence*100:.0f}%" if c.confidence is not None else "—",
            } for c in checks]), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# STEP 4 — submission pack (FR-5 / SOE / FR-7)
# ---------------------------------------------------------------------------
def _step_pack(res: PipelineResult) -> None:
    st.markdown("#### Submission pack")
    st.markdown("<p class='muted'>Three documents, each for a different reader — generated from the "
                "figures you just reviewed.</p>", unsafe_allow_html=True)

    pack = _pack(res)
    edb_files = {k: v for k, v in pack.items() if k.startswith("EDB_Submission")}

    with st.container(border=True):
        st.markdown("**1 · EDB submission template** — for EDB")
        st.markdown("<span class='muted'>The official RIS(C) export, filled with your qualifying staff "
                    "(one file per company). Claim formulas and totals are preserved.</span>",
                    unsafe_allow_html=True)
        if edb_files:
            cols = st.columns(len(edb_files))
            for col, (fname, data) in zip(cols, edb_files.items()):
                col.download_button(fname, data, file_name=fname, mime=_MIME, width="stretch")
        else:
            st.info("No qualifying staff yet — resolve the issues first.")

    with st.container(border=True):
        st.markdown("**2 · Statement of Expenditure (SOE)** — for the public accountant")
        st.markdown("<span class='muted'>The audit pack (SSRS 4400): expenditure summary, month-by-month "
                    "workings, the evidence trail (document & cell for every figure), the internal "
                    "cross-check, and excluded staff with reasons.</span>", unsafe_allow_html=True)
        st.download_button("Statement_of_Expenditure.xlsx", pack["Statement_of_Expenditure.xlsx"],
                           file_name="Statement_of_Expenditure.xlsx", mime=_MIME)

    with st.container(border=True):
        st.markdown("**3 · Issues to fix** — for HR")
        st.markdown("<span class='muted'>Everyone not yet claimed, colour-coded: amber = fixable "
                    "(document missing), red = not eligible, each with what to do.</span>",
                    unsafe_allow_html=True)
        st.download_button("Issues_to_fix.xlsx", pack["Issues_to_fix.xlsx"],
                           file_name="Issues_to_fix.xlsx", mime=_MIME)

    if not res.support_rate_is_final:
        st.caption("Files are marked non-final (UnauditedClaim) until EDB confirms the support rate.")


# ---------------------------------------------------------------------------
# navigation footer
# ---------------------------------------------------------------------------
_DOC_TYPE_BY_LABEL = {
    "Team timesheet": "timesheet",
    "ECMF researcher list": "ecmf",
    "Payroll / payslips": "payroll",
}


def _persist_to_store(res, docs=None) -> None:
    """Write the pipeline result into the SQLite store (FR-13) so the audit
    chatbot can retrieve a person's record by exact-SQL — true RAG over records,
    surviving across sessions. Best-effort: a store failure never breaks the run.

    When ``docs`` (the uploaded source files) are given, the raw bytes are also
    stored and linked to every employee in the result, so HR can later ask the
    chatbot to fetch the source documents for a person — resolved by employee id
    OR NRIC. A shared workbook is one ``document`` row fanned out to all
    employees via ``doc_link`` (the store dedupes identical bytes).
    """
    try:
        from edb_claim.db.schema import init_db
        from edb_claim.db.store import connect, persist_result, store_document
        init_db(settings.db_path)            # idempotent: ensure schema exists
        conn = connect(settings.db_path)
        try:
            persist_result(conn, res)
            for d in (docs or []):
                try:
                    with open(d["path"], "rb") as fh:
                        content = fh.read()
                except OSError:
                    continue
                doc_id = None
                doc_type = _DOC_TYPE_BY_LABEL.get(d.get("label"), "document")
                for e in getattr(res, "all_employees", ()) or ():
                    doc_id = store_document(
                        conn, e.employee.id, file=d["path"], content=content,
                        doc_type=doc_type, orig_filename=d.get("name"),
                        mime_type=_MIME, doc_id=doc_id,  # reuse the same row after the first link
                    )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — persistence is additive, never fatal
        pass


def _assistant():
    if "assistant" not in st.session_state:
        from edb_claim.llm.qa import AuditAssistant
        st.session_state["assistant"] = AuditAssistant(db_path=settings.db_path)
    return st.session_state["assistant"]


# ---------------------------------------------------------------------------
# AI advisories (FR-9/10/11) — model proposals over the deterministic result.
# Computed once and cached; the verdict/figures are NEVER changed by these.
# ---------------------------------------------------------------------------
def _advisories(run_extraction: bool = False):
    """Build (and cache) the AI advisory bundle for the current result.

    ``run_extraction`` opts into the per-row payslip extraction cross-check (one
    model call per row), so the default eligibility pass stays fast.
    """
    key = "advisories_x" if run_extraction else "advisories"
    if key not in st.session_state:
        from edb_claim.llm.advisories import build_advisories
        res = st.session_state.get("result")
        rse_records = ()
        rse_path = st.session_state.get("rse_path")
        if rse_path:
            try:
                from edb_claim.ingest.rse_list import parse_rse_list
                rse_records = parse_rse_list(rse_path)
            except Exception:  # never let advisory setup break the screen
                rse_records = ()
        st.session_state[key] = build_advisories(
            res, rse_records=rse_records,
            payroll_path=st.session_state.get("payroll_path"),
            run_extraction=run_extraction,
        )
    return st.session_state[key]


def _confidence_chip(conf) -> str:
    if conf is None:
        return ""
    pct = f"{conf*100:.0f}%"
    color = "#1F7A1F" if conf >= settings.confidence_cutoff else "#A85A00"
    return (f"<span class='pill' style='background:#EEF;color:{color}'>"
            f"confidence {pct}</span>")


def _render_designation_advisory(emp_id: str, adv) -> None:
    """Show the model's G5 judgement for a borderline role (FR-10/FR-14)."""
    j = adv.designations.get(emp_id)
    if j is None or not j.used_model:
        return
    verdict = "an eligible R&D role" if j.proposed_qualifies else "NOT an eligible R&D role"
    chip = _confidence_chip(j.confidence)
    st.markdown(
        f"<div style='border-left:3px solid #1F4E79;padding:6px 10px;margin-top:6px'>"
        f"🤖 <b>Local model's view:</b> {verdict} "
        f"<span class='muted'>({j.category})</span> &nbsp;{chip}<br>"
        f"<span class='muted'>{j.justification}</span></div>",
        unsafe_allow_html=True,
    )
    if not j.agrees_with_gate:
        st.warning("The model and the automated check disagree on this role — "
                   "please decide whether to claim this person.")
    if j.low_confidence:
        st.caption("Low confidence — treat as a prompt to look, not a decision.")


def _render_reconciliation_queue(adv) -> None:
    """Surface cross-document name/typo matches awaiting HR confirmation (FR-11)."""
    queue = adv.match_queue
    if not queue:
        return
    with st.expander(f"🔗 {len(queue)} identity match(es) need confirmation", expanded=True):
        st.markdown("<p class='muted'>These people appear under a different name spelling "
                    "or ID across documents. Exact-ID matches were linked automatically; "
                    "confirm these so the right ECMF record is used.</p>",
                    unsafe_allow_html=True)
        for m in queue:
            chip = _confidence_chip(m.confidence)
            kind = "name spelling/order" if m.match_kind == "name_variant" else "possible typo"
            st.markdown(
                f"<div style='border-left:3px solid #A85A00;padding:6px 10px;margin:6px 0'>"
                f"<b>{m.timesheet_name}</b> <span class='muted'>(timesheet {m.timesheet_id})</span>"
                f" &nbsp;↔&nbsp; <b>{m.candidate_name}</b> "
                f"<span class='muted'>({m.candidate_source} {m.candidate_id})</span>"
                f" &nbsp;<span class='muted'>· {kind}</span> &nbsp;{chip}<br>"
                f"<span class='muted'>{m.reason}</span></div>",
                unsafe_allow_html=True,
            )
            st.radio("Are these the same person?", ["Yes — same person", "No — different people"],
                     index=0 if m.same_person else 1, horizontal=True,
                     key=f"match_{m.timesheet_id}_{m.candidate_id}", label_visibility="collapsed")


def _send_chat() -> None:
    """Form-submit callback: answer the question and append to the transcript."""
    q = (st.session_state.get("chat_input") or "").strip()
    if not q:
        return
    res = st.session_state.get("result")
    ans = _assistant().answer(q, res)
    hist = st.session_state.setdefault("chat", [])
    hist.append({"role": "user", "text": q})
    hist.append({
        "role": "assistant", "text": ans.text, "citations": ans.citations,
        "offline": ans.offline, "used_model": ans.used_model, "mode": ans.mode,
    })


# ---------------------------------------------------------------------------
# Evidence preview — view the cited Excel sheet / PDF in its original form
# ---------------------------------------------------------------------------
def _grid_html(grid, focus_label: str) -> str:
    """Render a SheetGrid as a spreadsheet-like HTML table, highlighting the cell."""
    hi = "#FFE39A"  # focus cell fill
    head = "#1F4E79"
    cells = ["<table style='border-collapse:collapse;font-size:12px;font-family:monospace'>"]
    # column header row (corner + A,B,C…)
    cells.append("<tr>")
    cells.append(f"<th style='background:{head};color:#fff;border:1px solid #cbd5e1;"
                 "padding:2px 8px;position:sticky;left:0'></th>")
    for col in grid.col_letters:
        mark = col == grid.focus_col_letter
        cells.append(f"<th style='background:{'#2c5f96' if mark else head};color:#fff;"
                     "border:1px solid #cbd5e1;padding:2px 10px'>" + col + "</th>")
    cells.append("</tr>")
    for rnum, row in zip(grid.row_numbers, grid.rows):
        cells.append("<tr>")
        rmark = rnum == grid.focus_row
        cells.append(f"<th style='background:{'#2c5f96' if rmark else head};color:#fff;"
                     "border:1px solid #cbd5e1;padding:2px 8px;position:sticky;left:0'>"
                     + str(rnum) + "</th>")
        for col, val in zip(grid.col_letters, row):
            focus = (rnum == grid.focus_row and col == grid.focus_col_letter)
            style = ("background:%s;font-weight:600;border:2px solid #B45309" % hi) if focus \
                else "background:#fff;border:1px solid #e2e8f0"
            safe = (val or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cells.append(f"<td style='{style};padding:2px 10px;max-width:220px;"
                         f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{safe}</td>")
        cells.append("</tr>")
    cells.append("</table>")
    return "".join(cells)


def _render_preview_body(info: dict) -> None:
    """Render the preview contents for one citation (used by the dialog)."""
    file = info.get("file") or ""
    sheet_hint = info.get("sheet")
    cell = info.get("cell")
    label = info.get("label") or "source"
    registry = st.session_state.get("file_registry", {})
    path = resolve_evidence_path(file, registry)

    st.markdown(f"**{label}** &nbsp;·&nbsp; `{os.path.basename(file)}`"
                + (f" &nbsp;·&nbsp; sheet **{sheet_hint}**" if sheet_hint else "")
                + (f" &nbsp;·&nbsp; cell **{cell}**" if cell else ""))

    if not path or not os.path.exists(path):
        st.warning("The original file isn't available in this session. Re-upload the "
                   "document (or load the sample data) to preview it here.")
        return

    with open(path, "rb") as fh:
        raw = fh.read()
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        import base64
        b64 = base64.b64encode(raw).decode("ascii")
        st.markdown(
            f"<iframe src='data:application/pdf;base64,{b64}' width='100%' height='520' "
            "style='border:1px solid #cbd5e1;border-radius:6px'></iframe>",
            unsafe_allow_html=True,
        )
    elif ext in (".xlsx", ".xlsm"):
        sheet_ref, col, row = parse_cell_ref(cell)
        try:
            grid = excel_sheet_to_grid(path, sheet_ref or sheet_hint,
                                       focus_col=col, focus_row=row)
            st.caption(f"Sheet **{grid.sheet_name}** — the cited cell is highlighted."
                       + ("  Showing a window of the sheet." if grid.truncated else ""))
            st.markdown(f"<div style='overflow:auto;max-height:460px;border:1px solid #e2e8f0;"
                        f"border-radius:6px'>{_grid_html(grid, label)}</div>",
                        unsafe_allow_html=True)
        except Exception as exc:  # noqa: BLE001 — fall back to download on any read error
            st.info(f"Couldn't render this sheet inline ({exc}). Use the download below to open it.")
    else:
        st.info("Inline preview isn't available for this file type — download it below.")

    st.download_button("⬇  Download the original file", raw,
                       file_name=os.path.basename(file) or os.path.basename(path),
                       key=f"dl_{file}_{cell}")


@st.dialog("Evidence preview", width="large")
def _preview_dialog(info: dict) -> None:
    _render_preview_body(info)


def _toggle_chat() -> None:
    st.session_state["chat_open"] = not st.session_state.get("chat_open", False)


def _render_chat_fab_and_panel() -> None:
    """Floating chat: a fixed bottom-right button that toggles a docked panel."""
    st.button("💬", key="chat_fab", help="Ask the assistant", on_click=_toggle_chat)
    if not st.session_state.get("chat_open"):
        return
    with st.container(key="chat_panel"):
        top = st.columns([5, 1], vertical_alignment="center")
        with top[0]:
            st.markdown("**Grant & Verification Assistant**")
        with top[1]:
            st.button("✕", key="chat_close", on_click=_toggle_chat, help="Close")
        st.caption("🟢 Local model connected" if settings.llm_enabled
                   else "⚪ Offline — answering from the claim data and scheme rules")

        box = st.container(height=320)
        with box:
            hist = st.session_state.get("chat", [])
            if not hist:
                st.chat_message("assistant").markdown(
                    "Hi — ask me about the RIS(C) rules, a person's claim or reason, or say "
                    "“fetch the evidence for <name>” to pull the supporting documents.")
            for mi, m in enumerate(hist):
                with st.chat_message(m["role"]):
                    st.markdown(m["text"])
                    for ci, c in enumerate(m.get("citations", [])[:12]):
                        loc = f"{os.path.basename(c['file'])} · {c['cell']}"
                        cap_col, btn_col = st.columns([6, 1], vertical_alignment="center")
                        with cap_col:
                            st.caption(f"📎 {c.get('label') or 'source'} — {loc}")
                        with btn_col:
                            if st.button("🔍", key=f"prev_{mi}_{ci}",
                                         help="Preview this document in its original form"):
                                _preview_dialog(c)

        with st.form("chat_form", clear_on_submit=True, border=False):
            st.text_input("Ask the assistant", key="chat_input",
                          placeholder="e.g. fetch the evidence for ANS-002",
                          label_visibility="collapsed")
            st.form_submit_button("Send", width="stretch", on_click=_send_chat)


@st.dialog("Your documents", width="large")
def _docs_dialog() -> None:
    docs = st.session_state.get("uploaded_docs", [])
    if not docs:
        st.info("No documents in this session yet.")
        return
    st.caption("The source documents for this claim — open any to view it in its original form.")
    for i, d in enumerate(docs):
        cap, btn = st.columns([6, 1], vertical_alignment="center")
        with cap:
            st.markdown(f"📄 **{d['label']}** — <span class='muted'>{d['name']}</span>",
                        unsafe_allow_html=True)
        with btn:
            if st.button("👁 View", key=f"docsdlg_{i}"):
                _preview_dialog({"file": d["path"], "sheet": None,
                                 "cell": None, "label": d["label"]})


def _set_step(s: int) -> None:
    st.session_state["step"] = max(0, min(s, len(_STEPS) - 1))


def _reset() -> None:
    for k in ("result", "pack", "step", "ack_blockers", "advisories", "advisories_x",
              "rse_path", "payroll_path"):
        st.session_state.pop(k, None)


def _nav(active: int, *, can_continue: bool = True, blocked_hint: str = "") -> None:
    st.write("")
    st.divider()
    left, mid, right = st.columns([1, 4, 1])
    with left:
        if active > 0:
            st.button("←  Back", width="stretch", key="nav_back",
                      on_click=_set_step, args=(active - 1,))
    with right:
        if active < len(_STEPS) - 1:
            st.button("Continue  →", type="primary", width="stretch", key="nav_next",
                      on_click=_set_step, args=(active + 1,), disabled=not can_continue)
        else:
            st.button("Start over", width="stretch", key="nav_reset", on_click=_reset)
    with mid:
        if not can_continue and blocked_hint:
            st.markdown(f"<div style='text-align:center;color:#b54708'>{blocked_hint}</div>",
                        unsafe_allow_html=True)
            return
        q, blocked, excluded, _ = _counts(st.session_state["result"])
        st.markdown(
            f"<div style='text-align:center' class='muted'>"
            f"{len(q)} qualify · {_money(st.session_state['result'].total_claim_a)} · "
            f"{len(blocked) + len(excluded)} to review</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Pages (sidebar navigation)
# ---------------------------------------------------------------------------
def _page_home() -> None:
    st.markdown(
        "<div class='hero'><h2>EDB RIS(C) manpower-claim workspace</h2>"
        "<p class='muted'>Prepare a Research Incentive Scheme (Companies) manpower claim for the "
        "AI COE from your internal timesheet workbook — deterministically, with every figure "
        "traceable to its source cell. The claim, the eligibility checks and the EDB submission "
        "template are all produced from the timesheet alone; supporting documents are tracked "
        "separately. Nothing leaves this machine.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown("#### Sections")
    cards = [
        ("🧮", "Timesheet claim",
         "Upload the internal AI COE timesheet workbook. The app reads hours, roles, join/leave "
         "dates and the Staff Costs salary, runs EDB's eligibility gates, computes each person's "
         "claim (Method A — the submission basis) and fills the EDB output template. Salary comes "
         "from Staff Costs [A]; a missing payslip is flagged for that person, never blocking."),
        ("📋", "Document check",
         "Track the wider documentation EDB expects, per company and per person — Letter of Award, "
         "RISC submission form, CPF/bank proof of payment, PL3 confirmation, training certificates, "
         "progress reports and more. Independent of the calculation: tick what's on file and see "
         "what's still outstanding."),
        ("💬", "Assistant",
         "Ask about the scheme, a person's claim or eligibility reason, and fetch the stored "
         "supporting documents for any employee by their ID or NRIC — for EDB verification."),
    ]
    for icon, title, body in cards:
        with st.container(border=True):
            st.markdown(f"**{icon} {title}**")
            st.markdown(f"<span class='muted'>{body}</span>", unsafe_allow_html=True)
    st.caption("Use the sidebar to move between sections. Outputs remain non-final "
               "(UnauditedClaim) until EDB confirms the support rate and payslips are attached.")


def _timesheet_upload() -> None:
    """Upload + analyse the internal workbook ALONE (timesheet-only pipeline)."""
    with st.container(border=True):
        st.markdown("##### 1 · Add the timesheet workbook")
        mode = st.radio("Source", ["Use sample data", "Upload my files"],
                        horizontal=True, label_visibility="collapsed", key="ts_mode")
        internal_paths: List[str] = []
        docs: List[dict] = []
        if mode == "Use sample data":
            if any(not os.path.exists(p) for p in _SAMPLE_INTERNAL):
                st.error("Sample data missing. Run `python sample_data/generate.py`.")
                return
            internal_paths = list(_SAMPLE_INTERNAL)
            reg = st.session_state.setdefault("file_registry", {})
            for p in internal_paths:
                reg[os.path.basename(p)] = p  # citations cite the basename
            docs = [{"label": "Team timesheet", "path": p, "name": os.path.basename(p)}
                    for p in internal_paths]
            st.caption("Loaded a worked example: 2 companies · 20 staff covering the full range of cases.")
        else:
            ups = st.file_uploader("Internal AI COE timesheet workbook(s)", type=["xlsx"],
                                   accept_multiple_files=True, key="ts_upload")
            for u in (ups or []):
                p = _persist(u)
                if p:
                    internal_paths.append(p)
                    docs.append({"label": "Team timesheet", "path": p, "name": u.name})

        if docs:
            st.markdown("##### 2 · Review")
            st.caption("Open any file to check it's the right one before analysing.")
            for i, d in enumerate(docs):
                cap, btn = st.columns([6, 1], vertical_alignment="center")
                with cap:
                    st.markdown(f"📄 **{d['label']}** — <span class='muted'>{d['name']}</span>",
                                unsafe_allow_html=True)
                with btn:
                    if st.button("👁 View", key=f"tsview_{i}"):
                        _preview_dialog({"file": d["path"], "sheet": None, "cell": None,
                                         "label": d["label"]})

        st.markdown("##### 3 · Analyse")
        if st.button("Analyse timesheet  →", type="primary", key="ts_analyse"):
            if not internal_paths:
                st.warning("Add at least one timesheet workbook to continue.")
                return
            with st.status("Computing the claim from the timesheet…", expanded=False) as status:
                res = run_pipeline(internal_paths, timesheet_only=True)
                _persist_to_store(res, docs)  # FR-13 write-through + store the source file(s)
                status.update(label="Analysis complete", state="complete")
            st.session_state["result"] = res
            st.session_state["uploaded_docs"] = docs
            for k in ("pack", "advisories", "advisories_x", "assistant"):
                st.session_state.pop(k, None)  # rebind against the fresh result/store
            st.rerun()


def _page_timesheet() -> None:
    st.markdown("### 🧮 Timesheet claim")
    st.markdown("<p class='muted'>The claim, eligibility and EDB template are computed from the "
                "internal timesheet workbook alone — deterministically. Salary is read from the "
                "Staff Costs [A] figure; a missing payslip is flagged for that person but does not "
                "block the claim (documents are tracked in the Document check section).</p>",
                unsafe_allow_html=True)
    st.toggle("🔬 Advanced view", key="advanced",
              help="Show the full month-by-month calculation workings — no black box.")
    _timesheet_upload()

    res = st.session_state.get("result")
    if res is None:
        return

    # informational, non-blocking flags (e.g. payslip not uploaded)
    flagged = [e for e in res.all_employees if e.flags]
    if flagged:
        with st.expander(f"ℹ️ {len(flagged)} note(s) for HR (non-blocking)", expanded=False):
            for e in flagged:
                for f in e.flags:
                    st.markdown(f"- **{e.employee.name}** ({e.employee.id}) — {f}")

    q, blocked, excluded, _review = _counts(res)
    m1, m2, m3 = st.columns(3)
    m1.metric("Qualifying staff", len(q))
    m2.metric("Total claim (Method A)", _money(res.total_claim_a))
    m3.metric("To review", len(blocked) + len(excluded))

    tabs = st.tabs(["Eligibility", "Claim amount", "Submission pack"])
    with tabs[0]:
        _step_eligibility(res)
    with tabs[1]:
        _step_claim(res)
    with tabs[2]:
        _step_pack(res)


# EDB-expected documentation — the independent tracker (per company / per person).
_EXPECTED_DOCS = {
    "Per company": [
        "Completed RISC submission form",
        "EDB Letter of Award / offer letter",
        "Skill validation list",
        "List of trainees (emp. no + training dates)",
        "Supporting AI artifacts (codebase / app)",
        "Leave report",
        "Filled EDB output template",
    ],
    "Per person": [
        "Monthly payslips",
        "CPF & bank statements (proof of payment)",
        "Formal PL3 status confirmation",
        "Training certification (CLT / external)",
        "Signed monthly progress reports",
        "Daily clocking records",
    ],
}


def _page_doccheck() -> None:
    st.markdown("### 📋 Document check")
    st.markdown("<p class='muted'>Track the documentation EDB expects for the claim, per company and "
                "per person. This is independent of the calculation — tick what you have on file; "
                "anything unticked is listed as outstanding for the audit pack.</p>",
                unsafe_allow_html=True)

    tracker = st.session_state.setdefault("doc_tracker", {})
    outstanding: List[dict] = []
    cols = st.columns(len(_EXPECTED_DOCS))
    for col, (scope, items) in zip(cols, _EXPECTED_DOCS.items()):
        with col:
            with st.container(border=True):
                st.markdown(f"**{scope}**")
                for it in items:
                    key = f"dc::{scope}::{it}"
                    on = st.checkbox(it, value=tracker.get(key, False), key=key)
                    tracker[key] = on
                    if not on:
                        outstanding.append({"Scope": scope, "Document": it})

    st.write("")
    if outstanding:
        st.warning(f"**{len(outstanding)} document type(s) outstanding** for the audit pack.")
        st.dataframe(pd.DataFrame(outstanding), hide_index=True, width="stretch")
    else:
        st.success("All expected documents are marked as on file.")

    # If a timesheet claim has been run, surface which people still need a payslip.
    res = st.session_state.get("result")
    if res is not None:
        flagged = [e for e in res.all_employees if e.flags]
        if flagged:
            with st.expander(f"From the latest timesheet claim: {len(flagged)} person(s) "
                             "with a document note"):
                st.dataframe(pd.DataFrame([
                    {"Employee": e.employee.name, "ID": e.employee.id, "Note": "; ".join(e.flags)}
                    for e in flagged]), hide_index=True, width="stretch")


def _fetch_doc_blob(doc_id: str):
    """Read a stored document's bytes from the FR-13 store (None on any failure)."""
    try:
        from edb_claim.db.store import connect, fetch_blob
        conn = connect(settings.db_path)
        try:
            return fetch_blob(conn, doc_id)
        finally:
            conn.close()
    except Exception:
        return None


def _render_citations(msg: dict, mi: int) -> None:
    """Render an assistant message's citations: download stored docs, preview cells."""
    for ci, c in enumerate(msg.get("citations", [])[:12]):
        label = c.get("label") or "source"
        doc_id = c.get("doc_id")
        cap_col, btn_col = st.columns([6, 1], vertical_alignment="center")
        if doc_id:
            with cap_col:
                st.caption(f"📎 {label} — {os.path.basename(c.get('file') or '')}")
            with btn_col:
                blob = _fetch_doc_blob(doc_id)
                if blob is not None:
                    content, mime, fname = blob
                    st.download_button("⬇", content, file_name=fname or f"{doc_id}.bin",
                                       mime=mime or "application/octet-stream",
                                       key=f"dl_{mi}_{ci}", help="Download this document")
        else:
            loc = os.path.basename(c.get("file") or "")
            if c.get("cell"):
                loc += f" · {c['cell']}"
            with cap_col:
                st.caption(f"📎 {label} — {loc}")
            with btn_col:
                if c.get("file") and st.button("🔍", key=f"cbprev_{mi}_{ci}",
                                                help="Preview this document in its original form"):
                    _preview_dialog(c)


def _page_chatbot() -> None:
    st.markdown("### 💬 Grant & verification assistant")
    st.caption("🟢 Local model connected" if settings.llm_enabled
               else "⚪ Offline — answering from the claim data and scheme rules")
    st.markdown("<p class='muted'>Ask about the scheme, a person's claim or eligibility reason, or "
                "fetch stored supporting documents for an employee by their ID or NRIC "
                "(e.g. “documents for S1234567A”).</p>", unsafe_allow_html=True)

    hist = st.session_state.get("chat", [])
    if not hist:
        with st.chat_message("assistant"):
            st.markdown("Hi — ask me about the RIS(C) rules, a person's claim, or say "
                        "“fetch the documents for &lt;name / ID / NRIC&gt;”.")
    for mi, m in enumerate(hist):
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            _render_citations(m, mi)

    prompt = st.chat_input("e.g. documents for ANS-002")
    if prompt:
        st.session_state["chat_input"] = prompt
        _send_chat()
        st.rerun()


# ---------------------------------------------------------------------------
# main — sidebar navigation
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="EDB Grant Claim Portal", page_icon="📑", layout="wide")
    _inject_css()
    with st.sidebar:
        st.markdown("### 📑 EDB RIS(C) Portal")
        st.caption("AI COE manpower claim · fully local")
    nav = st.navigation([
        st.Page(_page_home, title="Home", icon="🏠", default=True),
        st.Page(_page_timesheet, title="Timesheet claim", icon="🧮"),
        st.Page(_page_doccheck, title="Document check", icon="📋"),
        st.Page(_page_chatbot, title="Assistant", icon="💬"),
    ])
    nav.run()


main()
