from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from bson import ObjectId
from flask import Flask, abort, redirect, render_template, request, send_file, send_from_directory, session, url_for
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database import admins, audit_logs, users

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
if not app.secret_key:
    raise RuntimeError("SESSION_SECRET is missing. Add it to a local .env file.")


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


def require_admin() -> str:
    admin_id = session.get("admin_id")
    if not admin_id:
        abort(401)
    return admin_id


def ticket_row_for_display(user: dict) -> dict:
    return {
        "ticket_id": str(user["_id"]),
        "full_name": user["fullName"],
        "email": user["email"],
        "mobile_number": user["mobileNumber"],
        "illuminate_id": user["illuminateId"],
        "password": "Protected",
        "date_of_birth": user["dateOfBirth"],
        "qr_filename": f"{user['qrToken']}.png",
    }


def get_user_id(ticket_id: str) -> ObjectId | None:
    try:
        return ObjectId(ticket_id)
    except Exception:
        return None


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

        admin = admins.find_one({"nameNormalized": admin_name, "active": True})
        if admin and verify_password(admin_code, admin["codeHash"]):
            session["admin_id"] = str(admin["_id"])
            return render_template("admin_dashboard.html", admin_name=admin["name"])

        message = "The admin name or assigned code is incorrect, try again."

    return render_template("admin_login.html", message=message)


@app.post("/admin/tickets/<ticket_id>/accept")
def accept_ticket(ticket_id: str):
    admin_id = require_admin()
    user_id = get_user_id(ticket_id)
    if user_id is None:
        return {"success": False, "message": "Invalid user ID."}, 400
    scanned_at = datetime.now(timezone.utc)
    user = users.find_one_and_update(
        {"_id": user_id, "status": "active"},
        {"$set": {"status": "attended", "scannedAt": scanned_at, "scannedBy": ObjectId(admin_id)}},
        return_document=ReturnDocument.AFTER,
    )
    if user is None:
        return {"success": False, "message": "This user is no longer active."}, 404
    audit_logs.insert_one({"action": "scan", "userId": user_id, "adminId": ObjectId(admin_id), "illuminateId": user["illuminateId"], "timestamp": scanned_at})
    return {"success": True, "message": "User accepted and moved to attendees."}


@app.delete("/admin/tickets/<ticket_id>")
def remove_ticket(ticket_id: str):
    admin_id = require_admin()
    user_id = get_user_id(ticket_id)
    if user_id is None:
        return {"success": False, "message": "Invalid user ID."}, 400
    result = users.update_one(
        {"_id": user_id, "status": {"$ne": "deleted"}},
        {"$set": {"status": "deleted", "deletedAt": datetime.now(timezone.utc), "deletedBy": ObjectId(admin_id)}},
    )
    if result.modified_count != 1:
        return {"success": False, "message": "This user is already deleted."}, 404
    audit_logs.insert_one({"action": "delete", "userId": user_id, "adminId": ObjectId(admin_id), "timestamp": datetime.now(timezone.utc)})
    return {"success": True, "message": "User marked as deleted."}


@app.get("/admin/database")
def admin_database():
    require_admin()
    filter_by = request.args.get("filter", "full_name")
    search = request.args.get("search", "").strip()
    allowed_filters = {
        "full_name": "full_name",
        "email": "email",
        "mobile_number": "mobile_number",
        "illuminate_id": "illuminate_id",
    }
    column = allowed_filters.get(filter_by, "fullName")
    query = {"status": "active"}
    if search:
        normalized_search = search.casefold()
        normalized_column = {"full_name": "fullNameNormalized", "email": "emailNormalized", "illuminate_id": "illuminateIdNormalized"}.get(filter_by, "fullNameNormalized")
        query[normalized_column] = {"$regex": re.escape(normalized_search)}
    rows = users.find(query).sort("createdAt", -1)
    return {"records": [ticket_row_for_display(row) for row in rows]}


@app.get("/admin/attendees")
def admin_attendees():
    require_admin()
    rows = users.find({"status": "attended"}).sort("scannedAt", -1)
    return {"records": [ticket_row_for_display(row) for row in rows]}


