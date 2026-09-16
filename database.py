from __future__ import annotations

import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "illuminate")

if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is missing. Add it to a local .env file.")

client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
database = client[MONGODB_DATABASE]
users = database["users"]
admins = database["admins"]
audit_logs = database["auditLogs"]


def check_connection() -> None:
    client.admin.command("ping")


if __name__ == "__main__":
    check_connection()
    print(f"Connected to MongoDB database: {MONGODB_DATABASE}")