import pickle
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timezone

# Define constants
LOGIN_URL = 'https://steamcommunity.com/login'
COOKIES_FILE = 'steam_cookies.pkl'

def save_cookies(cookies):
    with open(COOKIES_FILE, 'wb') as f:
        pickle.dump(cookies, f)

def load_cookies():
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, 'rb') as f:
            return pickle.load(f)
    return None

def create_headless_driver():
    options = Options()
    options.add_argument('--headless')
    return webdriver.Chrome(options=options)

def create_visible_driver():
    return webdriver.Chrome()

def is_session_valid(driver):
    driver.get('https://steamcommunity.com/my')
    return 'Sign In' not in driver.title

def login_to_steam():
    # Start with visible browser for login
    driver = create_visible_driver()
    driver.get(LOGIN_URL)
    
    # Wait for manual login to complete (wait for profile page)
    print("Please log in manually in the browser window...")
    wait = WebDriverWait(driver, 300)  # 5-minute timeout
    wait.until(lambda d: 'Sign In' not in d.title)
    
    # Save cookies after successful login
    cookies = driver.get_cookies()
    save_cookies(cookies)
    print("Login successful! Cookies saved.")
    
    # Close visible browser
    driver.quit()
    
    # Return cookies
    return cookies

def check_cookie_expiry(cookies):
    if not cookies:
        return False
        
    current_time = datetime.now(timezone.utc).timestamp()
    
    # Check steamLoginSecure cookie, which is crucial for authentication
    for cookie in cookies:
        if cookie['name'] == 'steamLoginSecure':
            if 'expiry' in cookie:
                expiry_time = cookie['expiry']
                # If cookie expires in less than 24 hours
                if expiry_time - current_time < 86400:  # 86400 seconds = 24 hours
                    print("Warning: Steam session will expire in less than 24 hours")
                    return False
                else:
                    days_left = (expiry_time - current_time) / 86400
                    print(f"Steam session valid for {days_left:.1f} more days")
                    return True
    return False

def main():
    # Try to create headless session with saved cookies
    driver = create_headless_driver()
    cookies = load_cookies()
    
    if cookies and check_cookie_expiry(cookies):
        # Visit Steam domain first (required for cookie setting)
        driver.get('https://steamcommunity.com')
        
        # Add saved cookies
        for cookie in cookies:
            driver.add_cookie(cookie)
            
        if is_session_valid(driver):
            print("Session is valid. Using saved cookies.")
        else:
            print("Session is invalid. Need to login again.")
            driver.quit()
            cookies = login_to_steam()
            
            # Create new headless driver with fresh cookies
            driver = create_headless_driver()
            driver.get('https://steamcommunity.com')
            for cookie in cookies:
                driver.add_cookie(cookie)
    else:
        print("No valid saved cookies found. Need to login.")
        driver.quit()
        cookies = login_to_steam()
        
        # Create new headless driver with fresh cookies
        driver = create_headless_driver()
        driver.get('https://steamcommunity.com')
        for cookie in cookies:
            driver.add_cookie(cookie)
    
    # Test the session
    driver.get('https://steamcommunity.com/my')
    print(f"Page Title: {driver.title}")
    
    # Keep the session available for further use
    return driver

if __name__ == "__main__":
    driver = main()
    # The driver can be used for further operations
    # Remember to call driver.quit() when completely done
