from __future__ import annotations

from datetime import datetime, timezone
from getpass import getpass

from database import admins


def hash_password(password: str) -> str:
    import hashlib
    import secrets

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"{salt.hex()}:{digest.hex()}"


admin_name = " ".join(input("Admin name: ").split())
admin_code = getpass("Admin code: ").strip()

if not admin_name or not admin_code:
    raise SystemExit("Admin name and code are required.")

admins.update_one(
    {"nameNormalized": admin_name.casefold()},
    {"$set": {
        "name": admin_name,
        "nameNormalized": admin_name.casefold(),
        "codeHash": hash_password(admin_code),
        "role": "admin",
        "active": True,
        "createdAt": datetime.now(timezone.utc),
    }},
    upsert=True,
)

print(f"Admin account ready: {admin_name}")