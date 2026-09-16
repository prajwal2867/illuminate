from database import admins, audit_logs, database, users


users.create_index("illuminateIdNormalized", unique=True)
users.create_index("emailNormalized", unique=True)
users.create_index("qrToken", unique=True)
users.create_index([("status", 1), ("createdAt", -1)])
admins.create_index("nameNormalized", unique=True)
audit_logs.create_index([("timestamp", -1)])

print("Collections:", database.list_collection_names())
print("MongoDB indexes are ready")