"""End-to-end orchestration of the deterministic claim pipeline (the UI's backend).

This module is the single seam the Streamlit shell (``app/main.py``) calls. It
wires the already-built, independently-tested layers together per employee:

    ingest (T2/T3)  ->  completeness (T4)  +  gates/crosschecks (T5)
                    ->  Method A & Method B (T6/T7)  ->  variance (T8)
                    ->  verdict (T9)

It adds **no** new domain logic and computes **no** claim figure itself — every
amount comes straight out of ``calc/``; this file only assembles inputs and
groups the per-employee results. It imports nothing from ``edb_claim.llm`` (the
deterministic core must run with no model configured — CLAUDE.md).

Determinism: input order is preserved throughout (employees in Time-Sheet order,
entities in upload order), so the same files always yield the same result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from edb_claim.config import Config, settings
from edb_claim.domain.models import (
    Employee,
    GateCode,
    HireType,
    MethodAResult,
    MethodBResult,
    SalaryRecord,
    Verdict,
    VarianceReport,
)
from edb_claim.ingest.timesheet import IngestResult, StaffCostsRow, parse_internal_workbook
from edb_claim.ingest.rse_list import (
    RseListRecord,
    index_by_employee_id,
    parse_rse_list,
)
from edb_claim.ingest.salary import index_by_employee_month, parse_payroll_register
from edb_claim.validate.completeness import (
    CompletenessResult,
    DocType,
    EmployeeRollup,
    build_completeness,
)
from edb_claim.validate.crosschecks import CrossCheckWarning, run_crosschecks
from edb_claim.validate.gates import GateEvaluation, evaluate_person_month
from edb_claim.validate.verdict import compute_verdict
from edb_claim.calc.method_a import compute_method_a_from_person_months
from edb_claim.calc.method_b import MethodBDetail, MethodBInput, compute_method_b
from edb_claim.calc.variance import compute_variance


# ---------------------------------------------------------------------------
# Supporting-evidence presence (the wider HR checklist; FR-2)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SupportingDocs:
    """Presence of the wider HR evidence checklist, supplied by the UI.

    The three core inputs (timesheet, RSE list, payroll) drive the calculation
    and are passed as file paths. This bundle carries the *presence* of the
    remaining documents an HR officer assembles per UEN — they are presence-
    checked only (never parsed), per PRD §4/FR-2. Every field is tri-state:
    ``True`` (provided), ``False`` (missing → flag), or ``None`` (not tracked
    this run → no matrix cell, leaving the result identical to the core POC).

    Per-person fields apply uniformly to every rostered employee in the POC
    (we don't yet attribute evidence to individuals — same stance as CPF/bank).
    """

    # entity-once (per UEN)
    risc_submission_form: Optional[bool] = None   # WARNING (approval already granted)
    letter_of_award: Optional[bool] = None
    skill_validation_list: Optional[bool] = None
    trainee_list: Optional[bool] = None
    ai_artifacts: Optional[bool] = None
    leave_report: Optional[bool] = None           # existing entity WARNING
    edb_template: Optional[bool] = None           # existing entity BLOCKER (default present)
    # per-person (uniform across the roster)
    cpf_bank: Optional[bool] = None               # drives CPF + bank (proof of payment)
    pl3_confirmation: Optional[bool] = None
    training_certification: Optional[bool] = None
    monthly_progress_report: Optional[bool] = None
    daily_clocking: Optional[bool] = None

    def entity_docs(self) -> Dict[DocType, Optional[bool]]:
        return {
            DocType.RISC_SUBMISSION_FORM: self.risc_submission_form,
            DocType.LETTER_OF_AWARD: self.letter_of_award,
            DocType.SKILL_VALIDATION_LIST: self.skill_validation_list,
            DocType.TRAINEE_LIST: self.trainee_list,
            DocType.AI_ARTIFACTS: self.ai_artifacts,
        }

    def person_docs(self) -> Dict[DocType, Optional[bool]]:
        return {
            DocType.PL3_CONFIRMATION: self.pl3_confirmation,
            DocType.TRAINING_CERTIFICATION: self.training_certification,
            DocType.MONTHLY_PROGRESS_REPORT: self.monthly_progress_report,
            DocType.DAILY_CLOCKING: self.daily_clocking,
        }


# ---------------------------------------------------------------------------
# Result containers (what the UI renders)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EmployeeResult:
    """Everything computed for one trainee, ready to render."""

    employee: Employee
    verdict: Verdict
    rollup: Optional[EmployeeRollup]
    method_a: MethodAResult
    method_b: Optional[MethodBResult]
    method_b_detail: Optional[MethodBDetail]
    gate_evaluations: Tuple[GateEvaluation, ...]
    crosscheck_warnings: Tuple[CrossCheckWarning, ...]
    staff_cost: Optional[StaffCostsRow]
    # presentation fields for the output documents (SOE / EDB template) -----
    monthly_basic_salary: Optional[float] = None  # actual, uncapped (EDB col D)
    involvement_from: Optional[date] = None        # claim window ∩ employment
    involvement_to: Optional[date] = None
    # informational, non-blocking notes for HR (e.g. timesheet-only presumptions).
    # These never change the verdict or the figures — they just explain caveats.
    flags: Tuple[str, ...] = ()

    @property
    def needs_review(self) -> bool:
        """Borderline gate (e.g. ambiguous G5) OR a qualifying-but-$0 claim.

        A person who passes every eligibility gate but whose Method A claim is
        $0 (typically a New Hire with no project hours recorded) must NOT read as
        a clean qualifier — there is nothing to claim until the hours are entered.
        """
        return any(ev.needs_review for ev in self.gate_evaluations) or self.zero_claim

    @property
    def zero_claim(self) -> bool:
        """Eligible, but the Method A claim is $0 — e.g. no project hours logged."""
        return self.verdict.status.value == "QUALIFIES" and self.method_a.claim_amount == 0

    @property
    def qualifies(self) -> bool:
        return self.verdict.status.value == "QUALIFIES"

    @property
    def claim_amount(self) -> float:
        """The amount we submit to EDB — Method A (the submission basis)."""
        return self.method_a.claim_amount

    @property
    def crosscheck_ok(self) -> bool:
        """True when Method B agrees with A (no material divergence, no flag)."""
        if self.method_b is None:
            return True
        a, b = self.method_a.claim_amount, self.method_b.claim_amount
        if self.method_b.new_hire and b > a:
            return False
        if a == 0:
            return b == 0
        return abs(a - b) / a * 100.0 <= 1.0


@dataclass(frozen=True)
class EntityResult:
    """Per-entity bundle: completeness matrix + per-employee results + variance."""

    entity: str
    file: str
    completeness: CompletenessResult
    employees: Tuple[EmployeeResult, ...]
    variance: VarianceReport
    ingest_warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineResult:
    """Top-level result across all uploaded entities."""

    entities: Tuple[EntityResult, ...]
    variance: VarianceReport  # aggregate across every entity
    support_rate: float
    support_rate_is_final: bool
    claim_period: Tuple[date, date]
    errors: Tuple[str, ...] = ()

    # -- convenience rollups for the dashboard ----------------------------
    @property
    def all_employees(self) -> Tuple[EmployeeResult, ...]:
        return tuple(e for ent in self.entities for e in ent.employees)

    @property
    def total_claim_a(self) -> float:
        # ONLY qualifying staff are submitted to EDB, so the headline total sums
        # the qualifying claims (the EDB template writes qualifying rows only).
        # Non-qualifying people still carry a computed Method A figure, but it is
        # never claimed — including it here would overstate the claim.
        return round(sum(e.method_a.claim_amount for e in self.all_employees if e.qualifies), 2)

    @property
    def total_claim_b(self) -> float:
        return round(
            sum(e.method_b.claim_amount for e in self.all_employees
                if e.qualifies and e.method_b), 2
        )


# ---------------------------------------------------------------------------
# Per-employee assembly
# ---------------------------------------------------------------------------
def _hire_type(employee: Employee, staff_cost: Optional[StaffCostsRow]) -> HireType:
    """Resolve hire type, preferring the parsed Employee value."""
    if employee.hire_type is not None:
        return employee.hire_type
    return HireType.UPSKILLED  # neutral default; never forces the New-Hire quirk


def _synth_salary_from_staff_costs(
    employee: Employee,
    staff_cost: Optional[StaffCostsRow],
    months: Sequence[int],
    year: int,
) -> Dict[int, SalaryRecord]:
    """Build per-month SalaryRecords from the Staff Costs ``[A]`` actual salary.

    Timesheet-only mode has no payslip upload, so the internal workbook's own
    Staff Costs monthly salary is the salary source for the floor gate (G4) and
    Method A. The source_ref points at the real ``[A]`` cell, so a below-floor
    salary still reads as a substantive G4 exclusion (not an "unverifiable"
    blocker). Returns ``{}`` when there is no usable Staff Costs salary.
    """
    if staff_cost is None or staff_cost.actual_salary_a is None:
        return {}
    ref = next((r for r in staff_cost.source_refs if r.label == "actual_salary_a"), None)
    basic = float(staff_cost.actual_salary_a)
    return {
        m: SalaryRecord(
            employee_id=employee.id, year=year, month=m, basic_salary=basic,
            source_ref=ref,
            confidence_reason="Salary from Staff Costs [A] (no payslip uploaded)",
        )
        for m in months
    }


def _compute_one(
    employee: Employee,
    *,
    person_months: Sequence,
    rse: Optional[RseListRecord],
    staff_cost: Optional[StaffCostsRow],
    salaries: Tuple[SalaryRecord, ...],
    salary_by_month: Dict[int, SalaryRecord],
    rollup: Optional[EmployeeRollup],
    config: Config,
    timesheet_only: bool = False,
) -> EmployeeResult:
    year = config.claim_period_start.year

    # Timesheet-only: derive the salary from Staff Costs [A] so eligibility and
    # the claim compute from the internal workbook alone. The payslip document
    # gate (G7) becomes an informational flag, not a blocker — the document
    # checklist is tracked independently (per the HR workflow).
    flags: List[str] = []
    salary_by_month_eff = dict(salary_by_month)
    if timesheet_only and not salary_by_month_eff:
        months = sorted({pm.month for pm in person_months}) or list(range(1, 13))
        salary_by_month_eff = _synth_salary_from_staff_costs(
            employee, staff_cost, months, year
        )
        if salary_by_month_eff:
            flags.append(
                "Payslip not uploaded — salary taken from Staff Costs [A]; "
                "obtain the payslip before final EDB submission."
            )
        else:
            flags.append(
                "No salary found in Staff Costs [A] — the claim cannot be computed "
                "for this person from the timesheet alone."
            )

    # --- gates G1-G7 per person-month, then folded into one verdict --------
    evaluations: List[GateEvaluation] = []
    for pm in person_months:
        evaluations.extend(
            evaluate_person_month(
                employee,
                pm,
                rse=rse,
                salary=salary_by_month_eff.get(pm.month),
                staff_cost=staff_cost,
                config=config,
            )
        )
    # If there are no person-months at all (e.g. New Hire with zero hours),
    # still run the gates once so eligibility (G1-G5) is evaluated.
    if not person_months:
        from edb_claim.domain.models import PersonMonth

        probe = PersonMonth(employee_id=employee.id, year=year, month=1, basic_salary=0.0, hours=0.0)
        evaluations.extend(
            evaluate_person_month(
                employee, probe, rse=rse,
                salary=salary_by_month_eff.get(1), staff_cost=staff_cost, config=config,
            )
        )

    # Timesheet-only: G7 (payslip presence) is a document-tracker concern, not a
    # calc blocker, and completeness (which flags the absent payslip) must not
    # BLOCK the verdict. Drop G7 and evaluate the verdict on eligibility alone.
    if timesheet_only:
        verdict_evals = [ev for ev in evaluations if ev.gate is not GateCode.G7]
        verdict = compute_verdict(employee.id, verdict_evals, rollup=None)
    else:
        verdict = compute_verdict(employee.id, evaluations, rollup=rollup)

    # --- cross-checks (FR-3) — surfaced, never block on their own ----------
    monthly_hours = {pm.month: pm.hours for pm in person_months}
    warnings = tuple(
        run_crosschecks(
            employee,
            rse=rse,
            staff_cost=staff_cost,
            salaries=salaries,
            monthly_hours=monthly_hours,
            config=config,
        )
    )

    # --- Method A (EDB pro-ration; submission basis) -----------------------
    sal_map = {m: rec.basic_salary for m, rec in salary_by_month_eff.items()}
    period_start = staff_cost.date_join_c1 if staff_cost else None
    period_end = staff_cost.date_left_c2 if staff_cost else None
    # Flat fallback (timesheet-only) so a month without an explicit salary row
    # still prices from the Staff Costs [A] figure. Left None in the payroll path
    # so established results are byte-identical.
    flat_basic = (
        float(staff_cost.actual_salary_a)
        if timesheet_only and staff_cost and staff_cost.actual_salary_a is not None
        else None
    )
    method_a = compute_method_a_from_person_months(
        employee.id,
        person_months,
        year=year,
        salary_by_month=sal_map or None,
        basic_salary=flat_basic,
        period_start=period_start,
        period_end=period_end,
        config=config,
        hire_type=_hire_type(employee, staff_cost),
    )

    # --- Method B (internal Staff Costs replica; reconciliation only) ------
    method_b: Optional[MethodBResult] = None
    method_b_detail: Optional[MethodBDetail] = None
    if staff_cost and staff_cost.date_join_c1 and staff_cost.date_left_c2:
        basic = (
            staff_cost.actual_salary_a
            if staff_cost.actual_salary_a is not None
            else next(iter(sal_map.values()), 0.0)
        )
        project_hours = round(sum(pm.hours for pm in person_months), 2)
        method_b_detail = compute_method_b(
            MethodBInput(
                employee_id=employee.id,
                hire_type=_hire_type(employee, staff_cost),
                basic_salary=float(basic or 0.0),
                date_join=staff_cost.date_join_c1,
                date_left=staff_cost.date_left_c2,
                project_hours=project_hours,
            ),
            support_rate=config.support_rate,
        )
        method_b = method_b_detail.result

    # representative monthly basic salary (actual, uncapped) for EDB col D / SOE
    basics = [r.basic_salary for r in salary_by_month.values() if r.basic_salary]
    if basics:
        monthly_basic = max(set(basics), key=basics.count)  # modal value
    elif staff_cost and staff_cost.actual_salary_a is not None:
        monthly_basic = float(staff_cost.actual_salary_a)
    else:
        monthly_basic = None

    # involvement period for the claim = employment span ∩ claim window
    claim_start, claim_end = config.claim_period
    inv_from = max(period_start, claim_start) if period_start else claim_start
    inv_to = min(period_end, claim_end) if period_end else claim_end

    return EmployeeResult(
        employee=employee,
        verdict=verdict,
        rollup=rollup,
        method_a=method_a,
        method_b=method_b,
        method_b_detail=method_b_detail,
        gate_evaluations=tuple(evaluations),
        crosscheck_warnings=warnings,
        staff_cost=staff_cost,
        monthly_basic_salary=monthly_basic,
        involvement_from=inv_from,
        involvement_to=inv_to,
        flags=tuple(flags),
    )


# ---------------------------------------------------------------------------
# Per-entity assembly
# ---------------------------------------------------------------------------
def _run_entity(
    timesheet: IngestResult,
    *,
    rse_index: Dict[str, RseListRecord],
    salary_records: Tuple[SalaryRecord, ...],
    supporting: Optional[SupportingDocs],
    config: Config,
    timesheet_only: bool = False,
) -> EntityResult:
    year = config.claim_period_start.year

    salary_index = index_by_employee_month(salary_records)
    # Translate the supporting-evidence bundle into completeness kwargs, keeping
    # the no-bundle path byte-identical to the core POC (defaults preserved).
    sup = supporting or SupportingDocs()
    completeness = build_completeness(
        timesheet,
        salary_records,
        tuple(rse_index.values()),
        edb_template_present=(sup.edb_template if sup.edb_template is not None else True),
        leave_report_present=bool(sup.leave_report) if sup.leave_report is not None else False,
        cpf_bank_present_ids=() if sup.cpf_bank is False else None,
        entity_docs=sup.entity_docs(),
        person_docs=sup.person_docs(),
    )

    # group person-months and staff-cost rows by employee id. The Time Sheet
    # emits year=0 (the year is implied by the claim window); stamp the claim
    # year so the per-month gates (G6/G7) and Method A see a real calendar date.
    pm_by_emp: Dict[str, List] = {}
    for pm in timesheet.person_months:
        stamped = pm if getattr(pm, "year", 0) not in (0, None) else replace(pm, year=year)
        pm_by_emp.setdefault(stamped.employee_id, []).append(stamped)
    sc_by_emp = {sc.employee_id: sc for sc in timesheet.staff_costs if sc.employee_id}

    results: List[EmployeeResult] = []
    for emp in timesheet.employees:
        pms = pm_by_emp.get(emp.id, [])
        salaries = tuple(r for r in salary_records if r.employee_id == emp.id)
        salary_by_month = {
            m: salary_index[(emp.id, year, m)]
            for m in range(1, 13)
            if (emp.id, year, m) in salary_index
        }
        results.append(
            _compute_one(
                emp,
                person_months=pms,
                rse=rse_index.get(emp.id),
                staff_cost=sc_by_emp.get(emp.id),
                salaries=salaries,
                salary_by_month=salary_by_month,
                rollup=completeness.employee(emp.id),
                config=config,
                timesheet_only=timesheet_only,
            )
        )

    # variance over (A, B) pairs for employees that have both methods
    pairs = [(r.method_a, r.method_b) for r in results if r.method_b is not None]
    variance = compute_variance(pairs, config=config)

    return EntityResult(
        entity=timesheet.entity or "(unknown entity)",
        file=timesheet.file,
        completeness=completeness,
        employees=tuple(results),
        variance=variance,
        ingest_warnings=tuple(timesheet.warnings),
    )


# ---------------------------------------------------------------------------
# Friendly ingest-error reasoning (so the UI explains WHY a doc was rejected)
# ---------------------------------------------------------------------------
def explain_ingest_error(label: str, path: str, exc: Exception) -> str:
    """Turn a raw parse exception into a clear, actionable reason for HR.

    Classifies the failure (missing sheet, missing column, unreadable period,
    duplicate row, …) and states the expected format + fix, instead of surfacing
    a stack-trace string.
    """
    name = os.path.basename(path or "file")
    m = str(exc)
    low = m.lower()
    if "required sheet" in low or ("time sheet" in low and "staff costs" in low):
        why = "this timesheet workbook is missing required sheets"
        fix = ("It must contain two tabs — 'Time Sheet' (hours, from row 19) and "
               "'Staff Costs' (join/leave dates, from row 15). Reference: "
               "docs/demo/testkit/3_Team_Timesheet.xlsx.")
    elif "sheet" in low and "not found" in low:
        why = "we couldn't find a matching worksheet/tab"
        fix = ("Name the payroll tab 'Payroll' (also accepts 'Payslip' / 'Salary'), "
               "or upload a single-sheet workbook.")
    elif "basic-salary column" in low or "basic salary" in low:
        why = "no Basic Salary column was found"
        fix = ("Add a column headed 'Basic Salary' (or 'Salary'); extra columns "
               "like CPF / Bonus / Gross are ignored.")
    elif "employee id" in low and "infer" in low:
        why = "no Employee ID column, and it couldn't be read from the file name"
        fix = ("Add an 'Employee ID' column, or name single-payslip files like "
               "'payslip-E001-2026-01.xlsx'.")
    elif "year/month" in low or "period" in low:
        why = "the pay period (year & month) couldn't be determined"
        fix = ("Add 'Year' + 'Month' columns, or a 'Period' / 'Pay Date' column, or put "
               "the month in the file name (e.g. '…-2026-01.xlsx').")
    elif "duplicate" in low:
        why = "the same employee-month appears more than once"
        fix = "Keep one basic-salary figure per employee per month."
    elif "not a zip" in low or "badzip" in low or "openpyxl" in low:
        why = "this doesn't look like a valid .xlsx workbook"
        fix = "Export it as Excel (.xlsx), not .csv / .xls / a PDF."
    else:
        why = m
        fix = ""
    return f"{label} — “{name}”: {why}." + (f" {fix}" if fix else "")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_pipeline(
    internal_workbook_paths: Sequence[str],
    rse_list_path: Optional[str] = None,
    payroll_path=None,  # str | Sequence[str] | None — one or many payroll/payslip registers
    *,
    supporting: Optional[SupportingDocs] = None,
    config: Config = settings,
    timesheet_only: bool = False,
) -> PipelineResult:
    """Run the full deterministic pipeline over the uploaded documents.

    ``internal_workbook_paths`` — one internal HR workbook per entity.
    ``rse_list_path`` — the ECMF RSE list (authority for G1/G2); optional.
    ``payroll_path`` — the payroll/payslip register(s): a single path OR a list
        of paths. Multiple files are PARSED AND MERGED, so HR can upload one
        register per month/entity (or many individual payslip registers) and
        every employee-month row is picked up — not just the first file.
    ``supporting`` — presence of the wider HR evidence checklist (FR-2); optional.
    When omitted the result is identical to the three-document core POC.
    ``timesheet_only`` — when True, the claim is computed from the internal
        workbook ALONE: the salary comes from Staff Costs ``[A]``, eligibility
        runs on the Time Sheet's own citizenship/ECMF cells, and the payslip
        document gate (G7) is downgraded to an informational flag rather than a
        blocker (document tracking is handled independently). The figures remain
        fully deterministic; outputs stay non-final until the support rate and
        payslips are confirmed.

    Returns a :class:`PipelineResult`. Parse failures for an individual file are
    captured in ``errors`` rather than aborting the whole run, so the UI can show
    partial results plus what went wrong.
    """
    errors: List[str] = []

    rse_index: Dict[str, RseListRecord] = {}
    if rse_list_path:
        try:
            rse_index = dict(index_by_employee_id(parse_rse_list(rse_list_path)))
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the UI
            errors.append(explain_ingest_error("ECMF researcher list", rse_list_path, exc))

    # Accept a single payroll path or a list; parse each and merge the rows so
    # no payslip file is silently dropped (the "some payslips not accepted" case).
    payroll_paths = ([payroll_path] if isinstance(payroll_path, str)
                     else list(payroll_path or []))
    merged: List[SalaryRecord] = []
    for pp in payroll_paths:
        try:
            merged.extend(parse_payroll_register(pp))
        except Exception as exc:  # noqa: BLE001
            errors.append(explain_ingest_error("Payroll register", pp, exc))
    # De-duplicate to exactly ONE payslip per (employee, year, month): a person
    # has a single payslip per month, so if registers overlap we keep the first
    # occurrence rather than double-counting the salary.
    seen: set = set()
    deduped: List[SalaryRecord] = []
    for r in merged:
        key = (r.employee_id, r.year, r.month)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    salary_records: Tuple[SalaryRecord, ...] = tuple(deduped)

    entities: List[EntityResult] = []
    for path in internal_workbook_paths:
        try:
            ts = parse_internal_workbook(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(explain_ingest_error("Team timesheet", path, exc))
            continue
        entities.append(
            _run_entity(
                ts, rse_index=rse_index, salary_records=salary_records,
                supporting=supporting, config=config, timesheet_only=timesheet_only,
            )
        )

    # aggregate variance across every entity
    all_pairs = [
        (e.method_a, e.method_b)
        for ent in entities
        for e in ent.employees
        if e.method_b is not None
    ]
    aggregate_variance = compute_variance(all_pairs, config=config)

    return PipelineResult(
        entities=tuple(entities),
        variance=aggregate_variance,
        support_rate=config.support_rate,
        support_rate_is_final=config.support_rate_is_final,
        claim_period=config.claim_period,
        errors=tuple(errors),
    )
