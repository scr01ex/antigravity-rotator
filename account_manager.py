#!/usr/bin/env python3
import http.server
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional

from auth import (
    load_accounts,
    save_accounts,
    import_from_keychain,
    import_from_ide,
    ensure_valid_token,
    parse_jwt_email,
)
from config import (
    HOST,
    PORT,
    UPSTREAM_URL,
    IDE_SETTINGS_FILE,
    OAUTH_CLIENTS,
    OAUTH_TOKEN_URL,
)


def check_for_duplicate(new_email: str, new_refresh_token: str, target_name: str) -> Optional[dict]:
    accounts = load_accounts()
    for acc in accounts:
        if acc.get("name") == target_name:
            continue

        if new_email and acc.get("email") and new_email.lower() == acc.get("email").lower():
            return acc

        if new_refresh_token and acc.get("refresh_token") == new_refresh_token:
            return acc

    return None


def add_or_update_account(account: dict) -> bool:
    name = account["name"]
    email = account.get("email", "")
    rt = account.get("refresh_token", "")

    dup = check_for_duplicate(email, rt, name)
    if dup:
        print(f"[WARN] Duplicate account detected: '{email or rt[:20]}' already saved as '{dup['name']}'.")
        print(f"[ERROR] Registration of '{name}' cancelled.")
        return False

    accounts = load_accounts()
    existing = next((a for a in accounts if a["name"] == name), None)
    if existing:
        accounts.remove(existing)
        print(f"[INFO] Updating existing account '{name}'...")

    accounts.append(account)
    save_accounts(accounts)
    return True


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<body style="font-family: system-ui, sans-serif; text-align: center; padding-top: 50px;">
    <h2 style="color: #059669;">Authorization Successful</h2>
    <p>Authentication complete. You may close this window and return to your terminal.</p>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error: Missing authorization code.")

    def log_message(self, format, *args):
        pass


