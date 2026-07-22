"""Generate a clean, numbered TEST KIT in the exact format the system expects.

Upload these (in number order) to exercise the whole workflow without format
errors. Reuses the shipped synthetic-data writers so the sheet names / columns
match the parser contract:
  - Internal workbook: sheets 'Time Sheet' (row 19+) and 'Staff Costs' (row 15+)
  - Payroll register : sheet 'Payroll', header row 1 (Employee ID, Name, Year,
                       Month, Basic Salary, … )
  - ECMF list        : sheet 'RSE List' (Employee ID, Name, Citizenship, ECMF)
"""
import os
import sys
import shutil
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sample_data"))
import generate as g
from openpyxl import Workbook
from edb_claim.app.pipeline import run_pipeline

OUT = os.path.dirname(os.path.abspath(__file__))
ENTITY = "ST Engineering Digital Systems Pte Ltd"
FULL = g.FULL


def P(**kw):
    return g.Person(entity=ENTITY, no_other_grant=True, **kw)


roster = [
    P(employee_id="E001", ts_name="Aaron Tan", case_label="standard", citizenship="Citizen",
      ecmf_validated=True, designation="AI Research Engineer", hire_type="Upskilled",
      date_join=FULL[0], date_left=FULL[1], basic_salary=9000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="QUALIFIES"),
    P(employee_id="E002", ts_name="Bella Ng", case_label="salary_above_cap", citizenship="Citizen",
      ecmf_validated=True, designation="Principal AI Scientist", hire_type="New Hire",
      date_join=FULL[0], date_left=FULL[1], basic_salary=24000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="QUALIFIES"),
    P(employee_id="E003", ts_name="Chandra Rao", case_label="mid_period_joiner", citizenship="PR",
      ecmf_validated=True, designation="Data Scientist", hire_type="Upskilled",
      date_join=date(2026, 3, 10), date_left=FULL[1], basic_salary=8000.0,
      hours=g._full_time_hours(date(2026, 3, 10), FULL[1]), expected_verdict="QUALIFIES"),
    P(employee_id="E004", ts_name="Daniel Kim", case_label="foreigner_excluded", citizenship="Foreigner",
      ecmf_validated=False, designation="AI Engineer", hire_type="New Hire",
      date_join=FULL[0], date_left=FULL[1], basic_salary=11000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), expected_verdict="EXCLUDED"),
    P(employee_id="E005", ts_name="Emma Lim", case_label="missing_payslip", citizenship="Citizen",
      ecmf_validated=True, designation="ML Engineer", hire_type="Upskilled",
      date_join=FULL[0], date_left=FULL[1], basic_salary=10000.0,
      hours=g._full_time_hours(FULL[0], FULL[1]), omit_payroll_months=(5,),
      expected_verdict="BLOCKED"),
]

# 1) EDB output template — copy the shipped blank v1.1 export
shutil.copy(os.path.join(ROOT, "docs", "EDB_Output Template.xlsx"),
            os.path.join(OUT, "1_EDB_Output_Template.xlsx"))
# 2) trainee list — simple roster with training dates (presence-checked)
tw = Workbook(); ws = tw.active; ws.title = "Trainees"
ws.append(["Employee ID", "Name", "Training Start", "Training End"])
for p in roster:
    ws.append([p.employee_id, p.ts_name, p.date_join.isoformat(), p.date_left.isoformat()])
tw.save(os.path.join(OUT, "2_Trainee_List.xlsx"))
# 3) team timesheet (Time Sheet + Staff Costs) ; 4) ECMF list ; 5) payroll register
g._write_internal_workbook(ENTITY, roster, os.path.join(OUT, "3_Team_Timesheet.xlsx"))
g._write_rse_list(roster, os.path.join(OUT, "4_ECMF_Researcher_List.xlsx"))
g._write_payroll(roster, os.path.join(OUT, "5_Payroll_Register.xlsx"))
print("Test kit written to docs/demo/testkit/ (5 numbered files)")

# verify the whole pipeline runs cleanly on the kit
res = run_pipeline(
    [os.path.join(OUT, "3_Team_Timesheet.xlsx")],
    os.path.join(OUT, "4_ECMF_Researcher_List.xlsx"),
    [os.path.join(OUT, "5_Payroll_Register.xlsx")],
)
ent = res.entities[0]
print(f"\nParsed OK · errors: {len(res.errors)}")
for e in ent.employees:
    print(f"  {e.employee.id:<6} {e.employee.name:<14} {e.verdict.status.value:<10} ${e.method_a.claim_amount:,.2f}")
print(f"\nQualify: {sum(1 for e in ent.employees if e.qualifies)}/{len(roster)} · "
      f"Total claim ${res.total_claim_a:,.2f}")
print("RESULT:", "CLEAN — no read errors ✅" if not res.errors else f"ERRORS: {res.errors}")

# Also emit INDIVIDUAL payslip files (one per employee-month) in the loose format
# the parser now understands: a 'Payslip' sheet, only a Basic Salary column, and
# the employee id + period inferred from the FILE NAME. These merge just like a
# register — proving the "some payslips not accepted" case now works.
pdir = os.path.join(OUT, "payslips")
os.makedirs(pdir, exist_ok=True)
for old in os.listdir(pdir):
    os.remove(os.path.join(pdir, old))
payslip_paths = []
for p in roster:
    # only the claim window (Jan-Jun 2026), within the person's involvement
    for m in range(max(p.date_join.month, 1), min(p.date_left.month, 6) + 1):
        if m in p.omit_payroll_months:
            continue
        w = Workbook(); s = w.active; s.title = "Payslip"
        s.append(["Employee Name", "Basic Salary", "CPF", "Allowances"])  # CPF/Allowances ignored
        s.append([p.ts_name, p.basic_salary, round(p.basic_salary * 0.17, 2), 500])
        fp = os.path.join(pdir, f"payslip-{p.employee_id}-2026-{m:02d}.xlsx")
        w.save(fp); payslip_paths.append(fp)

res2 = run_pipeline([os.path.join(OUT, "3_Team_Timesheet.xlsx")],
                    os.path.join(OUT, "4_ECMF_Researcher_List.xlsx"), payslip_paths)
same = abs(res.total_claim_a - res2.total_claim_a) < 0.005 and not res2.errors
print(f"\n{len(payslip_paths)} individual payslip files in testkit/payslips/")
print(f"Individual-payslips merge == register: ${res2.total_claim_a:,.2f} "
      f"(errors {len(res2.errors)}) -> {'OK ✅' if same else 'MISMATCH ❌'}")
