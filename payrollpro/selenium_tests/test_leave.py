"""LEAVE MODULE  (3 test cases: 2 positive, 1 negative)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium_tests import config as c


def _apply(driver, leave_type, start, end, reason):
    c.open_page(driver, "/leave")
    Select(driver.find_element(By.NAME, "type")).select_by_visible_text(leave_type)
    c.fill(driver, "start", start)
    c.fill(driver, "end", end)
    c.fill(driver, "reason", reason)
    c.submit(driver)


def _status(driver, reason):
    return driver.find_element(By.XPATH, f"//tr[td[normalize-space()='{reason}']]//span[contains(@class,'b')]").text.lower()


def run(driver):
    t = c.Tester("LEAVE MODULE")
    c.ensure_test_employee(driver)
    reason = f"Selenium casual leave {int(time.time())}"

    def invalid_range():  # TC-19 negative
        c.login_employee(driver)
        _apply(driver, "Casual", c.future(12), c.future(10), "Invalid range")
        c.assert_text(driver, "Choose a valid date range.")
    t.case("Error 'Choose a valid date range.' when the end date is before the start date",
           "Date range validation message displayed", invalid_range)

    def apply_ok():  # TC-20 positive
        _apply(driver, "Casual", c.future(10), c.future(11), reason)
        c.assert_text(driver, "Leave request submitted.")
        assert _status(driver, reason) == "pending", "New leave request is not pending"
    t.case("Employee should submit a leave request with status pending",
           "Leave request submitted successfully", apply_ok)

    def admin_approves():  # TC-21 positive
        c.login_admin(driver)
        c.open_page(driver, "/leave")
        driver.find_element(By.XPATH, f"//tr[td[normalize-space()='{reason}']]//button[@value='approved']").click()
        c.assert_text(driver, "Request approved.")
        assert _status(driver, reason) == "approved", "Leave status is not approved"
    t.case("Admin should approve the leave request", "Leave approved successfully", admin_approves)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
