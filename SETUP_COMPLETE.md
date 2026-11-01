# CivicLens v3.0 — CoBuild Hackathon Setup

## 1. Prerequisites
- Windows + VS Code
- Python 3.10+ recommended
- Internet connection for package installation and Sightengine calls

## 2. Open the correct folder
Open the `civic` folder in VS Code. The terminal should be at the folder containing `backend`, `citizen`, `admin`, and `index.html`.

## 3. Create and activate the virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If PowerShell blocks activation:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 4. Install dependencies
```powershell
pip install -r backend\requirements.txt
```
Optional C2PA support:
```powershell
pip install -r backend\requirements-optional.txt
```
If C2PA installation fails, CivicLens continues to work and reports C2PA as unavailable.

## 5. Configure environment variables
Copy the root example:
```powershell
Copy-Item .env.example .env
```
Then edit `civic/.env`. The backend loads this root `.env` automatically.

### Sightengine (recommended for the hackathon)
Get an API User and API Secret from the Sightengine dashboard: https://sightengine.com/
Put them in `.env`:
```env
SIGHTENGINE_API_USER=YOUR_API_USER
SIGHTENGINE_API_SECRET=YOUR_API_SECRET
```
Do not commit or share the real `.env`.

### Google OAuth
Not required for the demo. The project supports demo/mock login.

## 6. Start CivicLens
From the `civic` root:
```powershell
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```
Open:
- App: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health

### One-click Windows option
You can also double-click `start.bat`. It creates the virtual environment, installs dependencies, attempts optional C2PA installation, and starts the backend.

## 7. CoBuild end-to-end test
1. Open Citizen Portal.
2. Use demo/guest login or development OTP `123456` where applicable.
3. Create a pothole/road-damage report.
4. Add a location.
5. Upload a real phone photo first.
6. Submit and inspect the evidence/authenticity result.
7. Create a second report using `test_assets/AI_generated_pothole_test.png`.
8. Compare the AI-detector result.
9. Open the Admin Portal and inspect the cluster/report.
10. Resolve the issue and test citizen verification.

## 8. Important interpretation
Sightengine's `genai` result is an advisory probability, not proof that an image is fake. CivicLens should present it as a review signal. C2PA is a separate provenance signal and may be unavailable for ordinary images.
