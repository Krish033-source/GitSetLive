"""Fernet encryption for secrets stored at rest (GitHub tokens, per-repo env vars).

Key resolution order:
  1. ENCRYPTION_KEY environment variable (recommended in production)
  2. DATA_DIR/.encryption_key (auto-generated on first run in development)
"""

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

import config

log = logging.getLogger("gitsetlive.encryption")


def _load_key() -> bytes:
    env_key = (os.getenv("ENCRYPTION_KEY") or "").strip()
    if env_key:
        return env_key.encode()

    key_file = config.DATA_DIR / ".encryption_key"
    if key_file.exists():
        return key_file.read_text().strip().encode()

    key = Fernet.generate_key()
    key_file.write_text(key.decode())
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    if config.IS_PROD:
        log.warning(
            "ENCRYPTION_KEY not set — generated %s. On ephemeral disks this key is lost "
            "on redeploy and every stored token becomes unreadable. Set ENCRYPTION_KEY.",
            key_file,
        )
    return key


_fernet = Fernet(_load_key())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None