def cmd_login_browser(name: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        callback_port = s.getsockname()[1]

    client = OAUTH_CLIENTS[0]
    client_id = client["client_id"]
    client_secret = client["client_secret"]
    redirect_uri = f"http://localhost:{callback_port}/oauth-callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": (
            "https://www.googleapis.com/auth/cloud-platform "
            "https://www.googleapis.com/auth/userinfo.email "
            "https://www.googleapis.com/auth/userinfo.profile "
            "https://www.googleapis.com/auth/cclog "
            "https://www.googleapis.com/auth/experimentsandconfigs"
        ),
        "access_type": "offline",
        "prompt": "select_account consent",
    }

    login_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    print(f"[INFO] Initiating browser authentication for '{name}'")
    print(f"[INFO] If browser does not open automatically, visit:\n{login_url}\n")

    server = http.server.HTTPServer(("localhost", callback_port), OAuthCallbackHandler)
    server.timeout = 180

    webbrowser.open(login_url)
    print("[INFO] Awaiting callback on local listener...")

    server.handle_request()

    code = OAuthCallbackHandler.auth_code
    if not code:
        print("[ERROR] Authorization aborted or request timed out.")
        return

    print("[INFO] Exchanging authorization code for OAuth tokens...")
    token_data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode("utf-8")

    req = urllib.request.Request(OAUTH_TOKEN_URL, data=token_data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            expires_in = data.get("expires_in", 3600)
            email = parse_jwt_email(data.get("id_token", ""))

            if not refresh_token:
                print("[ERROR] Upstream OAuth did not return a refresh_token.")
                return

            account = {
                "name": name,
                "email": email,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": time.time() + expires_in,
                "status": "active",
                "cooldown_until": 0,
                "source": "browser",
            }

            if add_or_update_account(account):
                print(f"[OK] Account '{name}' registered successfully.")
                print(f"     Email: {email}")

    except urllib.error.HTTPError as e:
        print(f"[ERROR] Token exchange failed: HTTP {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"[ERROR] Connection failure during token exchange: {e}")


def cmd_import(name: str, source: str = "auto") -> None:
    imported = None
    source_name = ""

    if source == "ide":
        imported = import_from_ide(name)
        source_name = "Antigravity IDE"
    elif source == "cli":
        imported = import_from_keychain(name)
        source_name = "Antigravity CLI (Keychain)"
    else:
        ide_acc = import_from_ide(name)
        cli_acc = import_from_keychain(name)
        existing_emails = {a.get("email") for a in load_accounts() if a.get("email")}

        if ide_acc and ide_acc.get("email") not in existing_emails:
            imported = ide_acc
            source_name = "Antigravity IDE"
        elif ide_acc:
            imported = ide_acc
            source_name = "Antigravity IDE"
        elif cli_acc:
            imported = cli_acc
            source_name = "Antigravity CLI"

    if not imported:
        print(f"[ERROR] Could not extract active session from {source_name or 'any detected source'}.")
        return

    if add_or_update_account(imported):
        print(f"[OK] Account '{name}' imported from [{source_name}].")
        print(f"     Email: {imported.get('email', 'unknown')}")


def cmd_list() -> None:
    accounts = load_accounts()
    if not accounts:
        print("[INFO] Account pool is empty.")
        print("       Use 'python3 account_manager.py login <name>' to register an account.")
        return

    now = time.time()
    header_fmt = "{:<12} {:<32} {:<12} {:<10} {:<12}"
    print("-" * 80)
    print(header_fmt.format("NAME", "EMAIL", "SOURCE", "STATUS", "COOLDOWN"))
    print("-" * 80)
    for a in accounts:
        name = a.get("name", "-")
        email = a.get("email", "-") or "-"
        src = a.get("source", "-")
        cooldown_until = a.get("cooldown_until", 0)

        if cooldown_until > now:
            rem = int(cooldown_until - now)
            status = "COOLDOWN"
            cooldown_str = f"{rem // 60}m {rem % 60}s"
        else:
            status = "ACTIVE"
            cooldown_str = "ready"

        print(header_fmt.format(name, email, src, status, cooldown_str))
    print("-" * 80)


def cmd_remove(name: str) -> None:
    accounts = load_accounts()
    filtered = [a for a in accounts if a.get("name") != name]
    if len(filtered) == len(accounts):
        print(f"[WARN] Account '{name}' not found.")
        return
    save_accounts(filtered)
    print(f"[OK] Account '{name}' removed.")


def cmd_test() -> None:
    accounts = load_accounts()
    if not accounts:
        print("[WARN] No accounts available to test.")
        return

    print("[INFO] Validating accounts via Google Cloud Code API...\n")
    for a in accounts:
        name = a.get("name")
        email = a.get("email", "no-email")
        print(f"Testing [{name}] ({email})... ", end="", flush=True)

        token = ensure_valid_token(a, persist=True)
        if not token:
            print("FAILED (Token refresh failed)")
            continue

        test_url = f"{UPSTREAM_URL}/v1internal:fetchAvailableModels"
        req = urllib.request.Request(
            test_url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "AntigravityRotator/1.0",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    print("OK (HTTP 200)")
                else:
                    print(f"WARN (HTTP {resp.status})")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("FAILED (HTTP 429 Quota Exceeded)")
            else:
                print(f"FAILED (HTTP {e.code})")
        except Exception as e:
            print(f"FAILED ({e})")

    save_accounts(accounts)


def configure_ide(silent: bool = False) -> None:
    if not IDE_SETTINGS_FILE.exists():
        settings = {}
    else:
        try:
            settings = json.loads(IDE_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}

    target_url = f"http://{HOST}:{PORT}"
    if settings.get("jetski.cloudCodeUrl") == target_url:
        return

    settings["jetski.cloudCodeUrl"] = target_url
    IDE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDE_SETTINGS_FILE.write_text(json.dumps(settings, indent=4, ensure_ascii=False), encoding="utf-8")
    if not silent:
        print(f"[OK] Antigravity IDE configuration updated:")
        print(f"     'jetski.cloudCodeUrl': '{target_url}'")
        print(f"     Settings file: {IDE_SETTINGS_FILE}")


def unconfigure_ide(silent: bool = False) -> None:
    if not IDE_SETTINGS_FILE.exists():
        if not silent:
            print("[INFO] IDE settings.json not found.")
        return

    try:
        settings = json.loads(IDE_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if "jetski.cloudCodeUrl" in settings:
        del settings["jetski.cloudCodeUrl"]
        IDE_SETTINGS_FILE.write_text(json.dumps(settings, indent=4, ensure_ascii=False), encoding="utf-8")
        if not silent:
            print("[OK] Parameter 'jetski.cloudCodeUrl' removed from IDE settings. Default restored.")
    else:
        if not silent:
            print("[INFO] 'jetski.cloudCodeUrl' is not present in settings.")


def cmd_configure_ide() -> None:
    configure_ide(silent=False)


def cmd_unconfigure_ide() -> None:
    unconfigure_ide(silent=False)


def print_help() -> None:
    print("""Antigravity Account Manager CLI:
----------------------------------------
  python3 account_manager.py login <name>       - Authenticate new account via browser
  python3 account_manager.py import-ide <name>   - Import current account from Antigravity IDE
  python3 account_manager.py import-cli <name>   - Import current account from Antigravity CLI
  python3 account_manager.py list               - List all registered accounts and status
  python3 account_manager.py test               - Validate API token connectivity for all accounts
  python3 account_manager.py remove <name>      - Remove account from pool
  python3 account_manager.py configure-ide      - Configure Antigravity IDE to route via proxy
  python3 account_manager.py unconfigure-ide    - Revert Antigravity IDE settings to default
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "login" and len(sys.argv) > 2:
        cmd_login_browser(sys.argv[2])
    elif cmd == "import" and len(sys.argv) > 2:
        cmd_import(sys.argv[2], source="auto")
    elif cmd in ("import-ide", "ide") and len(sys.argv) > 2:
        cmd_import(sys.argv[2], source="ide")
    elif cmd in ("import-cli", "cli") and len(sys.argv) > 2:
        cmd_import(sys.argv[2], source="cli")
    elif cmd == "list":
        cmd_list()
    elif cmd == "remove" and len(sys.argv) > 2:
        cmd_remove(sys.argv[2])
    elif cmd == "test":
        cmd_test()
    elif cmd == "configure-ide":
        cmd_configure_ide()
    elif cmd == "unconfigure-ide":
        cmd_unconfigure_ide()
    else:
        print_help()