@app.post("/admin/scan")
def admin_scan():
    admin_id = require_admin()
    payload = request.get_json(silent=True) or {}
    qr_value = str(payload.get("qr_value", "")).strip()
    parsed_path = urlparse(qr_value).path
    match = re.fullmatch(r"/ticket/([^/]+)", parsed_path)
    qr_token = match.group(1) if match else qr_value.rsplit("/", 1)[-1]

    if not qr_token:
        return {"success": False, "message": "Invalid QR code."}, 400
    scanned_at = datetime.now(timezone.utc)
    admin_object_id = ObjectId(admin_id)
    ticket = users.find_one_and_update(
        {"qrToken": qr_token, "status": "active"},
        {"$set": {"status": "attended", "scannedAt": scanned_at, "scannedBy": admin_object_id}},
        return_document=ReturnDocument.AFTER,
    )
    if ticket is None:
        return {"success": False, "message": "QR code is not valid or has already been scanned."}, 404
    audit_logs.insert_one({"action": "scan", "userId": ticket["_id"], "adminId": admin_object_id, "illuminateId": ticket["illuminateId"], "timestamp": scanned_at})
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

    email = form["email"].strip()
    illuminate_id = form["illuminate-id"].strip()
    if users.find_one({"$or": [{"emailNormalized": email.casefold()}, {"illuminateIdNormalized": illuminate_id.casefold()}]}):
        return redirect(
            url_for(
                "registration_page",
                message="Account already exists. Please sign in to view your QR code",
                message_type="warning",
            )
        )

    qr_token = secrets.token_urlsafe(32)
    ticket_url = url_for("ticket_page", ticket_id=qr_token, _external=True)

    try:
        users.insert_one({
            "fullName": form["full-name"].strip(),
            "fullNameNormalized": form["full-name"].strip().casefold(),
            "email": email,
            "emailNormalized": email.casefold(),
            "mobileNumber": form["mobile-number"].strip(),
            "illuminateId": illuminate_id,
            "illuminateIdNormalized": illuminate_id.casefold(),
            "passwordHash": hash_password(form["password"]),
            "dateOfBirth": date_of_birth,
            "qrToken": qr_token,
            "status": "active",
            "createdAt": datetime.now(timezone.utc),
            "scannedAt": None,
            "scannedBy": None,
            "deletedAt": None,
            "deletedBy": None,
        })
    except DuplicateKeyError:
        return redirect(
            url_for(
                "registration_page",
                message="Account already exists. Please sign in to view your QR code",
                message_type="warning",
            )
        )

    return redirect(url_for("ticket_page", ticket_id=qr_token))


@app.route("/signin", methods=["GET", "POST"])
def signin_page():
    message = None
    message_type = None

    if request.method == "POST":
        full_name = request.form.get("full-name", "").strip()
        illuminate_id = request.form.get("illuminate-id", "").strip()
        date_of_birth = normalize_date(request.form.get("date-of-birth", ""))
        password = request.form.get("password", "")

        ticket = users.find_one({
            "fullNameNormalized": full_name.casefold(),
            "illuminateIdNormalized": illuminate_id.casefold(),
            "dateOfBirth": date_of_birth or "",
            "status": {"$ne": "deleted"},
        })

        if ticket is None:
            message = "No such details were found, register using valid illuminate details."
            message_type = "warning"
        elif not verify_password(password, ticket["passwordHash"]):
            message = "The details were incorrect, try again."
            message_type = "error"
        else:
            return redirect(url_for("ticket_page", ticket_id=ticket["qrToken"]))

    return render_template(
        "signin.html",
        message=message,
        message_type=message_type,
    )


@app.get("/ticket/<ticket_id>")
def ticket_page(ticket_id: str):
    user = users.find_one({"qrToken": ticket_id, "status": {"$ne": "deleted"}})

    if user is None:
        abort(404)

    return render_template("ticket.html", ticket={
        "illuminate_id": user["illuminateId"],
        "qr_filename": f"{user['qrToken']}.png",
    })


@app.get("/generated_qr/<filename>")
def generated_qr(filename: str):
    qr_token = filename.removesuffix(".png")
    user = users.find_one({"qrToken": qr_token, "status": {"$ne": "deleted"}})
    if user is None:
        abort(404)
    image = qrcode.make(url_for("ticket_page", ticket_id=qr_token, _external=True))
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return send_file(output, mimetype="image/png", download_name=filename)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
