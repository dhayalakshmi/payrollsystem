"""ATTENDANCE MODULE  (3 test cases: 3 positive)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from selenium.webdriver.common.by import By
from selenium_tests import config as c


def _row(name):
    return f"//tr[td[normalize-space()='{name}'] and td[normalize-space()='{date.today().isoformat()}']]"


def run(driver):
    t = c.Tester("ATTENDANCE MODULE")
    c.ensure_test_employee(driver)

    def check_in():  # TC-16 positive
        c.login_employee(driver)
        c.open_page(driver, "/attendance")
        c.assert_text(driver, "My Attendance")
        driver.find_element(By.XPATH, "//button[normalize-space()='Check in']").click()
        c.assert_text(driver, "Checked in. Awaiting admin approval.")
        status = driver.find_element(By.XPATH, f"//tr[td[normalize-space()='{date.today().isoformat()}']]//span[contains(@class,'b')]").text
        assert status.lower() == "pending", f"Expected status pending but found '{status}'"
    t.case("Employee should check in and today's record should be pending",
           "Checked in successfully (pending approval)", check_in)

    def check_out():  # TC-17 positive
        driver.find_element(By.XPATH, "//button[normalize-space()='Check out']").click()
        c.assert_text(driver, "Checked out.")
    t.case("Employee should be able to check out", "Checked out successfully", check_out)

    def admin_approves():  # TC-18 positive
        c.login_admin(driver)
        c.open_page(driver, "/attendance")
        driver.find_element(By.XPATH, _row(c.STATE["name"]) + "//button[@value='approved']").click()
        c.assert_text(driver, "Request approved.")
        status = driver.find_element(By.XPATH, _row(c.STATE["name"]) + "//span[contains(@class,'b')]").text
        assert status.lower() == "approved", f"Expected status approved but found '{status}'"
    t.case("Admin should approve the attendance request", "Attendance approved successfully", admin_approves)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
