import os
import sys
import threading
import time
import subprocess
import urllib.request
import django
from django.core.management import execute_from_command_line


# ═══════════════════════════════════════════════════════════
# PATH HELPERS
# ═══════════════════════════════════════════════════════════

def get_base_dir():
    """Base directory — .exe folder when frozen, project root otherwise."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════════════
# BROWSER LAUNCHER — Firefox first, then fallbacks
# ═══════════════════════════════════════════════════════════

def open_browser():
    """Launch the app in Firefox (preferred) or fallback to other browsers."""
    time.sleep(2)
    url = 'http://127.0.0.1:8000'

    # Wait until the Django server actually responds
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(1)

    # ─── 1. Firefox (client's preferred browser) ───
    firefox_paths = [
        r'C:\Program Files\Mozilla Firefox\firefox.exe',
        r'C:\Program Files (x86)\Mozilla Firefox\firefox.exe',
    ]
    for path in firefox_paths:
        if os.path.isfile(path):
            try:
                subprocess.Popen([path, '-new-window', url])
                print(f"  Browser: Firefox → {path}")
                return
            except Exception as e:
                print(f"  Firefox failed: {e}")

    # ─── 2. Chrome ───
    chrome_paths = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        os.path.expanduser(r'~\AppData\Local\Google\Chrome\Application\chrome.exe'),
    ]
    for path in chrome_paths:
        if os.path.isfile(path):
            try:
                subprocess.Popen([path, '--start-maximized', url])
                print(f"  Browser: Chrome → {path}")
                return
            except Exception:
                pass

    # ─── 3. Edge (Chromium) ───
    edge_paths = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    for path in edge_paths:
        if os.path.isfile(path):
            try:
                subprocess.Popen([path, '--start-maximized', url])
                print(f"  Browser: Edge → {path}")
                return
            except Exception:
                pass

    # ─── 4. System default ───
    try:
        os.startfile(url)
        print("  Browser: system default")
    except Exception:
        print(f"  ⚠ Please open manually: {url}")


# ═══════════════════════════════════════════════════════════
# DATABASE MIGRATIONS
# ═══════════════════════════════════════════════════════════

def run_migrations():
    """Run Django migrations to create tables if they don't exist."""
    print("=" * 55)
    print("  Checking database... Running migrations...")
    print("=" * 55)
    sys.stdout.flush()

    try:
        django.setup()
        execute_from_command_line([
            'manage.py', 'migrate', '--noinput', '--verbosity', '2'
        ])
        print("=" * 55)
        print("  Migrations completed successfully.")
        print("=" * 55)
        sys.stdout.flush()
        return True
    except Exception as e:
        print("=" * 55)
        print(f"  MIGRATION FAILED: {e}")
        print("=" * 55)
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        return False


# ═══════════════════════════════════════════════════════════
# DJANGO SERVER
# ═══════════════════════════════════════════════════════════

def start_django_server():
    """Start the Django development server (blocking)."""
    execute_from_command_line([
        'manage.py', 'runserver', '127.0.0.1:8000', '--noreload'
    ])


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'poyafar_business.settings')

    # Step 1: Migrate the database
    if not run_migrations():
        print("")
        print("The app cannot start because migrations failed.")
        print("Check the error message above.")
        print("")
        input("Press Enter to close...")
        sys.exit(1)

    # Step 2: Open browser in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Step 3: Show startup banner
    print("")
    print("=" * 55)
    print("  Poyafar App is running")
    print("  آدرس: http://127.0.0.1:8000")
    print("  برای بستن این پنجره را ببندید")
    print("=" * 55)
    print("")

    # Step 4: Start Django server (blocking)
    start_django_server()