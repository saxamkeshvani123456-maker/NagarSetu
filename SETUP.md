# CivicLens — Setup & Run Guide

CivicLens is a civic-tech MVP that turns citizen reports into actionable, trackable civic issues.

Core flow:

**Report → GPS → Cluster → Prioritize → Resolve → Citizen Verify → Reward → Measure**

The MVP uses a Python/FastAPI backend, SQLite, and a vanilla HTML/CSS/JavaScript frontend.

---

## 1. Requirements

Install:

- Python 3.10+ (Python 3.11 recommended)
- VS Code
- Git (recommended)
- A modern browser such as Chrome or Edge

No Node.js, React, MongoDB, PostgreSQL, or Docker is required for the local MVP.

---

## 2. Project structure

Typical structure:

```text
CivicLens/
├── backend/
├── citizen/
├── admin/
├── assets/
├── uploads/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

The exact file/folder layout may vary slightly between MVP builds.

---

## 3. Open in VS Code

1. Extract the ZIP.
2. Open the extracted CivicLens folder in VS Code.
3. Open **Terminal → New Terminal**.

Check Python:

```powershell
python --version
```

---

## 4. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate again:

```powershell
.venv\Scripts\Activate.ps1
```

You should see `(venv)` in the terminal.

---

## 5. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

---

## 6. Configure environment variables

Create a local `.env` from the example:

```powershell
Copy-Item .env.example .env
```

For the local MVP, you normally do **not** need to enter API keys.

The important rule is:

> Never put real secrets in `.env.example`.

Your actual `.env` is ignored by Git through `.gitignore`.

### Optional services

CivicLens can be extended with external services such as:

- Sightengine for AI-image detection
- Google OAuth for real authentication

If those integrations are enabled in the code, add their credentials to `.env`.

---

## 7. Start the backend

From the project root, use the command matching the location of `app.py`.

If the application is exposed as `backend.app:app`:

```powershell
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

If `app.py` is in the project root:

```powershell
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Keep this terminal running.

You should see:

```text
Uvicorn running on http://127.0.0.1:8000
```

---

## 8. Check the backend

Open:

```text
http://127.0.0.1:8000/api/health
```

A healthy installation should return a successful health response.

If FastAPI exposes Swagger documentation, you can also open:

```text
http://127.0.0.1:8000/docs
```

---

## 9. Start the frontend

The CivicLens frontend is plain HTML/CSS/JavaScript.

### Recommended: VS Code Live Server

Install the **Live Server** extension in VS Code.

Then:

1. Open the citizen `welcome.html`.
2. Right-click it.
3. Choose **Open with Live Server**.

The frontend will normally run on something similar to:

```text
http://127.0.0.1:5500/
```

Keep the FastAPI backend running on port 8000.

---

## 10. Browser permissions

The improved CivicLens MVP uses browser geolocation for issue reporting.

When prompted:

> Allow this site to access your location.

This is required for real GPS-based reporting.

The map also requires an internet connection because map tiles are loaded from the configured online map provider.

---

## 11. Recommended demo flow

### Citizen

1. Open CivicLens.
2. Choose Guest Login / demo login.
3. Open **Report an Issue**.
4. Allow location access.
5. Select an issue category.
6. Add a description.
7. Capture/upload evidence.
8. Submit the report.
9. Save the tracking ID.

### Duplicate/cluster demonstration

Create another report for the same type of issue from a nearby location.

CivicLens should use proximity and similarity logic to associate related reports with the same civic issue/cluster.

### Admin

1. Open the admin dashboard.
2. View the issue cluster.
3. Inspect priority/report information.
4. Open the cluster details.
5. Submit a resolution and after-evidence.

### Citizen verification

1. Return to the citizen dashboard.
2. Open the resolution notification.
3. Review the resolution.
4. Approve if the issue is fixed.
5. Reopen it if the problem remains.

### Metrics

Check the admin metrics page for resolution and verification information.

---

## 12. Settings and logout

Authenticated citizen pages include:

- Settings
- Notifications preference
- Location-use information
- Logout

Logout clears the local demo authentication state and returns the user to the welcome flow.

---

## 13. Common problems

### `python is not recognized`

Reinstall Python and enable:

**Add Python to PATH**

Then restart VS Code.

### `uvicorn is not recognized`

Activate the virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
```

Then:

```powershell
pip install -r backend/requirements.txt
```

### Port 8000 is already in use

Run:

```powershell
uvicorn backend.app:app --reload --port 8001
```

If you change the backend port, make sure the frontend API base URL uses the same port.

### CORS error

Make sure the frontend origin is allowed by the FastAPI backend.

Typical local origins are:

```text
http://127.0.0.1:5500
http://localhost:5500
```

### Location does not work

Check that:

- browser location permission is allowed
- the page is served through localhost/Live Server
- you are not blocking browser location access

### Map is blank

Check:

- internet connection
- browser DevTools → Console
- browser DevTools → Network

---

## 14. Security notes

This is a **hackathon/demo MVP**, not a production civic-government deployment.

The local/demo setup may use:

- demo authentication
- development OTP
- in-memory sessions
- SQLite
- optional external services

Before production deployment, replace these with:

- real OAuth/OTP
- secure persistent sessions/JWT
- PostgreSQL
- HTTPS
- strong secret management
- rate limiting
- audit logs
- role-based access control
- abuse/fraud prevention
- secure file storage
- production CORS configuration

Never commit:

```text
.env
```

API keys, passwords, tokens, or production credentials.

---

## 15. GitHub setup

After testing:

```powershell
git init
git add .
git status
git commit -m "Initial CivicLens MVP"
```

Before pushing, verify that `.env`, databases, virtual environments, and uploaded files are ignored.

Check:

```powershell
git status
```

You should **not** see your `.env` or `venv/` as files to commit.

---

## 16. Hackathon demo checklist

Before presenting CivicLens:

- [ ] Backend starts successfully
- [ ] `/api/health` works
- [ ] Citizen login works
- [ ] GPS permission works
- [ ] Report submission works
- [ ] Image upload works
- [ ] Nearby reports cluster correctly
- [ ] Admin dashboard loads
- [ ] Cluster details load
- [ ] Resolution submission works
- [ ] Citizen receives verification flow
- [ ] Approve/reopen works
- [ ] Wallet/reward updates correctly
- [ ] Settings opens
- [ ] Logout works
- [ ] Map loads
- [ ] Metrics load
- [ ] No API keys or secrets are committed

---

## 17. One-command mental model

For local development, think of CivicLens as two services:

```text
VS Code
│
├── Terminal 1
│   └── FastAPI backend :8000
│
└── Browser / Live Server
    └── CivicLens frontend :5500
```

The browser talks to the FastAPI backend through API requests.

---

## License / project note

CivicLens is currently an MVP/hackathon project. Add your preferred license and project ownership information before public distribution.
