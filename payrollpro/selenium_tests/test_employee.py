"""EMPLOYEE MODULE  (4 test cases: 2 positive, 2 negative)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from selenium.webdriver.common.by import By
from selenium_tests import config as c


def run(driver):
    t = c.Tester("EMPLOYEE MODULE")
    c.ensure_test_employee(driver)

    def list_and_search():  # TC-12 positive
        c.login_admin(driver)
        c.open_page(driver, "/employees")
        c.assert_text(driver, "Employees")
        c.assert_text(driver, c.SEEDED_EMPLOYEE["email"])
        c.fill(driver, "s", c.STATE["email"])
        driver.find_element(By.CSS_SELECTOR, "main form button").click()
        c.assert_text(driver, c.STATE["name"], "Searched employee not found in the list")
    t.case("Employee list should be displayed and a search should find the employee",
           "Employee list and search worked successfully", list_and_search)

    def search_none():  # TC-13 negative
        c.open_page(driver, "/employees")
        c.fill(driver, "s", "zzzz-no-such-employee")
        driver.find_element(By.CSS_SELECTOR, "main form button").click()
        c.assert_text(driver, "No employees found.")
    t.case("'No employees found.' for a search with no match", "No employees message displayed", search_none)

    def update_salary():  # TC-14 positive
        c.set_salary(driver)
        c.assert_text(driver, "Employee updated.")
        assert driver.find_element(By.NAME, "designation").get_attribute("value") == "QA Engineer", "Designation not saved"
        assert driver.find_element(By.NAME, "basic_salary").get_attribute("value") in ("30000", "30000.0"), "Basic salary not saved"
    t.case("Admin should update department, designation and salary structure",
           "Employee updated successfully", update_salary)

    def employee_blocked():  # TC-15 negative
        c.login_employee(driver)
        c.open_page(driver, "/employees")
        c.assert_text(driver, "403")
    t.case("Employee must not open the admin employee list (403)", "Access denied (403) displayed", employee_blocked)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
