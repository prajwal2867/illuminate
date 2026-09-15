from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "illuminate.db"
QR_DIRECTORY = BASE_DIR / "generated_qr"
ADMIN_CREDENTIALS = {
    "satvi sumedha": "a0578",
    "rupanjali": "a0483",
    "akshaya": "a0575",
    "umesh": "a05e9",
    "hansini": "a67f3",
    "anantha": "a0464",
    "advika": "a05gu",
    "srushti": "a6765",
    "gopika": "a66g7",
    "srishti": "a6653",
    "joel": "a67c4",
    "ali raza": "a66d0",
    "deekshith": "a0439",
    "sumanth": "a0541",
    "prajwal": "a66j2",
}

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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS attendees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                mobile_number TEXT NOT NULL,
                illuminate_id TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                qr_filename TEXT NOT NULL,
                created_at TEXT NOT NULL,
                scanned_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_illuminate_id_unique
            ON tickets (lower(illuminate_id))
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


def verify_password(password: str, stored_hash: str) -> bool:
    salt_hex, digest_hex = stored_hash.split(":", 1)
    candidate_digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), 240_000
    )
    return secrets.compare_digest(candidate_digest.hex(), digest_hex)


@app.get("/")
def registration_page():
    return render_template(
        "index.html",
        message=request.args.get("message"),
        message_type=request.args.get("message_type"),
    )


@app.get("/styles.css")
def static_styles():
    return send_from_directory(BASE_DIR, "styles.css")


@app.get("/India_flag.png")
def india_flag():
    return send_from_directory(BASE_DIR, "India_flag.png")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    message = None

    if request.method == "POST":
        admin_name = " ".join(request.form.get("admin-name", "").split()).casefold()
        admin_code = request.form.get("admin-code", "").strip().casefold()

        if ADMIN_CREDENTIALS.get(admin_name) == admin_code:
            display_name = " ".join(request.form["admin-name"].split())
            return render_template("admin_dashboard.html", admin_name=display_name)

        message = "The admin name or assigned code is incorrect, try again."

    return render_template("admin_login.html", message=message)


def ticket_row_for_display(row: sqlite3.Row) -> dict:
    return {
        "full_name": row["full_name"],
        "email": row["email"],
        "mobile_number": row["mobile_number"],
        "illuminate_id": row["illuminate_id"],
        "password": "Protected",
        "date_of_birth": row["date_of_birth"],
        "qr_filename": row["qr_filename"],
    }


@app.get("/admin/database")
def admin_database():
    filter_by = request.args.get("filter", "full_name")
    search = request.args.get("search", "").strip()
    allowed_filters = {
        "full_name": "full_name",
        "email": "email",
        "mobile_number": "mobile_number",
        "illuminate_id": "illuminate_id",
    }
    column = allowed_filters.get(filter_by, "full_name")

    with get_connection() as connection:
        if search:
            rows = connection.execute(
                f"SELECT * FROM tickets WHERE lower({column}) LIKE lower(?) ORDER BY id DESC",
                (f"%{search}%",),
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()

    return {"records": [ticket_row_for_display(row) for row in rows]}


@app.get("/admin/attendees")
def admin_attendees():
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM attendees ORDER BY id DESC").fetchall()

    return {"records": [ticket_row_for_display(row) for row in rows]}


@app.post("/admin/scan")
def admin_scan():
    payload = request.get_json(silent=True) or {}
    qr_value = str(payload.get("qr_value", "")).strip()
    parsed_path = urlparse(qr_value).path
    match = re.fullmatch(r"/ticket/([^/]+)", parsed_path)
    ticket_id = match.group(1) if match else qr_value.rsplit("/", 1)[-1]

    if not ticket_id:
        return {"success": False, "message": "Invalid QR code."}, 400

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ticket = connection.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if ticket is None:
            return {"success": False, "message": "QR code is not valid or has already been scanned."}, 404

        scanned_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO attendees (
                ticket_id, full_name, email, mobile_number, illuminate_id,
                password_hash, date_of_birth, qr_filename, created_at, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket["ticket_id"], ticket["full_name"], ticket["email"],
                ticket["mobile_number"], ticket["illuminate_id"], ticket["password_hash"],
                ticket["date_of_birth"], ticket["qr_filename"], ticket["created_at"], scanned_at,
            ),
        )
        connection.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))

    return {"success": True, "message": "QR verified. User moved to attendees.", "record": ticket_row_for_display(ticket)}


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

    with get_connection() as connection:
        existing_ticket = connection.execute(
            """
            SELECT 1
            FROM tickets
            WHERE lower(email) = lower(?) OR lower(illuminate_id) = lower(?)
            LIMIT 1
            """,
            (form["email"].strip(), form["illuminate-id"].strip()),
        ).fetchone()

    if existing_ticket is not None:
        return redirect(
            url_for(
                "registration_page",
                message="Account already exists. Please sign in to view your QR code",
                message_type="warning",
            )
        )

    ticket_id = secrets.token_urlsafe(12)
    qr_filename = f"{ticket_id}.png"
    ticket_url = url_for("ticket_page", ticket_id=ticket_id, _external=True)
    qr_code = qrcode.QRCode(version=None, box_size=10, border=4)
    qr_code.add_data(ticket_url)
    qr_code.make(fit=True)
    qr_code.make_image(fill_color="black", back_color="white").save(QR_DIRECTORY / qr_filename)

    try:
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
    except sqlite3.IntegrityError:
        (QR_DIRECTORY / qr_filename).unlink(missing_ok=True)
        return redirect(
            url_for(
                "registration_page",
                message="Account already exists. Please sign in to view your QR code",
                message_type="warning",
            )
        )

    return redirect(url_for("ticket_page", ticket_id=ticket_id))


@app.route("/signin", methods=["GET", "POST"])
def signin_page():
    message = None
    message_type = None

    if request.method == "POST":
        full_name = request.form.get("full-name", "").strip()
        illuminate_id = request.form.get("illuminate-id", "").strip()
        date_of_birth = normalize_date(request.form.get("date-of-birth", ""))
        password = request.form.get("password", "")

        with get_connection() as connection:
            ticket = connection.execute(
                """
                SELECT ticket_id, password_hash
                FROM tickets
                                WHERE lower(full_name) = lower(?)
                                    AND lower(illuminate_id) = lower(?)
                                    AND date_of_birth = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                                (full_name, illuminate_id, date_of_birth or ""),
            ).fetchone()

        if ticket is None:
            message = "No such details were found, register using valid illuminate details."
            message_type = "warning"
        elif not verify_password(password, ticket["password_hash"]):
            message = "The details were incorrect, try again."
            message_type = "error"
        else:
            return redirect(url_for("ticket_page", ticket_id=ticket["ticket_id"]))

    return render_template(
        "signin.html",
        message=message,
        message_type=message_type,
    )


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
