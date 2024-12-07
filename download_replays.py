from steam_login import load_cookies, create_driver, ensure_login, verify_login
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
import asyncio
import aiohttp
from aiohttp import ClientTimeout
from tqdm import tqdm
import json
from bs4 import BeautifulSoup
import traceback
import requests
import bz2
import shutil

MATCH_HISTORY_URL = "https://steamcommunity.com/my/gcpd/730?tab=matchhistorypremier"
DOWNLOAD_DIR = "replays"
MAX_CONCURRENT_DOWNLOADS = 5  # Adjust this based on your internet connection
TIMEOUT = ClientTimeout(total=300)  # 5 minutes timeout for each download

def setup_driver(headless=True):
    """Setup Chrome driver with cookies"""
    driver = create_driver(headless=headless)
    cookies = load_cookies()
    
    if not cookies:
        raise Exception("No cookies found - login required")
    
    # Visit Steam domain first (required for cookie setting)
    driver.get('https://steamcommunity.com')
    
    # Add saved cookies
    for cookie in cookies:
        try:
            driver.add_cookie(cookie)
        except Exception as e:
            print(f"Warning: Could not add cookie: {str(e)}")
    
    # Verify login worked
    if not verify_login(driver):
        raise Exception("Login verification failed")
    
    return driver

async def download_file(session, url, filepath, pbar):
    if os.path.exists(filepath.replace('.bz2', '')):  # Check for existing .dem file
        pbar.update(1)
        return True

    try:
        async with session.get(url, timeout=TIMEOUT) as response:
            if response.status == 200:
                with open(filepath, 'wb') as f:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                
                # Decompress the file after successful download
                if filepath.endswith('.bz2'):
                    if decompress_bz2(filepath):
                        print(f"Decompressed {filepath}")
                    else:
                        print(f"Failed to decompress {filepath}")
                
                pbar.update(1)
                return True
            else:
                print(f"\nFailed to download {filepath}: Status code {response.status}")
                return False
    except Exception as e:
        print(f"\nError downloading {filepath}: {str(e)}")
        return False

async def download_batch(urls_and_paths):
    async with aiohttp.ClientSession() as session:
        pbar = tqdm(total=len(urls_and_paths), desc="Downloading replays")
        tasks = []
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

        async def download_with_semaphore(url, filepath):
            async with semaphore:
                return await download_file(session, url, filepath, pbar)

        for url, filepath in urls_and_paths:
            task = asyncio.ensure_future(download_with_semaphore(url, filepath))
            tasks.append(task)

        results = await asyncio.gather(*tasks)
        pbar.close()
        return results

def extract_player_stats(driver, match_container):
    try:
        print("Extracting stats from match...")
        stats = []
        
        # Find all player rows directly under the scoreboard table
        player_rows = match_container.find_elements(By.CSS_SELECTOR, "td.inner_name")
        print(f"Found {len(player_rows)} player rows")
        
        for row in player_rows:
            try:
                # Get player link and name
                player_link = row.find_element(By.CSS_SELECTOR, "a.linkTitle")
                
                # Get the parent row which contains all stats
                stat_row = row.find_element(By.XPATH, "./..")
                
                # Get all stat cells from the parent row
                cells = stat_row.find_elements(By.TAG_NAME, "td")
                
                player_info = {
                    'profile_url': player_link.get_attribute('href'),
                    'name': player_link.text,
                    'ping': cells[1].text if len(cells) > 1 else '',
                    'kills': cells[2].text if len(cells) > 2 else '',
                    'assists': cells[3].text if len(cells) > 3 else '',
                    'deaths': cells[4].text if len(cells) > 4 else '',
                    'mvps': cells[5].text if len(cells) > 5 else '',
                    'hsp': cells[6].text if len(cells) > 6 else '',
                    'score': cells[7].text if len(cells) > 7 else ''
                }
                
                print(f"Extracted stats for player: {player_info['name']}")
                stats.append(player_info)
                
            except Exception as e:
                print(f"Error extracting player row: {str(e)}")
                continue
        
        return stats
    except Exception as e:
        print(f"Error extracting stats: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return None

def find_matches(driver):
    """Find all match containers on the page"""
    try:
        print("\nWaiting for page to load...")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.csgo_scoreboard_root"))
        )
        
        # Find all match containers
        match_containers = driver.find_elements(By.CSS_SELECTOR, "tr:has(td.val_left)")
        previous_count = getattr(find_matches, 'previous_count', 0)
        print(f"Found {len(match_containers)} match containers (Previous: {previous_count})")
        find_matches.previous_count = len(match_containers)
        
        return match_containers
    except Exception as e:
        print(f"Error finding matches: {str(e)}")
        return []

