# Campaign Wiki

A small, player-driven Dungeons & Dragons campaign wiki. Players can create and
edit articles and session recaps, link pages together, organize them into
categories, upload images, search the current wiki, and inspect or restore full
page revisions. Administrators can additionally maintain official pages,
categories, revisions, and user roles.

## Features

- Invite-only user registration with one-time keys
- Administrator-issued, one-time password-reset links
- Article, recap, and administrator-controlled official page types
- Complete revision snapshots of title, body, page type, session number,
  categories, and referenced images
- Historical revision viewing, restoration, and administrator deletion
- `[[Wiki Link]]` syntax with stable ID-based resolved links and wanted pages
- Multiple categories per page, with administrator rename/delete controls
- SQLite FTS5 search with title-weighted results and contextual highlighting
- Multiple-image uploads with master, display, and thumbnail WebP variants
- Browser-local draft recovery for page forms
- Per-client or per-user rate limits on sensitive and expensive routes

## Requirements

- Python 3.12 or newer
- SQLite with FTS5 support
- Writable storage for the SQLite database and `instance/uploads`

Install dependencies in a virtual environment:

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project directory:

```dotenv
SECRET_KEY=replace-with-a-long-random-value
DATABASE_URL=sqlite:///instance/dndwiki.db
```

Both values are required. The application exits with a clear error if either
is absent or blank. The `.env` file and the `instance` directory are ignored by
Git.

`RATELIMIT_STORAGE_URI` is optional and defaults to `memory://`. That is
appropriate for the intended single-process deployment. Configure a shared
backend such as Redis before running multiple application processes.

`WIKI_BASE_URL` is optional and controls the public URL printed by the password
reset script. It defaults to `http://localhost:5000` and should be set to the
HTTPS production origin.

## Database setup and migrations

The database is managed by Flask-Migrate/Alembic. Do not use `db.create_all()`
for a deployed database.

For a new installation, and after pulling future schema changes:

```bash
venv/bin/flask db upgrade
```

The first migration creates the original schema and its SQLite FTS5 table. The
second adds invite keys and complete revision snapshots; a compatibility
migration aligns indexes and constraints in older `create_all()` databases.

For a database created before migrations were introduced, make a backup and
mark it as the baseline before upgrading:

```bash
cp instance/dndwiki.db instance/dndwiki.before-migrations.bak
venv/bin/flask db stamp b32dc03a3054
venv/bin/flask db upgrade
```

Only use `stamp` for an existing, unversioned database that already has the
baseline tables. A fresh database should use `flask db upgrade` alone.

## Inviting users

Generate one or more registration keys:

```bash
venv/bin/python generate_invite.py
venv/bin/python generate_invite.py --count 5
```

Each plaintext key is displayed once. Only a SHA-256 hash is stored. A key is
atomically marked used when its account is created and cannot register another
account.

To promote a registered account to administrator:

```bash
venv/bin/python manage_user_role.py USERNAME admin
```

Use `user` instead of `admin` to remove administrator privileges.

## Running locally

After applying migrations:

```bash
venv/bin/flask run
```

The development server is not intended for internet-facing deployment. Use a
production WSGI server behind HTTPS and never expose Flask debug mode.

## Rate limits

Rate limits use the authenticated user ID when available and otherwise the
client IP address:

- Login: 10 attempts/minute and 50/hour
- Registration: 5 attempts/hour
- Page creation: 60/hour
- Page editing: 120/hour
- Image upload requests: 60/hour
- Search: 120/minute
- Password-reset links: 20 requests/hour, including at most 5 submissions/hour

If the application is behind a reverse proxy, configure the deployment so
Flask receives the real client address from that trusted proxy. Otherwise,
anonymous users may share the proxy's rate-limit bucket.

## Maintenance and backups

The database and image directory form one logical backup set:

- `instance/dndwiki.db`
- `instance/uploads/images`

Back them up together and periodically test a restoration. Always take a
database backup before schema upgrades.

Useful maintenance commands:

```bash
venv/bin/flask cleanup-images --days 30
venv/bin/flask image-storage-report
venv/bin/flask rebuild-search-index
```

Schedule image cleanup periodically. The storage report includes both tracked
database usage and files present on disk.

## Testing

```bash
venv/bin/python -m unittest -q
venv/bin/pip check
venv/bin/flask db check
```

Tests use isolated in-memory databases and temporary image directories.

## Password resets

Generate a one-time reset URL for a user:

```bash
venv/bin/python generate_password_reset.py USERNAME
```

The default lifetime is 60 minutes. It can be changed per link, and the public
base URL can be supplied directly if `WIKI_BASE_URL` is not configured:

```bash
venv/bin/python generate_password_reset.py USERNAME \
  --minutes 30 \
  --base-url https://wiki.example.com
```

Only the token hash is stored. Creating another link invalidates earlier unused
links for that user. The user chooses and confirms the new password in their
browser; the administrator never sees it. A successful reset consumes the link
and revokes every existing login session for that account.

The migration that introduces session revocation also logs out sessions created
by older versions of the wiki once; users can immediately log back in.
