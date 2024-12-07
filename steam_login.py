from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import pickle
import os

COOKIE_FILE = 'steam_cookies.pkl'
STEAM_LOGIN_URL = 'https://steamcommunity.com/login'

def create_driver(headless=False):
    options = Options()
    if headless:
        options.add_argument('--headless')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    
    driver = webdriver.Chrome(options=options)
    return driver

def save_cookies(cookies):
    with open(COOKIE_FILE, 'wb') as f:
        pickle.dump(cookies, f)

def load_cookies():
    try:
        with open(COOKIE_FILE, 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return None

def check_login_status(driver):
    try:
        # Wait for either login button or avatar to appear
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, 
                ".user_avatar"  # Only look for avatar now
            ))
        )
        
        # Additional check - verify we're actually logged in
        avatar = driver.find_elements(By.CSS_SELECTOR, ".user_avatar")
        return bool(avatar)  # Return True if avatar exists
    except:
        return False

def handle_login():
    print("Steam login required...")
    driver = create_driver(headless=False)
    
    try:
        driver.get(STEAM_LOGIN_URL)
        
        # Wait for user to log in manually
        print("Please log in to Steam in the browser window...")
        WebDriverWait(driver, 300).until(lambda d: check_login_status(d))
        
        # Additional verification - navigate to profile page
        driver.get('https://steamcommunity.com/my')
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".user_avatar"))
        )
        
        print("Login successful! Saving cookies...")
        cookies = driver.get_cookies()
        save_cookies(cookies)
        
        return cookies
        
    except Exception as e:
        print(f"Login error: {str(e)}")
        return None
    finally:
        driver.quit()

def verify_login(driver):
    """Verify that the current session is valid"""
    try:
        driver.get('https://steamcommunity.com/my')
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".user_avatar"))
        )
        return True
    except:
        return False

def ensure_login():
    """Ensures valid Steam login cookies exist, prompting for login if necessary"""
    cookies = load_cookies()
    
    if cookies:
        # Verify existing cookies
        test_driver = create_driver(headless=True)
        try:
            test_driver.get('https://steamcommunity.com')
            for cookie in cookies:
                test_driver.add_cookie(cookie)
            
            if verify_login(test_driver):
                print("Existing login is valid")
                test_driver.quit()
                return cookies
        except:
            pass
        finally:
            test_driver.quit()
    
    # If we get here, we need new cookies
    print("Need to login again")
    cookies = handle_login()
    if not cookies:
        raise Exception("Failed to obtain Steam login cookies")
    
    return cookies
