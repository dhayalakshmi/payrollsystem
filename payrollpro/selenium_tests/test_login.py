"""LOGIN MODULE  (4 test cases: 2 positive, 2 negative)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from selenium.webdriver.common.by import By
from selenium_tests import config as c


def run(driver):
    t = c.Tester("LOGIN MODULE")
    c.logout(driver)

    def page_loads():  # TC-01 positive
        c.open_page(driver, "/login")
        c.assert_text(driver, "Log in to the system")
        c.assert_text(driver, "One record. Every payslip, accounted for.", "Left brand panel tagline not shown")
        assert driver.find_element(By.CSS_SELECTOR, ".brand").is_displayed(), "Left brand panel not shown"
        assert driver.find_element(By.CSS_SELECTOR, ".brand svg").is_displayed(), "Illustration not shown"
        assert driver.find_element(By.NAME, "email").is_displayed(), "Email field not shown"
        assert driver.find_element(By.NAME, "password").is_displayed(), "Password field not shown"
    t.case("Login page should be displayed with the brand panel, email and password fields",
           "Login page displayed successfully", page_loads)

    def admin_login():  # TC-02 positive
        c.logout(driver)
        c.login(driver, c.ADMIN["email"], c.ADMIN["password"])
        c.assert_text(driver, "Admin Dashboard", f"Dashboard not shown, page is {driver.current_url}")
    t.case("Admin should log in and see the Admin Dashboard", "Admin logged in successfully", admin_login)

    def wrong_password():  # TC-03 negative
        c.logout(driver)
        c.login(driver, c.ADMIN["email"], "Wrong@1234")
        c.assert_text(driver, "Incorrect email or password.")
        c.assert_url(driver, "/login")
    t.case("Error 'Incorrect email or password.' for a wrong password",
           "Error message displayed for wrong password", wrong_password)

    def empty_form():  # TC-04 negative
        c.logout(driver)
        c.open_page(driver, "/login")
        c.submit(driver)
        c.assert_text(driver, "Enter a valid email address.")
        c.assert_text(driver, "Use 8+ characters")
    t.case("Validation errors when the login form is submitted empty",
           "Validation messages displayed for empty form", empty_form)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
