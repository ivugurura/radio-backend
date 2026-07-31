# radio-backend

Django backend for the Ivugurura radio platform. Provides a GraphQL API, REST endpoints for media uploads and streaming, studio management, listener analytics, and async media transcoding.

## Tech Stack

- **Python** 3.12
- **Django** 5.2 with PostgreSQL
- **GraphQL** via `graphene-django` + `django-graphql-jwt`
- **REST** via Django REST Framework
- **Async tasks** via Celery + Redis
- **Media processing** via FFmpeg / FFprobe
- **Password hashing** via Argon2

## Project Structure

```
apps/
  users/      # Custom user model, JWT auth (register, login, refresh)
  studio/     # Studios, playlists, rotation rules, scheduled shows, listener analytics
  medias/     # Track uploads, transcoding pipeline, file serving
config/       # Django settings, URLs, Celery, ASGI/WSGI
```

## Prerequisites

- Python 3.12
- PostgreSQL
- Redis (Celery broker + result backend)
- FFmpeg and FFprobe (see below)

### Installing FFmpeg and FFprobe

FFmpeg and FFprobe are required for audio transcoding and metadata extraction.

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install -y ffmpeg
```

**RHEL / Fedora:**
```bash
sudo dnf install -y ffmpeg
```

**Verify installation:**
```bash
ffmpeg -version
ffprobe -version
```

If the binaries are not on `PATH`, set their absolute paths via `FFMPEG_PATH` and `FFPROBE_PATH` in your `.env`.

## Setup

### Development

Uses `pipenv` to manage the virtualenv and dev dependencies (linting, testing tools).

```bash
# Install pipenv if needed
pip install pipenv

# Install all dependencies (including dev)
pipenv install --dev

# Activate the virtualenv
pipenv shell

# Configure environment
cp .env.example .env

# Apply database migrations
python manage.py migrate

# Create a superuser (optional)
python manage.py createsuperuser

# Start the development server
python manage.py runserver
# or
make run
```

### Production

Uses a plain `venv` with `requirements.txt` (no dev tools).

```bash
# Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install production dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Apply database migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | `INSECURE-CHANGE-ME` | Django secret key — **must be set in production** |
| `DJANGO_DEBUG` | `False` | Enable debug mode (`True` / `False`) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of allowed hostnames (required when `DEBUG=False`) |
| `CORS_ALLOWED_ORIGINS` | `http://127.0.0.1:8000,http://localhost:3000` | Comma-separated list of allowed CORS origins (frontend URLs) |
| `DB_NAME` | `dj_graphql` | PostgreSQL database name |
| `DB_USER` | `dj_user` | PostgreSQL username |
| `DB_PASSWORD` | _(empty)_ | PostgreSQL password |
| `DB_HOST` | `127.0.0.1` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/1` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | `redis://127.0.0.1:6379/2` | Celery result backend URL |
| `RADIO_ROOT` | `<BASE_DIR>/var/radio` | Root directory for all studio media files |
| `DEFAULT_TARGET_BITRATE_KBPS` | `128` | Default output bitrate for transcoded MP3s |
| `FFMPEG_PATH` | `ffmpeg` | Path to the `ffmpeg` binary |
| `FFPROBE_PATH` | `ffprobe` | Path to the `ffprobe` binary |
| `STUDIO_TOKEN` | _(empty)_ | Bearer token for studio event ingest endpoints |

## Running Celery

For local development, you can start a Celery worker directly:

```bash
celery -A config.celery worker -l info
```

For production on a VPS, the recommended approach is to run Django and Celery together from one systemd service. A launcher script and service unit are available in:

- [deploy/scripts/start-single-service.sh](deploy/scripts/start-single-service.sh)
- [deploy/systemd/radio-backend.service](deploy/systemd/radio-backend.service)

Example commands:

```bash
sudo cp deploy/systemd/radio-backend.service /etc/systemd/system/radio-backend.service
sudo systemctl daemon-reload
sudo systemctl enable radio-backend
sudo systemctl start radio-backend
sudo systemctl status radio-backend
```

Make sure to update the service file paths and user name to match your server.

## API Reference

### GraphQL

| Endpoint | Method | Description |
|---|---|---|
| `/graphql` | `POST` | GraphQL endpoint (GraphiQL UI available in dev) |

**Mutations:**
- `registerUser` — create a new user account
- `loginUser` — authenticate and receive a JWT token

**Queries:**
- `me` — return the currently authenticated user

### REST

| Endpoint | Method | Description |
|---|---|---|
| `/api/auth/refresh` | `POST` | Refresh a JWT access token |
| `/api/uploads/<upload_id>/chunk` | `PUT` | Upload a file chunk (resumable upload) |
| `/api/studios/<slug>/playlist` | `GET` | Get the ordered track playlist for a studio |
| `/api/studios/<slug>/tracks/<track_id>` | `GET` | Stream an MP3 track file |
| `/api/studios/<slug>/listener-events` | `POST` | Ingest listener session and stat bucket data |
| `/api/studios/<slug>/play-events` | `POST` | Ingest track play events (start / end) |

#### Token Refresh

```http
POST /api/auth/refresh
Content-Type: application/json

{ "refresh_token": "<token>" }
```

#### Chunk Upload

Chunks are uploaded with a `Content-Range` header and authenticated via `X-Upload-Token`:

```http
PUT /api/uploads/<upload_id>/chunk
Content-Range: bytes 0-1048575/5242880
X-Upload-Token: <token>
```

## Filesystem Layout

Media files are organized per-studio under `RADIO_ROOT/studios/`:

```
studios/
  {slug}/
    incoming/          # Partial upload files (.part)
    processing/        # FFmpeg working directory
    library/mp3/{kbps}/  # Finalized, transcoded MP3s
    waveform/          # Optional JSON waveform data
    artwork/           # Cover art
```

See [apps/medias/docs/FILESYSTEM_LAYOUT.md](apps/medias/docs/FILESYSTEM_LAYOUT.md) for details.

## Development Commands

```bash
make run         # Start development server
make fmt         # Format code with isort + black
make fmt-check   # Check formatting without applying changes
make test        # Run test suite with pytest
```

## Authentication

JWT tokens use the `RRV` prefix in the `Authorization` header:

```http
Authorization: RRV <access_token>
```

- Access tokens expire after **30 minutes**
- Refresh tokens expire after **7 days**
- Passwords are hashed with **Argon2**

## Admin

The Django admin interface is available at `/admin/`.
