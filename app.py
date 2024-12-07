from flask import Flask, render_template, jsonify, request, Response, redirect
from steam_login import ensure_login, check_login_status, create_driver, load_cookies, handle_login
from download_replays import download_replays, DOWNLOAD_DIR
import threading
import queue
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import os
import json
from datetime import datetime

app = Flask(__name__)

# Global variables to track download status
download_status = {
    'is_running': False,
    'status_message': '',
    'error': None
}

message_queue = queue.Queue()

def update_status(message):
    """Update status and add message to queue"""
    download_status['status_message'] = message
    message_queue.put(message)

@app.route('/')
def index():
    """Main page - check login status and render appropriate view"""
    cookies = load_cookies()
    is_logged_in = False
    
    if cookies:
        driver = create_driver(headless=True)
        try:
            # Visit Steam domain first
            driver.get('https://steamcommunity.com')
            
            # Add cookies
            for cookie in cookies:
                try:
                    driver.add_cookie(cookie)
                except Exception as e:
                    print(f"Error adding cookie: {e}")
            
            # Navigate to profile page to verify login
            driver.get('https://steamcommunity.com/my')
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".user_avatar"))
                )
                is_logged_in = True
            except:
                is_logged_in = False
                
        except Exception as e:
            print(f"Error checking login status: {e}")
        finally:
            driver.quit()
    
    return render_template('index.html', 
                         is_logged_in=is_logged_in,
                         is_downloading=download_status['is_running'])

@app.route('/login')
def login():
    """Handle Steam login"""
    try:
        cookies = handle_login()
        if cookies:
            # Add a small delay to ensure cookies are saved
            time.sleep(1)
            return redirect('/')
        return "Login failed", 400
    except Exception as e:
        return str(e), 500

@app.route('/start-download', methods=['POST'])
def start_download():
    """Start the download process"""
    if download_status['is_running']:
        return jsonify({'error': 'Download already in progress'})
    
    def download_worker():
        download_status['is_running'] = True
        download_status['error'] = None
        try:
            download_replays(status_callback=update_status)
            update_status("Download completed successfully!")
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            download_status['error'] = error_msg
            update_status(error_msg)
        finally:
            download_status['is_running'] = False
    
    # Start download in background thread
    thread = threading.Thread(target=download_worker)
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'started'})

@app.route('/status')
def get_status():
    """Get current download status"""
    return jsonify({
        'is_running': download_status['is_running'],
        'status_message': download_status['status_message'],
        'error': download_status['error']
    })

@app.route('/stream-status')
def stream_status():
    """Stream status updates to client"""
    def generate():
        while True:
            try:
                message = message_queue.get(timeout=1)
                yield f"data: {message}\n\n"
            except queue.Empty:
                yield "data: heartbeat\n\n"
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/demos')
def get_demos():
    """Get list of downloaded demos"""
    demos = []
    try:
        for file in os.listdir(DOWNLOAD_DIR):
            if file.endswith('.dem'):
                file_path = os.path.join(DOWNLOAD_DIR, file)
                stats_path = os.path.join(DOWNLOAD_DIR, file.replace('.dem', '.json'))
                
                # Get file creation time
                creation_time = datetime.fromtimestamp(os.path.getctime(file_path))
                
                demos.append({
                    'name': file,
                    'date': creation_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'has_stats': os.path.exists(stats_path)
                })
        
        return jsonify({'demos': sorted(demos, key=lambda x: x['date'], reverse=True)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/stats/<demo_name>')
def get_demo_stats(demo_name):
    """Get stats for a specific demo"""
    try:
        stats_path = os.path.join(DOWNLOAD_DIR, demo_name.replace('.dem', '.json'))
        if not os.path.exists(stats_path):
            return jsonify({'error': 'Stats not found'}), 404
            
        with open(stats_path, 'r') as f:
            stats = json.load(f)
            
        return jsonify({'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000) 