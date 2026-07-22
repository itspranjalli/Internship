"""Central, static configuration — the single source of tunables (PLAN.md §1).

Implemented as a frozen dataclass (stdlib only) so it imports with no third-party
dependency and is immutable at runtime (determinism, PRD §9). Env-var overrides are
read once at module import via ``Config.from_env()``; the resulting ``settings``
object is the canonical instance the rest of the package imports.

Design rules honoured here:
  * No nondeterminism in defaults — no ``datetime.now()`` / random / cwd-dependent
    values are baked in (PRD §9 "same inputs -> identical outputs").
  * No dependency on a running LLM endpoint — ``llm_base_url`` defaults to ``None``
    (stub mode); the deterministic pipeline must run with NO model configured
    (CLAUDE.md "LLM deferred", PRD FR-14).
  * Every ASSUMED value is marked; PRD/CLAUDE.md section cited per constant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Mapping, Optional, Tuple


def _env_str(key: str, default: Optional[str]) -> Optional[str]:
    val = os.environ.get(key)
    return val if val not in (None, "") else default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val in (None, ""):
        return default
    return float(val)


# --- non-qualifying designations (gate G5) --------------------------------
# EDB's non-qualifying categories; a person whose designation falls in one of
# these fails gate G5 -> verdict EXCLUDED (PRD §6 gate table, FR-10).
NON_QUALIFYING_DESIGNATIONS: Tuple[str, ...] = (
    "Marketing",
    "Finance",
    "Sales",
    "HR",
    "Admin",
    "Facilities Mgmt",
    "Legal",
)

# --- entities -------------------------------------------------------------
# The 16 base UENs, read verbatim from the hidden ``List`` sheet (B3:B18) of
# AI_COE_Claim_Checklist_Timesheet_for_FY_2026_to_2028_v2_Final.xlsx (CLAUDE.md
# "Source templates", PRD FR-1). Order preserved from the sheet.
BASE_ENTITIES: Tuple[str, ...] = (
    "ST Engineering IHQ Pte Ltd",
    "ST Engineering Advanced Networks & Sensors Pte Ltd",
    "ST Engineering Digital System Pte Ltd",
    "ST Engineering Geo-Insights Pte Ltd",
    "ST Engineering Mission Software & Services Pte Ltd",
    "ST Engineering Training & Simulation Systems Pte Ltd",
    "ST Engineering Unmanned & Integrated Systems Pte Ltd",
    "ST Engineering Advanced Material Engineering Pte Ltd",
    "ST Engineering Land MRO & Services Pte Ltd",
    "ST Engineering Land Systems Ltd",
    "ST Engineering Autonomous Solutions Pte Ltd",
    "ST Engineering Urban Solutions Ltd.",
    "ST Engineering Mobility Services Pte Ltd",
    "STA Inspection Pte Ltd",
    "ST Engineering Aerospace Ltd",
    "ST Engineering Marine Ltd",
)

# 16 base UENs -> participating entities. The IHQ split is read from the
# workbook's "Participating entities" sheet: ST Engineering IHQ Pte Ltd
# (S/No 1) is listed against three AI COE centres in col D — GEC / GTO / IT
# (rows 5-7) — while the other 15 entities map 1:1.
#
# *** SOURCE-DOC DISCREPANCY (flagged, not silently resolved) ***
# PRD FR-1 and CLAUDE.md both lock the count at *17* participating entities
# ("IHQ splits into GEC/GTO/IT to yield the 17"), but the workbook shows IHQ
# against THREE centre codes, which gives 15 + 3 = 18. These cannot both hold.
# We replicate the workbook (the layout authority) -> 18 entries, rather than
# silently dropping a centre to force 17 (CLAUDE.md: exclusions are never
# silently dropped). ASSUMED/PENDING confirmation: whether IHQ has 2 or 3
# claimable centres, and therefore whether the canonical count is 17 or 18.
#
# ASSUMED: the participating-entity display names for the IHQ split below
# ("... (GEC/GTO/IT)") are our naming convention; the workbook only stores the
# bare centre codes — pending confirmation of the exact label HR wants on output.
_IHQ = "ST Engineering IHQ Pte Ltd"
BASE_TO_PARTICIPATING: Mapping[str, Tuple[str, ...]] = {
    _IHQ: (
        f"{_IHQ} (GEC)",
        f"{_IHQ} (GTO)",
        f"{_IHQ} (IT)",
    ),
    # all other base entities map 1:1
    **{e: (e,) for e in BASE_ENTITIES if e != _IHQ},
}

# Flattened canonical 17-entity list (order: base-sheet order, IHQ expanded).
PARTICIPATING_ENTITIES: Tuple[str, ...] = tuple(
    p for e in BASE_ENTITIES for p in BASE_TO_PARTICIPATING[e]
)


@dataclass(frozen=True)
class Config:
    """Immutable bundle of all tunables. Build via :meth:`from_env`."""

    # --- support rate (EDB Support Package for AI COE) --------------------
    # CONFIRMED 60% of the (capped) basic monthly salary — per the EDB Support
    # Package ("up to 60% of monthly salary ... capped at $20k"). This replaces
    # the earlier 30% placeholder. ``support_rate_is_final`` now means "the rate
    # is confirmed" (True). It is DECOUPLED from whether the claim has been
    # externally audited — that is ``claim_is_audited`` below (always False in
    # the POC; the ACRA Practitioner audits outside the system).
    support_rate: float = 0.60  # CONFIRMED — EDB Support Package (was 0.30 ASSUMED)
    support_rate_is_final: bool = True   # rate confirmed; not the audit status
    claim_is_audited: bool = False       # POC always pre-audit (Practitioner audits externally)

    # --- grant ceiling & disbursement (EDB Support Package) ---------------
    # Maximum Grant Amount S$42m, manpower (salary) ONLY. Disbursement gate:
    # once cumulative disbursements reach 70% of the max, the remaining 30% is
    # held back until project completion + all T&Cs met.
    max_grant_amount: int = 42_000_000          # S$42m manpower-only ceiling
    disbursement_threshold_pct: float = 0.70    # 70% released; 30% holdback
    min_claim_months: int = 3                   # each claim must cover ≥ 3 months

    # --- qualifying-cost duration rules (EDB Support Package) -------------
    # New hires: 60% across the qualifying period (no month cap). Existing staff
    # upskilling/reskilling to PL3: 60% for UP TO 9 months only. The anchor for
    # those 9 months is ASSUMED "first_qualifying" (earliest qualifying months)
    # and is configurable/pending the Letter of Award (other option: training
    # start date from the trainee list).
    upskill_max_months: int = 9                 # 9-month cap for upskilled-to-PL3
    upskill_cap_anchor: str = "first_qualifying"  # ASSUMED; or "training_start" (LoA)

    # --- audit & reporting cadence (EDB Support Package; compliance) ------
    audit_report_interval_months: int = 12      # Practitioner's Report ≥ every 12 months
    final_submission_days: int = 183            # final Audited Claim within 183 days of QP end

    # --- salary thresholds (PRD §6) ---------------------------------------
    # floor = exclusion GATE G4 (basic monthly salary < 5000 -> EXCLUDED);
    # cap   = arithmetic CLAMP applied per month to a retained person.
    # Basic monthly salary ONLY (no CPF/bonus/AWS/allowances) — CLAUDE.md.
    salary_floor: int = 5000   # G4 gate floor (PRD §6)
    salary_cap: int = 20000    # arithmetic cap MIN(salary, cap) (PRD §6)

    # --- working-time basis (PRD §6, §10 Q5) ------------------------------
    # Working days = weekdays only (Mon-Fri). Public holidays do NOT reduce
    # working days (matches EDB example + internal NETWORKDAYS).
    # Q5 ASSUMED "no public-holiday adjustment" — pending auditor confirmation.
    hours_per_day: float = 8.8                 # PRD §6
    weekdays_only: bool = True                  # Mon-Fri, no weekends (PRD §6)
    public_holiday_adjustment: bool = False     # ASSUMED no (Q5)

    # --- claim / qualifying windows (PRD §10 Q7, §1) ----------------------
    # POC default claim window (Q7); distinct from the full qualifying period.
    claim_period_start: date = date(2026, 1, 1)   # Q7 POC default
    claim_period_end: date = date(2026, 6, 30)     # Q7 POC default
    qualifying_period_start: date = date(2026, 1, 1)  # scheme window (§1)
    qualifying_period_end: date = date(2028, 12, 31)  # scheme window (§1)

    # --- LLM confidence surfacing (PRD FR-9 / FR-14) ----------------------
    # ASSUMED 0.85. This is the threshold at which the explanation + confirm
    # prompt is SURFACED to HR — NOT a discard threshold. Nothing is dropped.
    confidence_cutoff: float = 0.85  # ASSUMED (FR-9/FR-14)

    # --- variance reconciliation (PRD §6 discrepancies, §10 Q1) -----------
    # A row whose |Δ%| (A vs B) exceeds this is reported as materially
    # divergent. The two methods are KNOWN to disagree (ruling pending, Q1);
    # this is an informational flag for the reconciliation report, it does NOT
    # resolve which method is correct. Δ% is relative to Method A (submission
    # basis); a New-Hire B>A row is flagged separately regardless of magnitude.
    variance_material_pct: float = 1.0  # ASSUMED reporting threshold (Q1)

    # --- gate G5 vocabulary (PRD §6) --------------------------------------
    non_qualifying_designations: Tuple[str, ...] = NON_QUALIFYING_DESIGNATIONS

    # --- entities (PRD FR-1) ----------------------------------------------
    base_entities: Tuple[str, ...] = BASE_ENTITIES
    participating_entities: Tuple[str, ...] = PARTICIPATING_ENTITIES
    base_to_participating: Mapping[str, Tuple[str, ...]] = field(
        default_factory=lambda: dict(BASE_TO_PARTICIPATING)
    )

    # --- LLM adapter (PRD §7, §9; CLAUDE.md) ------------------------------
    # Provider-agnostic OpenAI-compatible. base_url None => stub mode (no live
    # endpoint). The deterministic pipeline must run with NO model configured.
    # Qwen 3.6 35B A3B via vLLM is the intended provider but is DEFERRED.
    llm_base_url: Optional[str] = None          # env EDB_LLM_BASE_URL
    llm_model: Optional[str] = None             # env EDB_LLM_MODEL
    llm_temperature: float = 0.0                 # temp 0, schema-constrained (§7)
    # API key for the endpoint. A local vLLM endpoint ignores it, so the default
    # placeholder keeps the offline path working; a hosted provider (e.g. OpenAI)
    # needs a real key. env EDB_LLM_API_KEY, falling back to OPENAI_API_KEY.
    llm_api_key: str = "not-needed-local"        # env EDB_LLM_API_KEY / OPENAI_API_KEY

    # --- embeddings (PRD FR-13 / T23) -------------------------------------
    # Local sentence-transformer by default (offline); switchable via env.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # env EDB_EMBEDDING_MODEL

    # --- persistence (PRD FR-13) ------------------------------------------
    db_path: str = "./edb_claim.db"  # SQLite + sqlite-vec, single file (env EDB_DB_PATH)

    @classmethod
    def from_env(cls) -> "Config":
        """Construct, applying env-var overrides for the sensible knobs.

        Only operational knobs (LLM endpoint, model, embedding model, db path,
        support rate) are env-overridable; locked domain rules are not, to keep
        audit determinism. Reads os.environ once at import time.
        """
        base = cls()
        return replace(
            base,
            support_rate=_env_float("EDB_SUPPORT_RATE", base.support_rate),
            llm_base_url=_env_str("EDB_LLM_BASE_URL", base.llm_base_url),
            llm_model=_env_str("EDB_LLM_MODEL", base.llm_model),
            llm_api_key=_env_str("EDB_LLM_API_KEY", _env_str("OPENAI_API_KEY", base.llm_api_key))
            or base.llm_api_key,
            embedding_model=_env_str("EDB_EMBEDDING_MODEL", base.embedding_model)
            or base.embedding_model,
            db_path=_env_str("EDB_DB_PATH", base.db_path) or base.db_path,
        )

    # --- convenience ------------------------------------------------------
    @property
    def claim_period(self) -> Tuple[date, date]:
        return (self.claim_period_start, self.claim_period_end)

    @property
    def qualifying_period(self) -> Tuple[date, date]:
        return (self.qualifying_period_start, self.qualifying_period_end)

    @property
    def llm_enabled(self) -> bool:
        """True only when a base URL is configured (else stub mode)."""
        return bool(self.llm_base_url)


# Canonical instance imported across the package.
settings = Config.from_env()
