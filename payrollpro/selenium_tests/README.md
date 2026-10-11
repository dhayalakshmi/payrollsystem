# PayrollPro Selenium tests (Google Chrome) - 25 test cases

    pip install -r selenium_tests/requirements.txt
    python selenium_tests/run_all_tests.py          # all 25 cases
    python selenium_tests/test_payslip.py           # one module only

Needs Google Chrome installed (Selenium downloads the matching driver itself).
The runner starts PayrollPro on a fresh temporary database automatically; if the app is
already running on port 8000 it uses that one instead.

Options: `HEADLESS=1` (no window), `STEP_DELAY=0` (no pauses), `BASE_URL=http://host:port`.

| Module | Cases | Positive | Negative |
|---|---|---|---|
| Login (TC-01..04) | 4 | page loads, admin login | wrong password, empty form |
| Registration & profile (TC-05..11) | 7 | page loads, register, save profile | weak password, mismatch, duplicate email, bad mobile |
| Employee (TC-12..15) | 4 | list + search, update salary | no search match, employee gets 403 |
| Attendance (TC-16..18) | 3 | check in, check out, admin approves | - |
| Leave (TC-19..21) | 3 | apply, admin approves | end date before start date |
| Payroll (TC-22..23) | 2 | generate payroll, CSV export | - |
| Payslip (TC-24..25) | 2 | correct amounts + masked bank | other employee's payslip (403) |
