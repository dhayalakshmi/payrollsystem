"""Shared settings and helpers for the PayrollPro Selenium tests (Google Chrome)."""
import os
import sys
import time
import random
import string
import socket
import shutil
import tempfile
import subprocess
import urllib.request
from datetime import date, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# ----------------------------------------------------------------- settings
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("TEST_PORT", 8000))
BASE_URL = os.environ.get("BASE_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
HEADLESS = os.environ.get("HEADLESS", "0") == "1"      # HEADLESS=1 -> no browser window
DELAY = float(os.environ.get("STEP_DELAY", "0.4"))     # pause (seconds) so you can watch the browser
TIMEOUT = 10

ADMIN = {"email": "hr@admin.ac.in", "password": "Admin@123"}
SEEDED_EMPLOYEE = {"email": "aarav.sharma@example.com", "password": "Welcome@123"}
TEST_PASSWORD = "Test@1234"

SALARY = {  # monthly structure given to the test employee by the admin
    "basic_salary": "30000", "hra": "12000", "allowances": "3000", "bonus": "1000", "overtime": "500",
    "pf": "3600", "ptax": "200", "itax": "1000", "insurance": "500", "other_ded": "0",
}
GROSS, DEDUCTIONS = 46500.0, 5300.0
NET = GROSS - DEDUCTIONS   # 41200 (no unpaid leave is approved by these tests)

STATE = {}      # data shared between test modules (test employee, etc.)
RESULTS = []    # (module, expected, actual, passed)


# ------------------------------------------------------------------ reporter
class Tester:
    """Prints each test case in the format:

        ----- PAYSLIP MODULE -----
        Expected Output: Payslip should be displayed
        Actual Output: Payslip displayed successfully
        Test Result: PASS
    """

    def __init__(self, module):
        self.module = module
        print(f"\n----- {module} -----")

    def case(self, expected, success, fn):
        """Run fn(). No exception -> PASS and `success` is the actual output.
        An exception -> FAIL and the problem is the actual output."""
        try:
            fn()
            actual, ok = success, True
        except AssertionError as e:
            actual, ok = (str(e) or "Assertion failed"), False
        except Exception as e:  # Selenium timeouts, missing elements, etc.
            actual, ok = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}", False
        print(f"Expected Output: {expected}")
        print(f"Actual Output: {actual}")
        print(f"Test Result: {'PASS' if ok else 'FAIL'}\n")
        RESULTS.append((self.module, expected, actual, ok))
        return ok


def summary():
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r[3])
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    modules = []
    for m, *_ in RESULTS:
        if m not in modules:
            modules.append(m)
    for m in modules:
        rs = [r for r in RESULTS if r[0] == m]
        print(f"{m:<22} {sum(r[3] for r in rs)}/{len(rs)} passed")
    print("-" * 60)
    print(f"TOTAL: {total}   PASSED: {passed}   FAILED: {total - passed}")
    for m, e, a, ok in RESULTS:
        if not ok:
            print(f"  FAILED [{m}] {e}  ->  {a}")
    print("=" * 60)
    return passed == total


# -------------------------------------------------------------------- driver
def get_driver():
    """Launch Google Chrome. Selenium 4.6+ downloads the matching chromedriver automatically."""
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--no-sandbox")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    opts.add_experimental_option("prefs", {"credentials_enable_service": False,
                                           "profile.password_manager_enabled": False})
    opts.add_argument("--disable-dev-shm-usage")
    chrome_bin, driver_path = os.environ.get("CHROME_BIN"), os.environ.get("CHROMEDRIVER")
    if chrome_bin:                      # optional: use a specific Chrome/Chromium
        opts.binary_location = chrome_bin
    if driver_path:                     # optional: use a specific chromedriver
        from selenium.webdriver.chrome.service import Service
        driver = webdriver.Chrome(service=Service(driver_path), options=opts)
    else:
        driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(2)
    return driver


# -------------------------------------------------------------------- server
def _up():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


def start_server():
    """Use the app if it is already running, otherwise start it on a fresh temporary database
    (with the demo data) so every run starts from the same state. Returns a stop() function."""
    if _up():
        print(f"[setup] Using the app already running at {BASE_URL}")
        return lambda: None
    tmp = tempfile.mkdtemp(prefix="payrollpro_test_")
    env = dict(os.environ, PORT=str(PORT), DB_PATH=os.path.join(tmp, "test.db"), SEED_DEMO="1")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=PROJECT_DIR, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if _up():
            break
        if proc.poll() is not None:
            raise RuntimeError("PayrollPro failed to start (run `python app.py` to see the error).")
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("PayrollPro did not start within 20 seconds.")
    print(f"[setup] Started PayrollPro at {BASE_URL} with a fresh test database")

    def stop():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    return stop


def standalone(module_run):
    """Lets any test file be run on its own: python selenium_tests/test_login.py"""
    stop = start_server()
    driver = get_driver()
    try:
        module_run(driver)
    finally:
        driver.quit()
        stop()
    sys.exit(0 if summary() else 1)


# ------------------------------------------------------------------- helpers
def open_page(driver, path=""):
    driver.get(BASE_URL + path)
    time.sleep(DELAY)


def page_text(driver):
    return driver.find_element(By.TAG_NAME, "body").text


