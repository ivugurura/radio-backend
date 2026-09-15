# Radio API

The backend service for the [Ivugurura](https://github.com/ivugurura) radio platform — a Django application exposing a GraphQL and REST API that powers studio management, media ingestion, and listener analytics for an internet radio operation.

It is one of three services that make up the platform:

| Service                                                   | Role                                                           |
| --------------------------------------------------------- | -------------------------------------------------------------- |
| **radio-api** _(this repo)_                               | Application backend — auth, studios, media pipeline, analytics |
| [radio-studio](https://github.com/ivugurura/radio-studio) | Streaming server — live ingest and audio delivery to listeners |
| [radio-ui](https://github.com/ivugurura/radio-frontend)   | Web dashboard consumed by station staff                        |

## Features

- **Authentication** — JWT-based accounts with refresh tokens and Argon2 password hashing
- **Studio management** — multiple independently configured studios, each with its own playlist, rotation, and schedule
- **Media pipeline** — resumable chunked uploads with background audio transcoding and metadata extraction
- **Listener analytics** — ingestion of session and playback events from the streaming layer for reporting
- **Live chat** — real-time messaging tied to on-air studios
- **GraphQL-first API** with supporting REST endpoints for streaming and file transfer use cases that don't fit the GraphQL model well
- Internationalized error messages and content via translatable strings

## Tech Stack

- Python & Django, with GraphQL served through `graphene-django`
- PostgreSQL for persistence
- Celery + Redis for asynchronous work (transcoding, notifications)
- FFmpeg for audio processing

## Requirements

Running the service requires a Python runtime compatible with the version pinned in this repository, a PostgreSQL database, a Redis instance for the task queue, and FFmpeg/FFprobe available for audio processing. Exact versions are pinned in the dependency manifests rather than documented here, so they stay in sync automatically as the project evolves.

## Getting Started

The project uses `pipenv` for local development and a plain `requirements.txt` for production installs — pick whichever matches your workflow.

At a high level, getting a local instance running looks like:

1. Install the project's dependencies for your environment (dev or production).
2. Copy `.env.example` to `.env` and provide values for your database, cache, and media storage configuration.
3. Apply database migrations and, optionally, create an admin user.
4. Start the application server.

A `Makefile` is included with shortcuts for the most common development tasks (running the server, formatting, and testing) — see it for the exact commands.

For long-running deployments, the backend and its Celery worker are designed to run under a single process supervisor; reference material for that setup lives under [deploy/](deploy/).

## API Surface

The service exposes a single GraphQL endpoint for the bulk of the domain model (users, studios, media, chat), plus a small set of REST endpoints for concerns that don't map cleanly to GraphQL — chunked file uploads, token refresh, and the event/streaming endpoints consumed by the studio server. Introspect the schema via the bundled GraphiQL UI in development rather than relying on a static reference here, since it evolves with the domain model.

## License

Licensed under the terms in [LICENSE](LICENSE).

## Maintainer

[Jean d'Amour AKIMANIZANYE](https://github.com/AJAkimana)