def find_download_buttons(match_container):
    """Find download buttons in a match container"""
    try:
        # Look for download button div
        download_links = match_container.find_elements(By.CSS_SELECTOR, "div.csgo_scoreboard_btn_gotv")
        if download_links:
            # Get the parent a tag which contains the actual download URL
            download_urls = [link.find_element(By.XPATH, "./ancestor::a").get_attribute('href') for link in download_links]
            print(f"Found {len(download_urls)} download buttons")
            return download_urls
        return []
    except Exception as e:
        print(f"Error finding download buttons: {str(e)}")
        return []

def get_download_links(driver, status_callback=None):
    wait = WebDriverWait(driver, 10)
    processed_urls = set()  # Track processed URLs
    previous_matches_count = 0
    matches_without_download = 0  # Counter for matches without download button
    MAX_MATCHES_WITHOUT_DOWNLOAD = 3  # Stop after this many matches without download buttons
    
    while True:
        try:
            print("\nWaiting for page to load...")
            time.sleep(5)  # Give the page more time to load
            
            match_containers = find_matches(driver)
            current_matches_count = len(match_containers)
            print(f"Found {current_matches_count} match containers (Previous: {previous_matches_count})")
            
            if current_matches_count == previous_matches_count:
                print("No new matches found, stopping...")
                break
                
            previous_matches_count = current_matches_count
            
            # Process each match container
            for i, container in enumerate(match_containers):
                try:
                    print(f"\nProcessing match {i+1}/{current_matches_count}")
                    
                    # Find download links first - if none exist, this is an old match
                    download_links = find_download_buttons(container)
                    
                    if not download_links:
                        print("No download button found - match too old")
                        matches_without_download += 1
                        if matches_without_download >= MAX_MATCHES_WITHOUT_DOWNLOAD:
                            print(f"\nFound {matches_without_download} consecutive matches without downloads.")
                            print("Matches are too old, stopping processing...")
                            return processed_urls
                        continue
                    else:
                        matches_without_download = 0  # Reset counter if we find a download button
                    
                    # Extract player stats
                    stats = extract_player_stats(driver, container)
                    if stats:
                        print(f"Successfully extracted stats for {len(stats)} players")
                    
                    # Process download links
                    for replay_url in download_links:
                        try:
                            if replay_url and ".dem" in replay_url and replay_url not in processed_urls:
                                filename = replay_url.split('/')[-1]
                                filepath = os.path.join(DOWNLOAD_DIR, filename)
                                
                                print(f"Found new replay URL: {replay_url}")
                                processed_urls.add(replay_url)
                                
                                # Download the replay immediately
                                if not os.path.exists(filepath):
                                    if download_replay(replay_url, filepath):
                                        print(f"Successfully downloaded: {filepath}")
                                        # Save stats to JSON with same name as replay
                                        if stats:
                                            json_path = os.path.join(DOWNLOAD_DIR, filename.replace('.dem.bz2', '.json'))
                                            with open(json_path, 'w') as f:
                                                json.dump(stats, f, indent=4)
                                    else:
                                        print(f"Failed to download: {filepath}")
                                else:
                                    print(f"Skipping {filepath} - already exists")
                            else:
                                print("Already processed this replay URL")
                        except Exception as e:
                            print(f"Error processing download link: {str(e)}")
                        
                except Exception as e:
                    print(f"Error processing match container: {str(e)}")
                    continue
            
            # Try to find and click "Load More" button
            try:
                load_more = driver.find_element(By.ID, "load_more_button")
                if not load_more.is_displayed():
                    print("No more matches to load")
                    break
                    
                load_more.click()
                print(f"Clicked Load More... (Current total processed: {len(processed_urls)})")
                
                # Wait for new content with explicit wait
                wait.until(lambda driver: len(find_matches(driver)) > current_matches_count)
                time.sleep(3)  # Additional wait to ensure content is fully loaded
                
            except Exception as e:
                print(f"Could not find or click Load More button: {str(e)}")
                break
                
        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            break
            
    return processed_urls

