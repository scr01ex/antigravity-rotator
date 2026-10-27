#!/usr/bin/env python3
import atexit
import http.client
import logging
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from typing import Optional

from account_manager import configure_ide, unconfigure_ide
from auth import load_accounts, save_accounts, refresh_account_token
from config import (
    HOST, PORT, UPSTREAM_URL, COOLDOWN_SECONDS, UPSTREAM_TIMEOUT,
    LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT,
)

_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)
_root_logger.addHandler(_console_handler)

_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)
_root_logger.addHandler(_file_handler)

logger = logging.getLogger("rotator")


def _handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = _handle_uncaught_exception


def notify_desktop(title: str, text: str) -> None:
    try:
        if sys.platform == "darwin":
            cmd = f'display notification "{text}" with title "{title}"'
            subprocess.run(["osascript", "-e", cmd], capture_output=True, check=False)
        elif sys.platform == "win32":
            ps_script = (
                f"[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null; "
                f"$notify = new-object system.windows.forms.notifyicon; "
                f"$notify.icon = [system.drawing.systemicons]::Information; "
                f"$notify.visible = $true; "
                f"$notify.showballoontip(5000, '{title}', '{text}', [system.windows.forms.tooltipicon]::Info)"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, check=False)
    except (FileNotFoundError, OSError):
        pass


class AccountPool:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_index = 0

    def get_next_available_account(self, exclude_names: Optional[set] = None) -> tuple[Optional[dict], int]:
        if exclude_names is None:
            exclude_names = set()

        with self.lock:
            accounts = load_accounts()
            if not accounts:
                return None, -1

            now = time.time()
            n = len(accounts)

            for i in range(n):
                idx = (self.current_index + i) % n
                acc = accounts[idx]
                if acc.get("name") in exclude_names:
                    continue
                if acc.get("cooldown_until", 0) <= now:
                    self.current_index = idx
                    return acc, idx

            available = [a for a in accounts if a.get("name") not in exclude_names]
            if available:
                best = min(available, key=lambda a: a.get("cooldown_until", 0))
                idx = accounts.index(best)
                self.current_index = idx
                return best, idx

            return None, -1

    def ensure_account_token(self, account: dict) -> Optional[str]:
        now = time.time()
        expires_at = account.get("expires_at") or account.get("expiry") or 0

        if account.get("access_token") and now < expires_at - 120:
            return account["access_token"]

        with self.lock:
            accounts = load_accounts()
            target = next((a for a in accounts if a.get("name") == account.get("name")), None)
            target_expires_at = (target.get("expires_at") or target.get("expiry") or 0) if target else 0
            if target and target.get("access_token") and now < target_expires_at - 120:
                account.update(target)
                return account["access_token"]

            if not refresh_account_token(account):
                return None

            if target:
                target.update(account)
            else:
                accounts.append(account)
            save_accounts(accounts)

            return account.get("access_token")

    def mark_cooldown(self, account_name: str) -> None:
        with self.lock:
            accounts = load_accounts()
            for acc in accounts:
                if acc.get("name") == account_name:
                    acc["cooldown_until"] = time.time() + COOLDOWN_SECONDS
                    logger.warning(
                        "Account '%s' entered cooldown for %d seconds",
                        account_name,
                        COOLDOWN_SECONDS,
                    )
                    break
            save_accounts(accounts)


pool = AccountPool()


class RotatorProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self._handle_request("HEAD")

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def do_PUT(self):
        self._handle_request("PUT")

    def do_DELETE(self):
        self._handle_request("DELETE")

    def do_OPTIONS(self):
        self._handle_request("OPTIONS")

    def log_message(self, format, *args):
        pass

    def _handle_request(self, method: str):
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer_encoding:
            chunks = []
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                chunk_size_str = line.split(b";")[0].strip()
                if not chunk_size_str:
                    break
                try:
                    chunk_size = int(chunk_size_str, 16)
                except ValueError:
                    break
                if chunk_size == 0:
                    self.rfile.readline()
                    break
                chunk_data = self.rfile.read(chunk_size)
                self.rfile.readline()
                chunks.append(chunk_data)
            body = b"".join(chunks)
        else:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else None

        req_path = self.path
        if req_path.startswith("http://") or req_path.startswith("https://"):
            parsed = urllib.parse.urlsplit(req_path)
            req_path = parsed.path
            if parsed.query:
                req_path += f"?{parsed.query}"

        upstream_parsed = urllib.parse.urlparse(UPSTREAM_URL)
        upstream_host = upstream_parsed.hostname
        upstream_port = upstream_parsed.port or (443 if upstream_parsed.scheme == "https" else 80)

        attempted_accounts = set()
        max_attempts = max(1, len(load_accounts()))
        clean_path = req_path.split("?")[0]
        req_start_time = time.time()
        headers_sent = False

        headers_to_send = {}
        for k, v in self.headers.items():
            if k.lower() not in ("host", "authorization", "content-length", "transfer-encoding", "connection"):
                headers_to_send[k] = v

        headers_to_send["Host"] = upstream_host
        headers_to_send["Connection"] = "close"
        if body is not None:
            headers_to_send["Content-Length"] = str(len(body))

        for _ in range(max_attempts):
            account, _ = pool.get_next_available_account(exclude_names=attempted_accounts)
            if not account:
                if not headers_sent:
                    self.send_error(503, "All accounts in cooldown or none configured")
                return

            acc_name = account.get("name")
            attempted_accounts.add(acc_name)

            token = pool.ensure_account_token(account)
            if not token:
                logger.error("Failed to refresh token for '%s', skipping", acc_name)
                pool.mark_cooldown(acc_name)
                continue

            headers_to_send["Authorization"] = f"Bearer {token}"
            conn = None

            try:
                is_https = upstream_parsed.scheme == "https"
                conn_cls = http.client.HTTPSConnection if is_https else http.client.HTTPConnection
                conn = conn_cls(upstream_host, upstream_port, timeout=UPSTREAM_TIMEOUT)
                conn.request(method, req_path, body=body, headers=headers_to_send)
                resp = conn.getresponse()

                if resp.status == 429:
                    err_preview = resp.read(256).decode("utf-8", errors="ignore").strip()
                    logger.warning(
                        "HTTP 429 quota exceeded on account '%s': %s",
                        acc_name,
                        err_preview,
                    )
                    pool.mark_cooldown(acc_name)
                    conn.close()

                    notify_desktop(
                        "Antigravity Rotator",
                        f"Quota exceeded for '{acc_name}'. Switched to next account.",
                    )
                    continue

                elapsed = time.time() - req_start_time
                logger.info("%s %s -> %d (account: %s) [%.2fs]", method, clean_path, resp.status, acc_name, elapsed)

                self.send_response(resp.status, resp.reason)

                has_content_length = False
                for header, val in resp.getheaders():
                    h_lower = header.lower()
                    if h_lower == "content-length":
                        has_content_length = True
                    if h_lower not in ("transfer-encoding", "connection"):
                        self.send_header(header, val)

                use_chunked = not has_content_length
                if use_chunked:
                    self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")

                self.end_headers()
                headers_sent = True

                while True:
                    try:
                        chunk = resp.read1(65536)
                    except (http.client.IncompleteRead, TimeoutError) as e:
                        logger.warning("Upstream read timeout/incomplete for %s via '%s': %s", clean_path, acc_name, e)
                        break

                    if not chunk:
                        break

                    try:
                        if use_chunked:
                            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                        else:
                            self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        logger.info("Client closed connection for %s", clean_path)
                        conn.close()
                        return

                if use_chunked:
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                conn.close()
                return

            except Exception as e:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

                if headers_sent:
                    logger.warning("Streaming failed mid-response for %s via '%s': %s", clean_path, acc_name, e)
                    return

                logger.error("Connection error for %s via '%s': %s", clean_path, acc_name, e)
                continue

        if not headers_sent:
            self.send_error(502, "All accounts exhausted or upstream unavailable")


def run_server():
    configure_ide(silent=True)
    logger.info("Antigravity Proxy Rotator listening on http://%s:%d", HOST, PORT)
    logger.info("Upstream URL: %s", UPSTREAM_URL)
    logger.info("Auto-configured Antigravity IDE ('jetski.cloudCodeUrl' -> http://%s:%d)", HOST, PORT)

    def _cleanup():
        try:
            unconfigure_ide(silent=True)
            logger.info("Restored default Antigravity IDE configuration (proxy unlinked)")
        except Exception as e:
            logger.warning("Error during IDE unconfigure cleanup: %s", e)

    atexit.register(_cleanup)

    def _sig_handler(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    if hasattr(signal, "SIGHUP") and signal.getsignal(signal.SIGHUP) != signal.SIG_IGN:
        signal.signal(signal.SIGHUP, _sig_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _sig_handler)

    server_address = (HOST, PORT)
    httpd = ThreadingHTTPServer(server_address, RotatorProxyHandler)

    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Stopping proxy server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
