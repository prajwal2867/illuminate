from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "illuminate.db"
QR_DIRECTORY = BASE_DIR / "generated_qr"

app = Flask(__name__)
QR_DIRECTORY.mkdir(exist_ok=True)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                mobile_number TEXT NOT NULL,
                illuminate_id TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                qr_filename TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def normalize_date(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        return None

    try:
        parsed_date = datetime.strptime(digits, "%d%m%Y")
    except ValueError:
        return None

    return parsed_date.strftime("%d / %m / %Y")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"{salt.hex()}:{digest.hex()}"


@app.get("/")
def registration_page():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/styles.css")
def static_styles():
    return send_from_directory(BASE_DIR, "styles.css")


@app.get("/India_flag.png")
def india_flag():
    return send_from_directory(BASE_DIR, "India_flag.png")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.post("/generate-ticket")
def generate_ticket():
    form = request.form
    required_fields = (
        "full-name",
        "email",
        "mobile-number",
        "illuminate-id",
        "password",
        "confirm-password",
        "date-of-birth",
    )

    if any(not form.get(field, "").strip() for field in required_fields):
        return "Please complete every field before generating your e-ticket.", 400

    if form["password"] != form["confirm-password"]:
        return "The passwords do not match.", 400

    date_of_birth = normalize_date(form["date-of-birth"])
    if date_of_birth is None:
        return "Enter a valid date of birth in DD / MM / YYYY format.", 400

    ticket_id = secrets.token_urlsafe(12)
    qr_filename = f"{ticket_id}.png"
    ticket_url = url_for("ticket_page", ticket_id=ticket_id, _external=True)
    qr_code = qrcode.QRCode(version=None, box_size=10, border=4)
    qr_code.add_data(ticket_url)
    qr_code.make(fit=True)
    qr_code.make_image(fill_color="black", back_color="white").save(QR_DIRECTORY / qr_filename)

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO tickets (
                ticket_id, full_name, email, mobile_number, illuminate_id,
                password_hash, date_of_birth, qr_filename, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                form["full-name"].strip(),
                form["email"].strip(),
                form["mobile-number"].strip(),
                form["illuminate-id"].strip(),
                hash_password(form["password"]),
                date_of_birth,
                qr_filename,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    return redirect(url_for("ticket_page", ticket_id=ticket_id))


@app.get("/ticket/<ticket_id>")
def ticket_page(ticket_id: str):
    with get_connection() as connection:
        ticket = connection.execute(
            "SELECT ticket_id, illuminate_id, qr_filename FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()

    if ticket is None:
        abort(404)

    return render_template("ticket.html", ticket=ticket)


@app.get("/generated_qr/<filename>")
def generated_qr(filename: str):
    return send_from_directory(QR_DIRECTORY, filename)


initialize_database()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
