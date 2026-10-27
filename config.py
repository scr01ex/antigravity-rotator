import codecs
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env_file(filepath: Path) -> None:
    if not filepath.is_file():
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


_load_env_file(BASE_DIR / ".env")

HOST = os.getenv("ROTATOR_HOST", "127.0.0.1")
PORT = int(os.getenv("ROTATOR_PORT", "8888"))
UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://daily-cloudcode-pa.googleapis.com")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "1800"))
UPSTREAM_TIMEOUT = int(os.getenv("UPSTREAM_TIMEOUT", "120"))

ACCOUNTS_FILE = Path(os.getenv("ACCOUNTS_FILE", str(BASE_DIR / "accounts.json"))).resolve()
LOG_FILE = Path(os.getenv("ROTATOR_LOG_FILE", str(BASE_DIR / "rotator.log"))).resolve()
LOG_MAX_BYTES = int(os.getenv("ROTATOR_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("ROTATOR_LOG_BACKUP_COUNT", "2"))

def get_ide_user_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData/Roaming"
        return base / "Antigravity IDE/User"
    elif sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Antigravity IDE/User"
    else:
        xdg_config = os.getenv("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        return base / "Antigravity IDE/User"


IDE_USER_DIR = get_ide_user_dir()
_custom_ide_settings = os.getenv("IDE_SETTINGS_FILE")
IDE_SETTINGS_FILE = (
    Path(_custom_ide_settings).resolve()
    if _custom_ide_settings
    else IDE_USER_DIR / "settings.json"
)

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

_DEFAULT_OAUTH_CLIENTS = [
    {
        "client_id": codecs.decode("1071006060591-gzuffva2u21yper235igbybwu4t403rc.nccf.tbbtyrhfrepbagrag.pbz", "rot_13"),
        "client_secret": codecs.decode("TBPFCK-X58SJE486YqYW1zYO8fKP4m6dQNs", "rot_13"),
    },
    {
        "client_id": codecs.decode("884354919052-36gep1wwo3gthvnp32bi6pbq268p5oyu.nccf.tbbtyrhfrepbagrag.pbz", "rot_13"),
        "client_secret": codecs.decode("TBPFCK-9LDJcS7EJQP0DGqw-LkXZjE0MgfK", "rot_13"),
    },
]

_custom_c1_id = os.getenv("OAUTH_CLIENT_ID_1")
_custom_c1_secret = os.getenv("OAUTH_CLIENT_SECRET_1")
_custom_c2_id = os.getenv("OAUTH_CLIENT_ID_2")
_custom_c2_secret = os.getenv("OAUTH_CLIENT_SECRET_2")

OAUTH_CLIENTS = []
if _custom_c1_id and _custom_c1_secret:
    OAUTH_CLIENTS.append({"client_id": _custom_c1_id, "client_secret": _custom_c1_secret})
if _custom_c2_id and _custom_c2_secret:
    OAUTH_CLIENTS.append({"client_id": _custom_c2_id, "client_secret": _custom_c2_secret})

if not OAUTH_CLIENTS:
    OAUTH_CLIENTS = _DEFAULT_OAUTH_CLIENTS