def decompress_bz2(bz2_path):
    """Decompress a .bz2 file and remove the original compressed file"""
    dem_path = bz2_path.replace('.bz2', '')
    try:
        with bz2.BZ2File(bz2_path, 'rb') as source:
            with open(dem_path, 'wb') as dest:
                shutil.copyfileobj(source, dest)
        # Remove the original .bz2 file
        os.remove(bz2_path)
        print(f"Successfully decompressed: {dem_path}")
        return True
    except Exception as e:
        print(f"Error decompressing {bz2_path}: {str(e)}")
        return False

def download_replay(url, filepath):
    """Download a single replay file"""
    try:
        print(f"\nStarting download of {url}")
        print(f"Saving to: {filepath}")
        
        # Check if decompressed file already exists
        dem_path = filepath.replace('.bz2', '')
        if os.path.exists(dem_path):
            print(f"Decompressed file already exists: {dem_path}")
            return True
        
        # Add headers to mimic browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Make the request with a timeout
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        print(f"Response status code: {response.status_code}")
        response.raise_for_status()
        
        # Get total file size
        total_size = int(response.headers.get('content-length', 0))
        print(f"File size: {total_size / (1024*1024):.2f} MB")
        
        # Download with progress tracking
        block_size = 1024  # 1 Kibibyte
        downloaded = 0
        last_printed_progress = 0
        
        with open(filepath, 'wb') as f:
            for data in response.iter_content(block_size):
                downloaded += len(data)
                f.write(data)
                # Calculate progress
                progress = int((downloaded / total_size) * 100) if total_size else 0
                # Only print if progress has changed by at least 1%
                if progress != last_printed_progress:
                    print(f"Download progress: {progress}%", end='\r')
                    last_printed_progress = progress
        
        print(f"\nSuccessfully downloaded {filepath}")
        
        # Decompress the file after successful download
        if filepath.endswith('.bz2'):
            if decompress_bz2(filepath):
                print(f"Successfully decompressed {filepath}")
                return True
            else:
                print(f"Failed to decompress {filepath}")
                return False
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"Network error during download: {str(e)}")
        if os.path.exists(filepath):
            os.remove(filepath)  # Clean up partial download
        return False
    except Exception as e:
        print(f"Error downloading replay: {str(e)}")
        if os.path.exists(filepath):
            os.remove(filepath)  # Clean up partial download
        return False

def download_replays(status_callback=None):
    """Main function to download CS:GO replays"""
    try:
        # Create downloads directory
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        if status_callback:
            status_callback(f"Download directory: {os.path.abspath(DOWNLOAD_DIR)}")
        
        # Setup driver and download replays
        if status_callback:
            status_callback("Setting up browser...")
        driver = setup_driver(headless=True)
        
        try:
            if status_callback:
                status_callback("Navigating to match history...")
            driver.get(MATCH_HISTORY_URL)
            
            # Wait for the match history to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.csgo_scoreboard_root"))
            )
            
            processed_urls = get_download_links(driver, status_callback)
            if status_callback:
                status_callback(f"Finished processing {len(processed_urls)} matches")
            
        finally:
            driver.quit()
            
    except Exception as e:
        error_msg = f"Error in download_replays: {str(e)}"
        if status_callback:
            status_callback(error_msg)
        print(error_msg)
        print(f"Traceback: {traceback.format_exc()}")
        raise

if __name__ == "__main__":
    download_replays()