def wait_text(driver, text, timeout=TIMEOUT):
    """Wait for `text` (case-insensitive, because CSS may show e.g. 'WELCOME BACK' in capitals)."""
    WebDriverWait(driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until(
        lambda d: text.lower() in page_text(d).lower())   # ignore 'stale element' while the page is reloading


def assert_text(driver, text, what=None):
    """Assert that `text` is on the page (case-insensitive)."""
    try:
        wait_text(driver, text, 4)
    except Exception:
        raise AssertionError(what or f"Expected text '{text}' was not found on {driver.current_url}")


def assert_url(driver, part):
    assert part in driver.current_url, f"Expected URL to contain '{part}' but was {driver.current_url}"


def fill(driver, name, value):
    el = driver.find_element(By.NAME, name)
    if el.get_attribute("type") in ("date", "month"):   # locale-proof way of filling date inputs
        driver.execute_script(
            "arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el, value)
    else:
        el.clear()
        el.send_keys(value)
    return el


def submit(driver):
    """Click the main form button on the page."""
    driver.find_element(By.CSS_SELECTOR, "main form button, .stub form button").click()
    time.sleep(DELAY)


def logout(driver):
    open_page(driver, "/logout")


def login(driver, email, password):
    open_page(driver, "/login")
    fill(driver, "email", email)
    fill(driver, "password", password)
    submit(driver)


def login_admin(driver):
    logout(driver)
    login(driver, ADMIN["email"], ADMIN["password"])
    assert_text(driver, "Admin Dashboard", "Admin login failed - dashboard not shown")


def login_employee(driver):
    ensure_test_employee(driver)
    logout(driver)
    login(driver, STATE["email"], TEST_PASSWORD)
    assert_text(driver, "Welcome", "Employee login failed - dashboard not shown")


def errors(driver):
    return " | ".join(e.text for e in driver.find_elements(By.CSS_SELECTOR, ".err, .flash.err") if e.text)


def flash_text(driver):
    return " | ".join(e.text for e in driver.find_elements(By.CSS_SELECTOR, ".flash") if e.text)


def unique_name():
    return "Selenium " + "".join(random.choices(string.ascii_lowercase, k=7)).capitalize()


def unique_email(prefix="selenium", domain="example.com"):
    return f"{prefix}.{int(time.time() * 1000)}{random.randint(10, 99)}@{domain}"


def money(text):
    """'₹41,200' -> 41200.0"""
    digits = "".join(c for c in text if c.isdigit() or c == ".")
    return float(digits) if digits else 0.0


def inr(v):
    return "₹" + f"{v:,.0f}"


def register_employee(driver, name, email, password=TEST_PASSWORD):
    logout(driver)
    open_page(driver, "/register")
    fill(driver, "name", name)
    fill(driver, "email", email)
    fill(driver, "password", password)
    fill(driver, "confirm", password)
    submit(driver)


PROFILE = {"phone": "9876501234", "dob": "1998-05-15", "address": "12, Gandhi Road, Vellore, Tamil Nadu 632001",
           "bank_acc": "62014857309216", "ifsc": "SBIN0001234", "emergency": "9123409876"}


def fill_profile(driver, **overrides):
    data = {**PROFILE, **overrides}
    for k, v in data.items():
        fill(driver, k, v)
    submit(driver)


def ensure_test_employee(driver):
    """Create (once per run) an employee with a completed profile, used by the other modules."""
    if STATE.get("email"):
        return
    STATE["name"], STATE["email"] = unique_name(), unique_email()
    register_employee(driver, STATE["name"], STATE["email"])
    assert_text(driver, "Complete Your Profile", "Could not create the test employee")
    fill_profile(driver)
    assert_text(driver, "Details saved successfully", "Could not complete the test employee profile")
    logout(driver)


def open_employee_as_admin(driver):
    """Admin -> Employees -> open the test employee's page."""
    ensure_test_employee(driver)
    login_admin(driver)
    open_page(driver, "/employees")
    fill(driver, "s", STATE["email"])
    driver.find_element(By.CSS_SELECTOR, "main form button").click()
    time.sleep(DELAY)
    driver.find_element(By.XPATH, f"//tr[td[normalize-space()='{STATE['email']}']]//a[normalize-space()='Open']").click()
    time.sleep(DELAY)


def set_salary(driver):
    open_employee_as_admin(driver)
    fill(driver, "department", "Engineering")
    fill(driver, "designation", "QA Engineer")
    for k, v in SALARY.items():
        fill(driver, k, v)
    driver.find_element(By.XPATH, "//button[normalize-space()='Save changes']").click()
    time.sleep(DELAY)
    STATE["salary_set"] = True


def ensure_salary(driver):
    ensure_test_employee(driver)
    if not STATE.get("salary_set"):
        set_salary(driver)


def generate_payroll(driver):
    login_admin(driver)
    open_page(driver, "/payslips")
    driver.find_element(By.XPATH, "//button[normalize-space()='Generate payroll']").click()
    time.sleep(DELAY)


def ensure_payroll(driver):
    ensure_salary(driver)
    if not STATE.get("payroll_done"):
        generate_payroll(driver)
        STATE["payroll_done"] = True


def session_get(driver, path):
    """Fetch a URL (e.g. the CSV export) using the browser's logged-in session. Returns (status, body)."""
    cookies = "; ".join(f"{c['name']}={c['value']}" for c in driver.get_cookies())
    req = urllib.request.Request(BASE_URL + path, headers={"Cookie": cookies})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode("utf-8", "replace")


def future(days):
    return (date.today() + timedelta(days=days)).isoformat()
