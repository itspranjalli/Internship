"""Minimal Streamlit host to screenshot the REAL evidence-preview UI.

Renders the actual chat panel (with the new 🔍 Preview buttons) and the actual
preview-dialog body, using the real functions from app/main.py over real pipeline
data — so the screenshot reflects shipping code, not a mock.

Run:  .venv/bin/streamlit run tests/_preview_ui_demo.py --server.headless true
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import streamlit as st

from edb_claim.app import main as app
from edb_claim.app.pipeline import run_pipeline

st.set_page_config(page_title="Evidence preview", layout="wide")
app._inject_css()

SD = os.path.join(_REPO, "sample_data")


@st.cache_resource
def _bootstrap():
    """Run the pipeline once and produce a real evidence answer + citations."""
    res = run_pipeline(
        [os.path.join(SD, "internal_ANS.xlsx"), os.path.join(SD, "internal_DSG.xlsx")],
        os.path.join(SD, "rse_list.xlsx"), os.path.join(SD, "payroll.xlsx"),
    )
    from edb_claim.llm.qa import AuditAssistant
    ans = AuditAssistant().answer("fetch the evidence for ANS-001", res)
    return res, ans


res, ans = _bootstrap()
st.session_state["result"] = res
# registry so the preview resolves the cited basenames to the real sample files
reg = st.session_state.setdefault("file_registry", {})
for p in (os.path.join(SD, f) for f in
          ("internal_ANS.xlsx", "internal_DSG.xlsx", "rse_list.xlsx", "payroll.xlsx")):
    reg[os.path.basename(p)] = p
# seed the chat transcript with the real evidence answer
st.session_state["chat"] = [
    {"role": "user", "text": "fetch the evidence for ANS-001"},
    {"role": "assistant", "text": ans.text, "citations": ans.citations,
     "offline": ans.offline, "used_model": ans.used_model, "mode": ans.mode},
]

left, right = st.columns([1, 1.3], gap="large")
with left:
    st.markdown("#### Assistant — every figure carries its source, now with a preview")
    with st.container(border=True):
        st.caption("🟢 Local model connected" if app.settings.llm_enabled
                   else "⚪ Offline — answering from the claim data and scheme rules")
        for mi, m in enumerate(st.session_state["chat"]):
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
                            app._preview_dialog(c)
with right:
    st.markdown("#### 🔍 Preview (the modal that opens on click)")
    # pick the payroll basic-salary citation if present, else the first one
    cites = ans.citations or []
    pick = next((c for c in cites if "payroll" in (c.get("file") or "")), cites[0] if cites else None)
    if pick:
        with st.container(border=True):
            app._render_preview_body(pick)
    else:
        st.info("No citations produced.")
