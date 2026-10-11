"""PAYSLIP MODULE  (2 test cases: 1 positive, 1 negative)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from selenium.webdriver.common.by import By
from selenium_tests import config as c


def _cell(driver, label):
    return driver.find_element(By.XPATH, f"//div[@class='slip']//tr[td[1][normalize-space()='{label}']]/td[2]").text


def _payslip_id(url):
    return int(url.rstrip("/").split("/")[-1])


def run(driver):
    t = c.Tester("PAYSLIP MODULE")
    c.ensure_payroll(driver)

    def payslip_correct():  # TC-24 positive
        c.login_employee(driver)
        c.open_page(driver, "/payslips")
        c.assert_text(driver, "My Payslips")
        link = driver.find_element(By.LINK_TEXT, "View / download")
        c.STATE["payslip_url"] = link.get_attribute("href")
        link.click()
        assert driver.find_element(By.CSS_SELECTOR, ".slip").is_displayed(), "Payslip not displayed"
        c.assert_text(driver, c.STATE["name"])
        gross, ded = c.money(_cell(driver, "Gross earnings")), c.money(_cell(driver, "Total deductions"))
        net = c.money(driver.find_element(By.CSS_SELECTOR, ".netbox b").text)
        assert gross == c.GROSS, f"Gross earnings {gross:,.0f} but expected {c.GROSS:,.0f}"
        assert ded == c.DEDUCTIONS, f"Total deductions {ded:,.0f} but expected {c.DEDUCTIONS:,.0f}"
        assert net == gross - ded == c.NET, f"Net pay {net:,.0f} but expected {c.NET:,.0f} (gross - deductions)"
        c.assert_text(driver, "XXXXXX" + c.PROFILE["bank_acc"][-4:], "Masked bank account not shown")
        assert c.PROFILE["bank_acc"] not in c.page_text(driver), "Full bank account number is visible"
        assert driver.find_element(By.XPATH, "//button[contains(.,'Download / Print as PDF')]").is_displayed(), \
            "Download / Print button not shown"
    t.case(f"Payslip should show gross {c.inr(c.GROSS)}, deductions {c.inr(c.DEDUCTIONS)}, net {c.inr(c.NET)}, masked bank account and a print button",
           "Payslip displayed and calculated correctly", payslip_correct)

    def other_blocked():  # TC-25 negative
        c.login_admin(driver)
        c.open_page(driver, "/payslips")
        ids = {_payslip_id(a.get_attribute("href")) for a in driver.find_elements(By.XPATH, "//a[normalize-space()='View']")}
        others = sorted(ids - {_payslip_id(c.STATE["payslip_url"])})
        assert others, "No other employee payslip exists to test with"
        c.login_employee(driver)
        c.open_page(driver, f"/payslip/{others[0]}")
        c.assert_text(driver, "403")
    t.case("Employee must not open another employee's payslip (403)", "Access denied (403) displayed", other_blocked)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
