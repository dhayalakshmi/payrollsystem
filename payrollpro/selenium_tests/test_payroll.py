"""PAYROLL MODULE  (2 test cases: 2 positive)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from selenium.webdriver.common.by import By
from selenium_tests import config as c


def run(driver):
    t = c.Tester("PAYROLL MODULE")
    c.ensure_salary(driver)

    def generate():  # TC-22 positive
        c.login_admin(driver)
        c.open_page(driver, "/payslips")
        c.assert_text(driver, "Payroll")
        driver.find_element(By.XPATH, "//button[normalize-space()='Generate payroll']").click()
        c.assert_text(driver, "Payroll generated for")
        c.STATE["payroll_done"] = True
        row = driver.find_element(By.XPATH, f"//tr[td[normalize-space()='{c.STATE['name']}']]")
        assert c.inr(c.GROSS) in row.text, f"Gross {c.inr(c.GROSS)} not found in row: {row.text}"
        assert c.inr(c.NET) in row.text, f"Net pay {c.inr(c.NET)} not found in row: {row.text}"
        assert "Total" in driver.find_element(By.CSS_SELECTOR, "tr.tot").text, "Totals row not shown"
    t.case(f"Payroll should be generated; employee row shows gross {c.inr(c.GROSS)} and net {c.inr(c.NET)}",
           "Payroll generated and calculated correctly", generate)

    def csv_export():  # TC-23 positive
        href = driver.find_element(By.LINK_TEXT, "Export CSV").get_attribute("href")
        status, body = c.session_get(driver, href.replace(c.BASE_URL, ""))
        assert status == 200, f"Export returned HTTP {status}"
        assert body.startswith("Employee,Email,Month"), "CSV header is wrong"
        assert c.STATE["email"] in body, "Employee not found in the CSV"
    t.case("Payroll CSV export should contain the employee", "CSV exported successfully", csv_export)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
