"""Runs all 25 PayrollPro Selenium test cases in Google Chrome.

    cd payrollpro
    pip install -r selenium_tests/requirements.txt
    python selenium_tests/run_all_tests.py

Options (environment variables):
    HEADLESS=1      run Chrome without a window
    STEP_DELAY=0    no pause between steps (default 0.4 s so you can watch)
    BASE_URL=...    test an app that is already running (default http://127.0.0.1:8000)
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from selenium_tests import config as c
from selenium_tests import (test_login, test_registration, test_employee, test_attendance,
                            test_leave, test_payroll, test_payslip)

MODULES = [test_login, test_registration, test_employee, test_attendance,
           test_leave, test_payroll, test_payslip]


def main():
    stop = c.start_server()
    driver = c.get_driver()
    try:
        for m in MODULES:
            m.run(driver)
    finally:
        driver.quit()
        stop()
    return 0 if c.summary() else 1


if __name__ == "__main__":
    sys.exit(main())
