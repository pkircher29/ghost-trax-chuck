import os
import sys
import json
import urllib.request
import urllib.error

API_URL = "https://api.auto-kj.com/api/verify-license"

def show_error(title, message):
    # Try GUI error message if tkinter is available and we are running interactive
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        print(f"[{title}] {message}", file=sys.stderr)

def prompt_license_gui():
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog
        
        root = tk.Tk()
        root.withdraw()
        
        email = simpledialog.askstring("Ghost-Trax License Required", "Enter your registered email address:")
        if not email:
            return None, None
            
        token = simpledialog.askstring("Ghost-Trax License Required", "Enter your Host App API Token / Connection Key:")
        if not token:
            return None, None
            
        root.destroy()
        return email.strip(), token.strip()
    except Exception:
        return None, None

def prompt_license_cli():
    print("\n--- GHOST-TRAX STANDALONE LICENSE REQUIRED ---")
    try:
        email = input("Enter your registered email: ").strip()
        token = input("Enter your Host App API Connection Token: ").strip()
        return email, token
    except (KeyboardInterrupt, EOFError):
        return None, None

def verify_license():
    config_dir = os.path.expanduser("~/.ghosttrax")
    config_path = os.path.join(config_dir, "license.json")
    
    email = None
    token = None
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                email = config.get("email")
                token = config.get("token")
        except Exception:
            pass

    if not email or not token:
        # Prompt user
        if len(sys.argv) <= 1:
            email, token = prompt_license_gui()
            if not email or not token:
                email, token = prompt_license_cli()
        else:
            email, token = prompt_license_cli()

        if not email or not token:
            show_error("License Verification Failed", "Ghost-Trax requires an active paid license key. Please check your auto-kj.com dashboard.")
            sys.exit(1)

    # Call verification endpoint
    payload = json.dumps({"email": email, "token": token}).encode('utf-8')
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode('utf-8'))
            if res.get("status") == "active":
                # Save valid license details
                os.makedirs(config_dir, exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump({"email": email, "token": token}, f)
                return True
            else:
                show_error("License Blocked", f"Verification failed: {res.get('message', 'Subscription tier invalid.')}")
                # Remove cached file if invalid
                if os.path.exists(config_path):
                    os.remove(config_path)
                sys.exit(1)
    except urllib.error.URLError as e:
        # Offline/Timeout validation bypass logic
        # If the local license.json file already exists, let's allow it temporarily to support offline gigs
        if os.path.exists(config_path):
            print("[Ghost-Trax] Connection failed. Using cached offline license.", file=sys.stderr)
            return True
        else:
            show_error("License Verification Offline", "Could not reach server to verify license key, and no cached key was found.")
            sys.exit(1)
