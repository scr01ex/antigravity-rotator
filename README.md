# Antigravity Proxy Rotator

A local HTTP proxy and multi-account credential rotator for **Antigravity** (including **Antigravity IDE** and **Antigravity 2.0**) and **Antigravity CLI**.

## Key Features

- **Transparent Network-Level Failover:** Intercepts HTTP 429 (`RESOURCE_EXHAUSTED`) status codes and rotates to the next available account without dropping the active session in Antigravity.
- **Automated OAuth Refresh & Disk Persistence:** Automatically handles Google OAuth `access_token` refreshes prior to token expiration and immediately synchronizes state to disk.
- **Server-Sent Events (SSE) / Streaming:** Supports `Transfer-Encoding: chunked` for real-time model completions without buffering latency.
- **Duplicate Prevention:** Prevents duplicate registration of the same Google account under different identifiers.
- **Native Desktop Notifications (macOS & Windows):** Dispatches native system notifications on account exhaustion and rotation (via `osascript` on macOS and PowerShell `NotifyIcon` on Windows).
- **Cross-Platform Support:** Works seamlessly on macOS, Windows, and Linux.
- **Zero Third-Party Dependencies:** Implemented entirely using Python's standard library.

---

## Configuration

Configuration values can be provided via environment variables or a local `.env` file (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `ROTATOR_HOST` | `127.0.0.1` | Local bind address |
| `ROTATOR_PORT` | `8888` | Local listen port |
| `UPSTREAM_URL` | `https://daily-cloudcode-pa.googleapis.com` | Google Cloud Code upstream endpoint |
| `COOLDOWN_SECONDS` | `1800` | Account cooldown duration after HTTP 429 (seconds) |
| `ACCOUNTS_FILE` | `./accounts.json` | Path to persistent accounts database |
| `IDE_SETTINGS_FILE` | `Platform default` | Path to Antigravity `settings.json` (auto-detected on macOS, Windows, Linux) |
| `ROTATOR_LOG_MAX_BYTES` | `5242880 (5 MB)` | Maximum log file size before rotation |
| `ROTATOR_LOG_BACKUP_COUNT` | `2` | Number of rotated log backup archives to keep |

---

## Adding Accounts

> [!TIP]
> On Windows, use `python` instead of `python3` (e.g., `python account_manager.py login <name>`).

### Method 1: Interactive Browser Login (Recommended)

Run:
```bash
python3 account_manager.py login <name>
```
This starts a temporary local HTTP callback server and opens the Google OAuth authorization prompt with `prompt=select_account consent` to allow selecting any target Google account.

### Method 2: Import from Active Antigravity Session

Extracts credentials directly from the local Antigravity database (`state.vscdb`):
```bash
python3 account_manager.py import-ide <name>
```

### Method 3: Import from Antigravity CLI Session

Extracts credentials from the system credential store / macOS Keychain (`security find-generic-password`):
```bash
python3 account_manager.py import-cli <name>
```

---

## Account Verification

List all configured accounts and cooldown statuses:
```bash
python3 account_manager.py list
```

Validate API connectivity and token health against Google Cloud Code:
```bash
python3 account_manager.py test
```

---

## Running the Proxy

The proxy features **automated Antigravity lifecycle management**:
- Starting the proxy automatically configures Antigravity (IDE, Desktop 2.0, and CLI) to route requests via the local rotator (`http://127.0.0.1:8888`).
- Stopping the proxy (or closing the terminal) intercepts OS signals (`SIGHUP`, `SIGINT`, `SIGTERM`, `SIGBREAK`) and immediately restores default Google Cloud Code configuration.

### macOS & Linux

```bash
./run.sh start    # Start in background
./run.sh status   # Check daemon & account health
./run.sh logs     # Follow real-time logs
./run.sh stop     # Stop daemon & restore Antigravity settings
```
*Foreground mode (Ctrl+C to stop):* `./run.sh`

---

### Windows

```cmd
run.bat start    :: Start in background (PowerShell: .\run.bat start)
run.bat status   :: Check status (PowerShell: .\run.bat status)
run.bat logs     :: Follow logs (PowerShell: .\run.bat logs)
run.bat stop     :: Stop daemon (PowerShell: .\run.bat stop)
```
*Foreground mode (Ctrl+C to stop):* `run.bat` *(PowerShell: `.\run.bat`)*

---

## CLI Reference

| Command | Description |
|---|---|
| `python3 account_manager.py login <name>` | Authenticate account via browser |
| `python3 account_manager.py import-ide <name>` | Import credentials from active Antigravity session |
| `python3 account_manager.py import-cli <name>` | Import credentials from Antigravity CLI |
| `python3 account_manager.py list` | List accounts, sources, and cooldown timers |
| `python3 account_manager.py test` | Validate tokens and upstream API status |
| `python3 account_manager.py remove <name>` | Remove account from pool |
| `python3 account_manager.py configure-ide` | Configure Antigravity `settings.json` to route via proxy |
| `python3 account_manager.py unconfigure-ide` | Restore default Antigravity `settings.json` |
