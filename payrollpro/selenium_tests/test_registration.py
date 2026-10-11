"""REGISTRATION & PROFILE MODULE  (7 test cases: 3 positive, 4 negative)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from selenium_tests import config as c


def _try(driver, name, email, pw, confirm):
    c.logout(driver)
    c.open_page(driver, "/register")
    c.fill(driver, "name", name)
    c.fill(driver, "email", email)
    c.fill(driver, "password", pw)
    c.fill(driver, "confirm", confirm)
    c.submit(driver)


def run(driver):
    t = c.Tester("REGISTRATION MODULE")
    c.logout(driver)

    def page_loads():  # TC-05 positive
        c.open_page(driver, "/register")
        c.assert_text(driver, "Create your account")
        for field in ("name", "email", "password", "confirm"):
            assert driver.find_element(c.By.NAME, field).is_displayed(), f"{field} field not shown"
    t.case("Registration page should be displayed with all fields",
           "Registration page displayed successfully", page_loads)

    def weak_pw():  # TC-06 negative
        _try(driver, "Valid Name", c.unique_email(), "password", "password")
        c.assert_text(driver, "Use 8+ characters")
    t.case("Validation error for a weak password", "Password validation message displayed", weak_pw)

    def mismatch():  # TC-07 negative
        _try(driver, "Valid Name", c.unique_email(), c.TEST_PASSWORD, "Different@1234")
        c.assert_text(driver, "Passwords do not match.")
    t.case("Error 'Passwords do not match.' when passwords differ",
           "Mismatch message displayed", mismatch)

    def duplicate():  # TC-08 negative
        _try(driver, "Valid Name", c.SEEDED_EMPLOYEE["email"], c.TEST_PASSWORD, c.TEST_PASSWORD)
        c.assert_text(driver, "This email is already registered.")
    t.case("Error for an email that is already registered",
           "Duplicate email message displayed", duplicate)

    def register_ok():  # TC-09 positive
        c.STATE["name"], c.STATE["email"] = c.unique_name(), c.unique_email()
        c.register_employee(driver, c.STATE["name"], c.STATE["email"])
        c.assert_text(driver, "Complete Your Profile", f"Profile page not shown, page is {driver.current_url}")
    t.case("Employee account should be created and the profile page opened",
           "Employee registered successfully", register_ok)

    def profile_invalid():  # TC-10 negative
        c.fill_profile(driver, phone="12345")
        c.assert_text(driver, "Enter a valid 10-digit mobile number")
    t.case("Validation error for an invalid mobile number on the profile form",
           "Mobile number validation message displayed", profile_invalid)

    def profile_ok():  # TC-11 positive
        c.fill_profile(driver)
        c.assert_text(driver, "Details saved successfully")
        c.assert_text(driver, "Welcome")
    t.case("Profile should be saved and the employee dashboard opened",
           "Profile saved successfully", profile_ok)
    c.logout(driver)


if __name__ == "__main__":
    c.standalone(run)
