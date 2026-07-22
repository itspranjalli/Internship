# Test kit — ready-to-upload documents

Upload these in number order on the landing page to run the whole workflow with **no format errors**.
(Regenerate any time with `python docs/demo/testkit/make_testkit.py`.)

| # | File | Type | What it exercises |
|---|------|------|-------------------|
| 1 | `1_EDB_Output_Template.xlsx` | EDB output template | The export format; the system fills *this* template for the submission |
| 2 | `2_Trainee_List.xlsx` | Trainee list | The roster (presence-checked) |
| 3 | `3_Team_Timesheet.xlsx` | Team timesheet | Roster + monthly hours (sheets **Time Sheet** + **Staff Costs**) |
| 4 | `4_ECMF_Researcher_List.xlsx` | ECMF list | Citizenship + ECMF validation |
| 5 | `5_Payroll_Register.xlsx` | Payroll register | Basic monthly salary per employee-month (sheet **Payroll**) |

Expected result: **3 of 5 qualify** · total **$122,290.91** · Aaron/Bella/Chandra qualify, **Daniel excluded** (foreigner), **Emma blocked** (missing May payslip).

## Why your earlier files failed (format contract)

The parsers expect specific **sheet names and columns**:

- **Payroll register** — one workbook (a *register*, not one file per payslip), sheet named `Payroll`
  (also accepts `Payslip`/`Salary`, or a single-sheet workbook), header on row 1 with columns:
  `Employee ID`, `Name`, `Year`, `Month`, `Basic Salary` (extra columns like CPF/Bonus/AWS are ignored).
  → Your `payslip-E001-2024-01.xlsx` files had a `Payslip` sheet (now tolerated) but were one-payslip-per-file;
  put all employee-months as **rows in one register**, or upload several registers (they're merged).

- **Team timesheet** — needs **two** sheets: `Time Sheet` (data from row 19) and `Staff Costs` (data from row 15).
  → Your `employee_timesheet.xlsx` had a single `Timesheet` sheet and no `Staff Costs`, so it couldn't be read.
  Use `3_Team_Timesheet.xlsx` as the layout reference.

Inspect any kit file in Excel to see the exact layout to match for real data.

## The parser is now flexible (intelligent ingest)

You don't have to match the headers exactly anymore — the payroll parser handles:

- **Synonym headers** — `Emp No` / `Staff ID` (employee id), `Salary` / `Basic Pay` / `Base Salary`
  (basic salary), `Name`. Extra columns (CPF, Bonus, AWS, Gross, Net…) are ignored.
- **Sheet names** — `Payroll`, `Payslip`, `Salary`, or a single-sheet workbook.
- **Period in one column** — a `Period` / `Pay Date` / `Pay Month` column holding a real date,
  `2024-01`, or `Jan 2024`.
- **One payslip per file** — a file with just a Basic-Salary value and **no id/period columns**:
  the employee id and month are read from the **file name**, e.g. `payslip-E001-2026-01.xlsx`.
  Upload many at once — they're merged (and de-duplicated to one payslip per employee-month).

See `payslips/` for 27 example single-payslip files in this loose format — uploading them all
produces the **same** result as the single register (`$122,290.91`).

> Note: the **team timesheet** still needs its two sheets (`Time Sheet` + `Staff Costs`) — that
> structure carries the roster, hours and join/leave dates, so it can't be inferred from a flat list.

