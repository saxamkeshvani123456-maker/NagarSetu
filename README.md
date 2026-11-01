# NagarSetu

**Where Public Voice Meets Public Action.**

NagarSetu is a civic accountability application built from the downloaded CivicLens project. It lets residents submit a civic issue, attach evidence, follow related reports, and inspect a public incident record. Its central question is whether a reported problem was actually resolved.

## Run locally

Requirements: Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. The application serves the frontend and API from the same FastAPI process. SQLite and uploaded evidence are stored under `data/` by default. Set `CIVICLENS_DATA_DIR` to use another storage directory.

Authentication demo routes are disabled by default. For a local hackathon demo only, set `DEMO_MODE=true` in `.env` to enable the demo administrator and fixed development OTP (`123456`). This is not production authentication. Google sign-in is not implemented, and phone verification requires an SMS provider before production use.

## What works

- Citizen guest access, local-only development phone OTP (when `DEMO_MODE=true`), report submission, report tracking and evidence uploads.
- SQLite persistence for users, incidents, clusters, evidence, official statements, timeline events, verification records and existing administration workflows.
- Similarity and proximity based related-report suggestions. Matches remain suggestions; reports are not silently merged.
- Transparent keyword-based category and severity guidance on the report form. The suggestion basis is shown and residents remain in control.
- A public dashboard whose metrics and recent reports are queried from persisted submissions.
- OpenStreetMap views with filters and markers for actual submitted reports.
- Public incident pages with citizen report timelines, source-linked official statements and recorded verification evidence. Reporter contact details are not included in public responses.
- Promise vs Reality records distinguish authority responses from specific commitments, retain published source/date/authority/action/deadline and record-entry timestamps, and compare each promise only with later saved claims, evidence and reviews.
- Admin accountability review accepts sourced statements and evidence-backed decisions. A claim submitter is barred from independently verifying that same cluster claim.
- Public incident pages show evidence from every report in the incident cluster, including original citizen photos and later authority resolution photos, with upload timestamps and recorded image checks.
- Image structure and dimensions validation, SHA-256 tracking and optional C2PA/Sightengine checks (configure those services separately).
- 64-bit difference-hash image similarity suggestions. Similar photos are shown for review and never merge incidents automatically.

## Data integrity

New installations start empty. Startup does not invent sample complaints, residents, crews or outcomes. Dashboard metrics, category counts and map markers are calculated from saved reports. Official commitments appear only after an administrator records the statement, publication date and source URL. A missing statement or verification is shown as missing; AI analysis is not presented as an official update.

Image metadata and content-credential checks are signals, not proof that a photo is authentic. Sightengine and C2PA integrations are optional and report unavailable/not-run states when they are not configured.

NagarSetu currently has no municipal open-data feed configured. Its public data is limited to citizen reports saved in this application. AI text classification, automatic summaries and a live official-data integration still need implementation before those capabilities can be claimed.

## Architecture

- `backend/app/main.py` — FastAPI routes, SQLite schema, authentication, report matching and public incident records.
- `backend/app/authenticity.py` — image checks and optional provenance integrations.
- `assets/nagarsetu.css`, `assets/nagarsetu.js` — NagarSetu landing and public accountability experience.
- `citizen/` — report submission, authentication and citizen account screens.
- `admin/` — administration and evidence review screens.
- `public.html`, `incident.html` — public incident list and detail pages.
- `_reference/` — retained design references from the source project.

## API additions

- `GET /api/public/overview` — stored report metrics and category totals.
- `GET /api/public/incidents` — public incident list; accepts `category` and `status` filters.
- `GET /api/public/incidents/{tracking_id}` — public detail, timeline, official statements and verification records.
- `POST /api/admin/clusters/{cluster_id}/statements` — source-linked authority response or commitment with optional published deadline (admin session required).
- `POST /api/admin/clusters/{cluster_id}/verification` — evidence-backed verification record (admin session required).

Interactive maps use OpenStreetMap tiles. Internet access is needed for map tiles and the remotely hosted fonts and Leaflet library.

## Attribution and licence

This repository began as the downloaded CivicLens project. Its existing application structure, citizen and admin screens, API flows, image-authenticity code and `_reference/` materials have been retained and extended. Existing source notices have not been intentionally removed. No `LICENSE` file was present in the supplied repository, so the source project's license terms could not be verified from this checkout. Check the original CivicLens distribution and include its license and required attribution before redistribution.
