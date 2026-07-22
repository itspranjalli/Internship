"""Ad-hoc proof that the in-app chatbot is backed by the LOCAL OFFLINE model.

Not a unit test — a demonstration script. It establishes three independent facts:

  1. STRUCTURAL  — the configured endpoint is localhost vLLM (no internet route),
     and the server reports exactly the Qwen model run_app.sh launches.
  2. IDENTITY    — asked who it is, the raw model self-identifies (Qwen, local).
  3. OFFLINE-NESS — asked real-time / very-recent questions, the model cannot
     answer (no live clock, no web). An internet-backed service would nail these;
     a frozen offline model disclaims or guesses. THAT gap is the proof.

It also shows that the actual in-app chatbot (AuditAssistant) routes through this
same localhost endpoint. Run:  .venv/bin/python tests/_prove_offline_model.py
"""

from __future__ import annotations

import dataclasses
import os
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# Mirror run_app.sh: connect the local Qwen/vLLM endpoint before config import.
os.environ.setdefault("EDB_LLM_BASE_URL", "http://localhost:8000/v1")
os.environ.setdefault("EDB_LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

from edb_claim.config import Config
from edb_claim.llm.qa import AuditAssistant

cfg = Config.from_env()


def rule(title):
    print("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def ask_raw(client, model, question, max_tokens=1500):
    """Free-form (unconstrained) call straight to the served model.

    Qwen3.6 is a reasoning model: it emits chain-of-thought into a separate
    ``reasoning`` field and only fills ``content`` once thinking finishes, so we
    give a generous token budget and fall back to the reasoning text if needed.
    """
    t0 = time.perf_counter()
    out = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    dt = time.perf_counter() - t0
    msg = out.choices[0].message
    text = (msg.content or "").strip()
    if not text:  # ran out of budget mid-thought; show the reasoning instead
        text = "(no final answer; reasoning: " + (getattr(msg, "reasoning", "") or "")[:200] + " …)"
    return text, dt


def main():
    from openai import OpenAI

    # ---- 1. STRUCTURAL ---------------------------------------------------
    rule("1. STRUCTURAL — where the chatbot actually points")
    print(f"  EDB_LLM_BASE_URL : {cfg.llm_base_url}")
    print(f"  EDB_LLM_MODEL    : {cfg.llm_model}")
    print(f"  llm_enabled      : {cfg.llm_enabled}")
    is_local = "localhost" in (cfg.llm_base_url or "") or "127.0.0.1" in (cfg.llm_base_url or "")
    print(f"  -> loopback (no internet route): {is_local}")

    client = OpenAI(base_url=cfg.llm_base_url, api_key="not-needed-local")
    served = client.models.list()
    served_ids = [m.id for m in served.data]
    print(f"  server /v1/models reports: {served_ids}")
    print(f"  -> matches configured model: {cfg.llm_model in served_ids}")

    # ---- 2. IDENTITY -----------------------------------------------------
    rule("2. IDENTITY — ask the raw model who/what it is")
    ans, dt = ask_raw(client, cfg.llm_model,
                      "In one short sentence: what model are you, who made you, "
                      "and are you running locally or in the cloud?")
    print(f"  Q: what model are you?\n  A: {ans}\n  ({dt:.2f}s on local GPU)")

    # ---- 3. OFFLINE-NESS — recent / real-time questions ------------------
    rule("3. OFFLINE-NESS — 'latest online' questions it cannot know")
    print("  A frozen, air-gapped model has no live clock and no web. So:\n")
    recent_qs = [
        "What is today's exact date and current time right now?",
        "What is the very latest news headline today, with today's date?",
        "Who won the most recent Formula 1 Grand Prix, and on what date was it held?",
        "What is the current price of Bitcoin in USD as of right now?",
    ]
    for q in recent_qs:
        ans, dt = ask_raw(client, cfg.llm_model, q, max_tokens=4000)
        print(f"  Q: {q}\n  A: {ans}\n  ({dt:.2f}s)\n")
    print("  ^ If these are disclaimed / outdated / guessed rather than answered\n"
          "    with live data, the model has NO internet — it is the offline model.")

    # ---- 4. SAME PATH AS THE APP ----------------------------------------
    rule("4. The in-app chatbot (AuditAssistant) uses THIS endpoint")
    asst = AuditAssistant(config=cfg)
    a = asst.answer("Explain in plain words how the claim amount is calculated.")
    print(f"  used_model (offline Qwen phrased it): {a.used_model}")
    print(f"  offline flag                        : {a.offline}")
    print(f"  grounded (constrained to scheme KB) : {a.grounded}")
    print(f"  answer: {a.text[:300]}")
    print("\n  -> used_model=True means the localhost Qwen produced this answer.\n"
          "     Note: in the app the model is GROUNDED to the scheme KB, so it\n"
          "     refuses world-trivia by design. The raw calls above bypass that\n"
          "     grounding to expose the model's own (offline) knowledge.")


if __name__ == "__main__":
    main()
