"""Garmin Connect login with a saved token, so the password is only needed when the token expires.

The email comes from GARMIN_EMAIL. The password comes from GARMIN_PASSWORD or, on macOS, from the
Keychain (service "garmin-connect", account = your email). Never write it in a file.
"""

import os
import subprocess
from pathlib import Path

from garminconnect import Garmin

TOKEN_DIR = Path(os.environ.get("GARMIN_TOKEN_DIR", Path.home() / ".garmin-claude"))


def _password(email: str) -> str:
    if os.environ.get("GARMIN_PASSWORD"):
        return os.environ["GARMIN_PASSWORD"]
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-a", email, "-s", "garmin-connect", "-w"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise SystemExit(
            "No Garmin password found. Set GARMIN_PASSWORD, or on macOS run:\n"
            f'  security add-generic-password -a "{email}" -s garmin-connect -w'
        )


def get_client() -> Garmin:
    try:
        g = Garmin()
        g.login(tokenstore=str(TOKEN_DIR))
        return g
    except Exception:
        pass
    email = os.environ.get("GARMIN_EMAIL")
    if not email:
        raise SystemExit("Set GARMIN_EMAIL to log in for the first time.")
    g = Garmin(email, _password(email))
    g.login()
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    g.garth.dump(str(TOKEN_DIR))
    return g
