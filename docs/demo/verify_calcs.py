"""Stress-test every Method A claim figure for demo confidence.

Independently re-derives each employee's claim from the per-month components and
cross-checks against (a) the engine, (b) the synthetic oracle (expectations.json),
and (c) hand-calc edge cases. Prints PASS/FAIL per check. No asserts swallowed —
any mismatch is printed loudly.
"""
import json
import os
from dataclasses import replace
from datetime import date

from edb_claim.config import settings
from edb_claim.app.pipeline import run_pipeline
from edb_claim.calc.method_a import ClaimableMonth, compute_method_a
from edb_claim.domain.models import HireType

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SD = os.path.join(ROOT, "sample_data")
oracle = {e["employee_id"]: e for e in json.load(open(os.path.join(SD, "expectations.json")))["employees"]}

fails = []
def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)

CORE = ([os.path.join(SD, "internal_ANS.xlsx"), os.path.join(SD, "internal_DSG.xlsx")],
        os.path.join(SD, "rse_list.xlsx"), os.path.join(SD, "payroll.xlsx"))

print("\n=== 1. Determinism (same inputs -> identical outputs) ===")
r1 = run_pipeline(*CORE); r2 = run_pipeline(*CORE)
check("two runs identical total", r1.total_claim_a == r2.total_claim_a, f"{r1.total_claim_a} vs {r2.total_claim_a}")
check("two runs identical per-employee", all(a.claim_amount == b.claim_amount
      for a, b in zip(r1.all_employees, r2.all_employees)))

print("\n=== 2. Support rate & config ===")
check("support rate is 60%", settings.support_rate == 0.60, str(settings.support_rate))
check("salary cap 20000", settings.salary_cap == 20000)
check("salary floor 5000", settings.salary_floor == 5000)
check("upskill cap 9 months", settings.upskill_max_months == 9)

print("\n=== 3. EDB published worked example (reconciles at their 30%) ===")
hpd = settings.hours_per_day
ex_months = [ClaimableMonth(2018, 1, 9500.0, 23 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
             ClaimableMonth(2018, 2, 9500.0, 20 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
             ClaimableMonth(2018, 3, 9500.0, 22 * hpd, date(2018, 1, 15), date(2018, 3, 31))]
ex = compute_method_a("EX", ex_months, config=replace(settings, support_rate=0.30))
check("EDB example = $7,310.87", ex.claim_amount == 7310.87, str(ex.claim_amount))

print("\n=== 4. Per-employee: engine vs oracle vs independent re-derivation ===")
print(f"  {'EMP':<9}{'ENGINE':>12}{'ORACLE':>12}{'RE-DERIVED':>12}  match")
for e in r1.all_employees:
    eid = e.employee.id
    eng = e.method_a.claim_amount
    # independent re-derivation from the per-month components (cap & clamp re-checked)
    redet = 0.0
    caps_ok = clamps_ok = True
    for m in e.method_a.monthly:
        if m.capped_salary > settings.salary_cap + 1e-9:
            caps_ok = False
        if m.time_contribution > 1 + 1e-9 or m.month_fraction > 1 + 1e-9:
            clamps_ok = False
        redet += m.capped_salary * m.month_fraction * m.time_contribution
    redet = round(redet * settings.support_rate, 2)
    orc = oracle.get(eid, {}).get("method_a", {}).get("claim_amount")
    match = (eng == redet) and (orc is None or abs(eng - orc) < 0.005)
    if e.qualifies or (orc not in (None, 0.0)):
        print(f"  {eid:<9}{eng:>12,.2f}{(orc if orc is not None else float('nan')):>12,.2f}{redet:>12,.2f}  {'OK' if match else 'XX'}")
    check(f"{eid} engine==re-derived", eng == redet, f"{eng} vs {redet}")
    check(f"{eid} caps<=20k & clamps<=1", caps_ok and clamps_ok)
    if orc is not None:
        check(f"{eid} engine==oracle", abs(eng - (orc or 0)) < 0.005, f"{eng} vs {orc}")

print("\n=== 5. Edge cases (hand-calc) ===")
byid = {e.employee.id: e for e in r1.all_employees}
# salary cap: ANS-004 basic 23,000 -> capped 20,000 every month
a4 = byid.get("ANS-004")
if a4:
    check("ANS-004 capped to 20,000 every month", all(m.capped_salary == 20000.0 for m in a4.method_a.monthly))
# new hire, zero hours -> claim 0
a5 = byid.get("ANS-005")
if a5:
    check("ANS-005 New-Hire-no-hours -> claim 0", a5.method_a.claim_amount == 0.0)
# joiner partial month (ANS-002 March 14/22)
a2 = byid.get("ANS-002")
if a2:
    m = a2.method_a.monthly[0]
    check("ANS-002 joiner month fraction 14/22", abs(m.month_fraction - 14/22) < 1e-9, str(m.month_fraction))
# total reconciles to the sum of qualifying claims
q_sum = round(sum(e.method_a.claim_amount for e in r1.all_employees if e.qualifies), 2)
check("total == sum of qualifying claims", r1.total_claim_a == q_sum, f"{r1.total_claim_a} vs {q_sum}")

print("\n=== 6. Upskill 9-month cap (synthetic, since POC window is 6 months) ===")
twelve = [ClaimableMonth(2026, k + 1, 10000.0, 31 * hpd) for k in range(12)]
up = compute_method_a("UP", twelve, hire_type=HireType.UPSKILLED)
nh = compute_method_a("NH", twelve, hire_type=HireType.NEW_HIRE)
check("upskilled capped to 9 months", len(up.monthly) == 9 and up.months_capped == 3)
check("upskilled claim = 9*10000*0.6 = 54,000", up.claim_amount == 54000.00, str(up.claim_amount))
check("new hire uncapped (12 months)", len(nh.monthly) == 12 and nh.months_capped == 0)
check("new hire claim = 12*10000*0.6 = 72,000", nh.claim_amount == 72000.00, str(nh.claim_amount))

print("\n=== 7. Method A vs B cross-check (variance) ===")
for e in r1.all_employees:
    if e.method_b is not None and e.qualifies:
        a, b = e.method_a.claim_amount, e.method_b.claim_amount
        # cross-check flag must be consistent with the actual divergence
        diverge = (abs(a - b) / a * 100 > 1.0) if a else (b != 0)
        nh_flag = e.method_b.new_hire and b > a
        check(f"{e.employee.id} crosscheck_ok consistent",
              e.crosscheck_ok == (not diverge and not nh_flag))

print("\n" + "=" * 60)
print(f"RESULT: {'ALL CHECKS PASSED ✅' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
print("=" * 60)
