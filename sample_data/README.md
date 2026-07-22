# Synthetic test data (PLAN.md T14 / PRD §8)

Deterministic fixtures for the EDB RIS(C) grant POC, targeting the **Q7 claim
window 2026-01-01 → 2026-06-30** (PRD §10 Q7). Regenerate with:

```bash
.venv/bin/python sample_data/generate.py          # write the fixtures
.venv/bin/python sample_data/generate.py --check   # write + verify T2/T3 ingest
```

The generator (`generate.py`) constructs the roster **literally** (no randomness,
no `datetime.now()`), so re-running produces value-identical data every time
(PRD §9). `--check` re-parses through the real T2/T3 ingest and confirms 0 errors
and the expected counts.

## Files

| File | Schema (parser) | Contents |
|---|---|---|
| `internal_ANS.xlsx` | T2 `ingest/timesheet.py` | Entity A internal workbook (Time Sheet row 19+, Staff Costs row 15+) |
| `internal_DSG.xlsx` | T2 `ingest/timesheet.py` | Entity B internal workbook |
| `rse_list.xlsx` | T3 `ingest/rse_list.py` | ECMF `RSE List`, all 20 employees |
| `payroll.xlsx` | T3 `ingest/salary.py` | `Payroll` long-format register (+ CPF/bonus/AWS/allowance/gross noise) |
| `expectations.json` | — | Ground-truth oracle (verdicts, failed gates, Method A hand-calc to the cent) |

Two participating entities (PRD §8: 2–3), ~10 employees each (20 total):
- **Entity A** = `ST Engineering Advanced Networks & Sensors Pte Ltd` (IDs `ANS-0xx`) — calc-heavy / happy-path cases.
- **Entity B** = `ST Engineering Digital System Pte Ltd` (IDs `DSG-0xx`) — exclusion / blocker / reconciliation cases.

## Case → employee map (all 13 PRD §8 cases)

| PRD §8 case | Employee | Verdict | Gate |
|---|---|---|---|
| Standard full-period RSE | `ANS-001` Lim Jia Hao (salary 9,500) | QUALIFIES | — |
| Mid-period **joiner** (partial-month pro-ration) | `ANS-002` Nurul Aisyah (joins 2026-03-12) | QUALIFIES | — |
| Mid-period **leaver** | `ANS-003` Tan Wei Ming (leaves 2026-05-15) | QUALIFIES | — |
| **Name variant** across docs (FR-11) | `ANS-003` — TS `Tan Wei Ming` / RSE `WEI MING TAN` / payroll `Tan, Wei Ming` | QUALIFIES | — |
| Salary **S$23,000** (cap clamp) | `ANS-004` Rajesh Kumar Pillai | QUALIFIES | — |
| **New Hire, no timesheet hours** (A vs B divergence) | `ANS-005` Chua Mei Ling | QUALIFIES | — |
| Hours **> monthly capacity** (cap warning) | `ANS-006` Goh Boon Keng (April over capacity) | QUALIFIES | — |
| **Ambiguous designation** (FR-10 → HR review) | `ANS-007` "Engineering Operations Manager" | QUALIFIES | — |
| Salary **S$4,800** (G4 floor) | `DSG-001` Faridah Binte Omar | EXCLUDED | G4 |
| **Foreigner** (G1) | `DSG-002` Arjun Mehta | EXCLUDED | G1 |
| **Not ECMF-validated** (G2) | `DSG-003` Wong Kah Wai | EXCLUDED | G2 |
| **Other government grant** (G3) | `DSG-004` Priya Nair | EXCLUDED | G3 |
| Designation **"HR Manager"** (G5) | `DSG-005` Kelvin Ong | EXCLUDED | G5 |
| **Missing payslip** one month (G7 blocker) | `DSG-006` Siti Nurhaliza (April absent) | BLOCKED | G7 |

`ANS-008..010` and `DSG-007..010` are plain qualifying RSEs that fill each
entity's roster to ~10. The mid-period leaver and the name-variant case are the
same employee (`ANS-003`), so 13 distinct cases ride on 13 distinct rows.

