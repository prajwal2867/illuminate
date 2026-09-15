# MongoDB Atlas architecture recommendation

MongoDB Atlas is a good fit for this system, especially when paired with Vercel. SQLite should be replaced because Vercel serverless instances are ephemeral and cannot reliably share a local database between admins.

## Recommended architecture

```text
Browser
  -> Vercel frontend/API
      -> MongoDB Atlas
      -> QR generation/verification
```

Use MongoDB Atlas as the centralized source of truth. All 15 admins will access the same database through protected API routes.

## Suggested collections

### `users`

```js
{
  fullName,
  email,
  mobileNumber,
  illuminateId,
  passwordHash,
  dateOfBirth,
  qrToken,
  createdAt,
  status: "active" | "attended",
  scannedAt
}
```

### `admins`

```js
{
  name,
  codeHash,
  role: "admin",
  active: true
}
```

### `auditLogs`

```js
{
  adminName,
  action: "scan" | "view_database",
  illuminateId,
  timestamp
}
```

Instead of physically deleting a scanned user and copying them into another collection, I recommend changing:

```js
status: "active"
```

to:

```js
status: "attended"
```

Then:

- Database view filters `status: "active"`
- Attendees view filters `status: "attended"`
- Scanner updates the status atomically
- The original record is never lost

This is safer and simpler. If you need separate collections later, MongoDB transactions can move the document atomically.

## Important indexes

Create unique indexes for:

```text
illuminateId
email
```

Use case-insensitive normalization before storing values, for example:

```text
prajwal
```

instead of allowing inconsistent casing such as `Prajwal`, `PRAJWAL`, etc.

## Admin access

Do not hardcode admin credentials permanently in `app.py`. Store admin names and hashed codes in MongoDB or secure environment variables.

Each admin should authenticate through a session or signed HTTP-only cookie. Every admin can independently access:

- Database
- Scanner
- Attendees

The server must verify admin authentication on every API route, not just when loading the dashboard.

## QR design

The QR should contain a random, non-guessable ticket token, not the user’s password or personal details.

Example:

```text
https://your-domain.com/ticket/secure-random-token
```

When scanned:

1. Extract the token
2. Find the matching user
3. Confirm the ticket is active
4. Update the user to `status: "attended"`
5. Record `scannedAt` and the admin who scanned it
6. Reject future scans of the same ticket

Use a MongoDB atomic update such as:

```js
{
  qrToken: token,
  status: "active"
}
```

Then update it to `attended`. This prevents two admins scanning the same QR at exactly the same time.

## Vercel considerations

Vercel works well for the API and frontend, but avoid:

- SQLite
- Writing permanent files locally
- Saving generated QR images to the server filesystem
- In-memory login sessions
- Long-running background processes

For QR images, either:

- Store the QR as a data URL in MongoDB for a small application
- Store it in Vercel Blob, Cloudinary, or S3
- Regenerate the QR from the stored token when needed

For this project, I would store the QR token in MongoDB and regenerate the QR when displaying or downloading it. That avoids file-storage problems entirely.

## Deployment recommendation

Your current Flask app can potentially run on Vercel as a Python function, but the cleanest long-term structure would be:

```text
frontend: React/Next.js or existing HTML
API: Flask or Vercel serverless API routes
database: MongoDB Atlas
QR: qrcode library/server-side generation
hosting: Vercel
```

At minimum, you would need:

```text
MONGODB_URI
MONGODB_DATABASE
SESSION_SECRET
```

stored in Vercel environment variables, never committed to GitHub.

### Final recommendation

> Use MongoDB Atlas with one `users` collection and a `status` field instead of physically moving users between active and attendees collections.

That gives all 15 admins centralized real-time access, prevents duplicate scans, preserves auditability, and works much better with Vercel’s serverless model.