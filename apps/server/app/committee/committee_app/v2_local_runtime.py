"""Local key and access-code management for the integrated service."""

import secrets
from pathlib import Path

from .v2_core import Runtime


def local_runtime(folder: Path) -> tuple[Runtime, str]:
    """Preserve keys across restarts. Never replace keys for an existing DB."""
    folder.mkdir(parents=True, exist_ok=True)
    key_file, db_path = folder / "keys.bin", folder / "admin.sqlite3"
    if not key_file.exists():
        if db_path.exists():
            raise ValueError("Existing database has no key file. Restore its original keys.")
        with key_file.open("xb") as stream:
            stream.write(secrets.token_bytes(96))
        key_file.chmod(0o600)
    keys = key_file.read_bytes()
    if len(keys) != 96:
        raise ValueError("Invalid local key file")
    access_file = folder / "access-code.txt"
    if not access_file.exists():
        with access_file.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
        access_file.chmod(0o600)
    return Runtime(db_path, pii_key=keys[:32], lookup_key=keys[32:64], auth_key=keys[64:]), (
        access_file.read_text(encoding="utf-8").strip()
    )