## Method A hand-calc oracle (to the cent — PRD §11.3)

`expectations.json` carries a full Method A breakdown for **5 qualifying
employees** (`ANS-001..005`, incl. the partial-month joiner). Formula (PRD §6):

```
qualifying_cost = Σ_months  capped_salary × month_fraction(m) × time_contribution(m)
time_contribution(m) = min(1, hours(m) / (weekdays(m) × 8.8))
claim_amount = round(qualifying_cost × support_rate, 2)     # round ONLY the final claim
support_rate = 0.30 (ASSUMED, non-final — PRD §10 Q2)
```

computed with `domain/calendar_utils.month_fraction` / `weekdays_in_month`.

**Worked example — the partial-month joiner `ANS-002`** (salary 8,000 < cap,
joins 2026-03-12, full-time Mar–Jun):

| Month | weekdays | hours | month_fraction | time_contrib | qualifying_cost |
|---|---|---|---|---|---|
| Mar | 22 | 193.6 | 14/22 = 0.636364 | 1.0 | 8000 × 0.636364 = **5,090.909091** |
| Apr | 22 | 193.6 | 1.0 | 1.0 | 8,000.000000 |
| May | 21 | 184.8 | 1.0 | 1.0 | 8,000.000000 |
| Jun | 22 | 193.6 | 1.0 | 1.0 | 8,000.000000 |

```
qualifying_cost = 5,090.909091 + 8,000 + 8,000 + 8,000 = 29,090.909091
claim_amount    = round(29,090.909091 × 0.30, 2) = 8,727.27
```

(March: weekdays 12–31 = 14 of 22 → fraction 14/22; no full month is pre-rounded.)

Other oracle amounts: `ANS-001` = **17,100.00** (9,500 full-time × 6 mo × 0.30);
`ANS-003` leaver = **9,500.00** (May 11/21 partial); `ANS-004` capped 20,000 =
**36,000.00**; `ANS-005` New Hire with no hours = **0.00** (Method A needs hours;
Method B forces it to 100%, the variance New-Hire flag).

## Note on the Staff Costs derived columns

In the real workbook the Staff Costs `[B]/[D1]/[D2]/[D3]/[E]` columns are Excel
formulas. openpyxl cannot store a cached formula result and T2 opens the file
`data_only=True`, so a written formula would read back as `None`. Therefore the
generator writes the **literal computed values** into those cells, faithfully
applying the documented formulas **including the quirks** (New-Hire `[D3]=100%`
with `[D2]="N/A"`; `[B]` labelled "annual" but yielding a monthly capped figure;
`[D1] = NETWORKDAYS(join,left)×8.8` over the *full* employment span). These are
replicated as-is for Method B (T7) to reconcile — never "fixed".

## Schema notes / assumptions (T2/T3 ambiguities)

- **Citizenship spelling**: written as `Citizen` / `PR` / `Foreigner` — exactly
  the `Citizenship` enum values, which both the timesheet heuristic and the RSE
  list synonym table accept.
- **Booleans**: Time Sheet ECMF (col H) and no-other-grant (col I) are real
  Python booleans; RSE-list ECMF (col D) is the string `TRUE`/`FALSE`.
- **G3 polarity**: Time Sheet col I = "Confirm **not** enjoying any other grant",
  so `TRUE` = compliant. The other-grant case (`DSG-004`) sets it `FALSE`.
- **Staff Costs ↔ Time Sheet join**: we write a literal Employee ID into Staff
  Costs col C, so T2 resolves every row by `cross_ref_employee_id` (the row-offset
  +4 fallback is also structurally honoured — Staff Costs row N ↔ Time Sheet N+4).
- **New-Hire person-months**: `ANS-005` has no monthly hours, so T2 emits **no**
  `PersonMonth` rows for it (a month is only emitted when it carries a value);
  entity A therefore has 51 person-months across 10 employees.
