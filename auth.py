import base64
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from config import ACCOUNTS_FILE, IDE_USER_DIR, OAUTH_CLIENTS, OAUTH_TOKEN_URL

logger = logging.getLogger("auth")


def load_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.is_file():
        return []
    try:
        return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read accounts file %s: %s", ACCOUNTS_FILE, e)
        return []


def save_accounts(accounts: list[dict]) -> None:
    temp_file = ACCOUNTS_FILE.with_suffix(".tmp")
    data = json.dumps(accounts, indent=2, ensure_ascii=False)
    temp_file.write_text(data, encoding="utf-8")
    temp_file.replace(ACCOUNTS_FILE)


def sync_account_to_disk(account: dict) -> None:
    accounts = load_accounts()
    for idx, acc in enumerate(accounts):
        if acc.get("name") == account.get("name"):
            accounts[idx] = account
            save_accounts(accounts)
            return
    accounts.append(account)
    save_accounts(accounts)


def parse_jwt_email(id_token: str) -> str:
    if not id_token:
        return ""
    try:
        parts = id_token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
            return data.get("email", "")
    except Exception:
        pass
    return ""


def refresh_account_token(account: dict) -> bool:
    refresh_tok = account.get("refresh_token")
    account_name = account.get("name", "unknown")
    if not refresh_tok:
        logger.warning("Account '%s' has no refresh_token", account_name)
        return False

    for client in OAUTH_CLIENTS:
        post_data = urllib.parse.urlencode({
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
        }).encode("utf-8")

        req = urllib.request.Request(OAUTH_TOKEN_URL, data=post_data)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                new_access_token = data.get("access_token")
                expires_in = data.get("expires_in", 3600)
                if new_access_token:
                    account["access_token"] = new_access_token
                    account["expires_at"] = time.time() + expires_in
                    if "id_token" in data:
                        account["email"] = parse_jwt_email(data["id_token"])
                    return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if "unauthorized_client" in err_body or "invalid_client" in err_body:
                continue
            logger.error("Token refresh failed for '%s': HTTP %d - %s", account_name, e.code, err_body)
            return False
        except Exception as e:
            logger.error("Network error during token refresh for '%s': %s", account_name, e)
            return False

    logger.error("Failed to refresh token for '%s': all OAuth clients rejected request", account_name)
    return False


def ensure_valid_token(account: dict, persist: bool = False) -> Optional[str]:
    now = time.time()
    expires_at = account.get("expires_at") or account.get("expiry") or 0

    if not account.get("access_token") or now >= expires_at - 120:
        if not refresh_account_token(account):
            return None
        if persist:
            sync_account_to_disk(account)

    return account.get("access_token")


def import_from_ide(name: str) -> Optional[dict]:
    db_path = IDE_USER_DIR / "globalStorage/state.vscdb"
    if not db_path.is_file():
        return None

    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT value FROM ItemTable WHERE key = 'antigravityUnifiedStateSync.oauthToken'")
        row = c.fetchone()
        conn.close()

        if not row:
            return None

        raw = base64.b64decode(row[0])
        refresh_token = ""
        for match in re.finditer(rb"[A-Za-z0-9+/=_-]{100,}", raw):
            try:
                dec = base64.b64decode(match.group(0))
                rt_m = re.search(rb"1//[a-zA-Z0-9_.-]+", dec)
                if rt_m:
                    refresh_token = rt_m.group(0).decode("ascii")
                    break
            except Exception:
                pass

        if not refresh_token:
            return None

        account = {
            "name": name,
            "email": "",
            "access_token": "",
            "refresh_token": refresh_token,
            "expires_at": 0,
            "status": "active",
            "cooldown_until": 0,
            "source": "ide",
        }

        if refresh_account_token(account):
            return account
        return None
    except Exception as e:
        logger.error("Failed to import account from IDE database: %s", e)
        return None


def import_from_keychain(name: str) -> Optional[dict]:
    if sys.platform != "darwin":
        return None

    try:
        cmd = ["security", "find-generic-password", "-s", "gemini", "-a", "antigravity", "-w"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return None
    except (FileNotFoundError, OSError):
        return None

    raw = res.stdout.strip()
    if raw.startswith("go-keyring-base64:"):
        raw = raw[len("go-keyring-base64:"):]

    try:
        data = json.loads(base64.b64decode(raw).decode("utf-8"))
        tok_data = data.get("token", {})
        id_token = data.get("id_token", "")
        email = parse_jwt_email(id_token)

        access_token = tok_data.get("access_token", "")
        refresh_token_str = tok_data.get("refresh_token", "")
        expires_in = tok_data.get("expires_in", 3600)

        if not refresh_token_str:
            return None

        account = {
            "name": name,
            "email": email,
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "expires_at": time.time() + expires_in,
            "status": "active",
            "cooldown_until": 0,
            "source": "cli",
        }
        return account
    except Exception as e:
        logger.error("Failed to parse macOS Keychain entry: %s", e)
        return None
