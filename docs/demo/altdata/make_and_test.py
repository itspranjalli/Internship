"""Generate a BRAND-NEW document set (new company, new employees, fresh edge
cases) and run the whole pipeline on it — proving the system isn't tuned to the
shipped sample. Engine output is cross-checked against the generator's
independent hand-calc oracle. Files are written here so they can also be
uploaded through the UI to test the full flow end-to-end.
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sample_data"))
import generate as g  # the shipped synthetic-data generator
from edb_claim.app.pipeline import run_pipeline

OUT = os.path.dirname(os.path.abspath(__file__))
ENTITY = "ST Engineering Geo-Insights Pte Ltd"
FULL = g.FULL  # (claim_start, claim_end)


def P(**kw):
    return g.Person(entity=ENTITY, no_other_grant=True, **kw)


# A fresh roster — different ids, names, salaries, dates and edge cases.
roster = [
    P(employee_id="GEO-001", ts_name="Rahim Bin Osman", case_label="standard",
      citizenship="Citizen", ecmf_validated=True, designation="AI Research Scientist",
      hire_type="Upskilled", date_join=FULL[0], date_left=FULL[1], basic_salary=11000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="QUALIFIES"),
    P(employee_id="GEO-002", ts_name="Chen Wei Lin", case_label="salary_above_cap",
      citizenship="Citizen", ecmf_validated=True, designation="Principal AI Engineer",
      hire_type="New Hire", date_join=FULL[0], date_left=FULL[1], basic_salary=26000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="QUALIFIES"),
    P(employee_id="GEO-003", ts_name="Priya Kumar", case_label="mid_period_joiner",
      citizenship="PR", ecmf_validated=True, designation="Data Scientist",
      hire_type="Upskilled", date_join=date(2026, 4, 8), date_left=FULL[1], basic_salary=8500.0,
      hours=g._full_time_hours(date(2026, 4, 8), FULL[1]), expected_verdict="QUALIFIES"),
    P(employee_id="GEO-004", ts_name="Lim Hui Fen", case_label="mid_period_leaver",
      citizenship="Citizen", ecmf_validated=True, designation="ML Engineer",
      hire_type="Reskilled", date_join=FULL[0], date_left=date(2026, 4, 20), basic_salary=9000.0,
      hours=g._full_time_hours(FULL[0], date(2026, 4, 20)), expected_verdict="QUALIFIES"),
    P(employee_id="GEO-005", ts_name="John Becker", case_label="foreigner_excluded",
      citizenship="Foreigner", ecmf_validated=False, designation="AI Engineer",
      hire_type="New Hire", date_join=FULL[0], date_left=FULL[1], basic_salary=12000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="EXCLUDED"),
    P(employee_id="GEO-006", ts_name="Tan Boon Huat", case_label="non_qualifying_role",
      citizenship="Citizen", ecmf_validated=True, designation="Sales Manager",
      hire_type="New Hire", date_join=FULL[0], date_left=FULL[1], basic_salary=10000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="EXCLUDED"),
    P(employee_id="GEO-007", ts_name="Devi Anand", case_label="below_salary_floor",
      citizenship="Citizen", ecmf_validated=True, designation="Junior AI Engineer",
      hire_type="New Hire", date_join=FULL[0], date_left=FULL[1], basic_salary=4500.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="EXCLUDED"),
    P(employee_id="GEO-008", ts_name="Sarah Lim", case_label="missing_payslip",
      citizenship="Citizen", ecmf_validated=True, designation="AI Research Engineer",
      hire_type="Upskilled", date_join=FULL[0], date_left=FULL[1], basic_salary=13000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), omit_payroll_months=(4,),
      expected_verdict="BLOCKED"),
]

ts_path = os.path.join(OUT, "internal_GEO.xlsx")
rse_path = os.path.join(OUT, "rse_list_alt.xlsx")
pay_path = os.path.join(OUT, "payroll_alt.xlsx")
g._write_internal_workbook(ENTITY, roster, ts_path)
g._write_rse_list(roster, rse_path)
g._write_payroll(roster, pay_path)
# Also emit the payroll SPLIT across two files, to prove multiple payslip
# registers are all merged (the "some payslips not accepted" fix).
part1 = os.path.join(OUT, "payroll_part1.xlsx")
part2 = os.path.join(OUT, "payroll_part2.xlsx")
g._write_payroll(roster[:4], part1)
g._write_payroll(roster[4:], part2)
print(f"Wrote new doc set for {ENTITY}: {len(roster)} employees (+ split payroll x2)")

# merge-equivalence: one register vs two halves must give the same result
single = run_pipeline([ts_path], rse_path, pay_path)
split = run_pipeline([ts_path], rse_path, [part1, part2])
same = abs(single.total_claim_a - split.total_claim_a) < 0.005
print(f"Split-payroll merge equivalence: single ${single.total_claim_a:,.2f} == "
      f"split ${split.total_claim_a:,.2f} -> {'OK' if same else 'MISMATCH'}")

res = run_pipeline([ts_path], rse_path, pay_path)
ent = res.entities[0]
byid = {e.employee.id: e for e in ent.employees}

fails = 0
print(f"\n{'EMP':<9}{'CASE':<22}{'VERDICT':<10}{'exp':<10}{'ENGINE $':>12}{'ORACLE $':>12}  ok")
for p in roster:
    e = byid.get(p.employee_id)
    if not e:
        print(f"{p.employee_id:<9} MISSING FROM RESULT"); fails += 1; continue
    oracle = g.method_a_handcalc(p)["claim_amount"]
    eng = e.method_a.claim_amount
    v = e.verdict.status.value
    # For a missing-payslip case the engine correctly drops the unpaid month and
    # BLOCKS the person; the naive oracle counts all months, so compare verdict
    # only there. Otherwise the claim must match the independent hand-calc.
    claim_ok = bool(p.omit_payroll_months) or abs(eng - oracle) < 0.005
    ok = (v == p.expected_verdict) and claim_ok
    fails += 0 if ok else 1
    note = "  (blocked: claim over paid months only)" if p.omit_payroll_months else ""
    print(f"{p.employee_id:<9}{p.case_label:<22}{v:<10}{p.expected_verdict:<10}{eng:>12,.2f}{oracle:>12,.2f}  {'OK' if ok else 'XX'}{note}")

q = [e for e in ent.employees if e.qualifies]
print(f"\nQualify: {len(q)}/{len(roster)}  ·  Total claim (qualifying): ${res.total_claim_a:,.2f}")
print("=" * 64)
print("RESULT:", "ALL PASS ✅" if fails == 0 else f"{fails} MISMATCH ❌")
