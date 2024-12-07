from steam_login import ensure_login
from download_replays import download_replays
import time

def main():
    try:
        print("Starting CS:GO replay downloader...")
        
        # First ensure we have valid login
        print("\nChecking login status...")
        ensure_login()
        
        # Small delay to ensure cookies are saved
        time.sleep(2)
        
        # Then download replays
        print("\nStarting replay download process...")
        download_replays()
        
    except Exception as e:
        print(f"\nApplication error: {str(e)}")
        input("\nPress Enter to exit...")
    else:
        print("\nDownload process completed successfully!")
        input("\nPress Enter to exit...")

if __name__ == "__main__":
    main() 