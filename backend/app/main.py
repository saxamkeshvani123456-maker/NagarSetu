from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import sqlite3
import math
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load backend/../.env (project root) before anything reads os.getenv, since
# authenticity.py reads several config values (SIGHTENGINE_*, C2PA trust
# anchors, upload limits) at import time.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .authenticity import MAX_IMAGE_BYTES, combine_evidence, inspect_c2pa, inspect_with_sightengine, perceptual_hash_bytes, validate_image_bytes

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("CIVICLENS_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "civiclens.sqlite3"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="NagarSetu Civic Accountability API", version="1.1.0")
cors_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5500,http://localhost:5500").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://[a-z0-9-]+\.netlify\.app$|https://[a-z0-9-]+\.netlify\.app:\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
SESSIONS: dict[str, str] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db() -> None:
    db = connect()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, display_name TEXT NOT NULL, phone TEXT UNIQUE,
          role TEXT NOT NULL DEFAULT 'citizen', balance INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clusters (
          id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
          address TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'open', priority_score INTEGER NOT NULL DEFAULT 50,
          affected_count INTEGER NOT NULL DEFAULT 1,
          recurrence_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS issues (
          id TEXT PRIMARY KEY, tracking_id TEXT UNIQUE NOT NULL, reporter_id TEXT NOT NULL,
          cluster_id TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
          description TEXT NOT NULL, address TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
          status TEXT NOT NULL DEFAULT 'reported', priority TEXT NOT NULL DEFAULT 'medium',
          votes INTEGER NOT NULL DEFAULT 1, reward INTEGER NOT NULL DEFAULT 0,
          is_fix_submitted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          resolved_at TEXT, resolution_note TEXT,
          evidence_request_status TEXT NOT NULL DEFAULT 'none',
          evidence_request_note TEXT,
          FOREIGN KEY(reporter_id) REFERENCES users(id), FOREIGN KEY(cluster_id) REFERENCES clusters(id)
        );
        CREATE TABLE IF NOT EXISTS wallet_transactions (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, issue_id TEXT,
          kind TEXT NOT NULL, amount INTEGER NOT NULL, description TEXT NOT NULL,
          created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS otp_codes (
          phone TEXT PRIMARY KEY, code TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS issue_images (
          id TEXT PRIMARY KEY, issue_id TEXT NOT NULL,
          image_role TEXT NOT NULL DEFAULT 'report',
          original_filename TEXT NOT NULL, detected_media_type TEXT NOT NULL,
          sha256 TEXT NOT NULL, perceptual_hash TEXT, object_key TEXT NOT NULL, byte_size INTEGER NOT NULL,
          width INTEGER, height INTEGER,
          c2pa_status TEXT NOT NULL DEFAULT 'not_run',
          c2pa_trust_status TEXT NOT NULL DEFAULT 'unknown',
          c2pa_manifest_json TEXT, ai_detector_provider TEXT,
          ai_probability REAL, ai_detector_status TEXT NOT NULL DEFAULT 'not_run',
          review_status TEXT NOT NULL DEFAULT 'not_required',
          final_authenticity_state TEXT NOT NULL DEFAULT 'insufficient_evidence',
          provider_request_id TEXT, analysis_error TEXT, created_at TEXT NOT NULL,
          FOREIGN KEY(issue_id) REFERENCES issues(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, issue_id TEXT,
          type TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL,
          is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(issue_id) REFERENCES issues(id)
        );
        CREATE TABLE IF NOT EXISTS user_settings (
          user_id TEXT PRIMARY KEY, notifications INTEGER NOT NULL DEFAULT 1,
          location INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS comments (
          id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, user_id TEXT NOT NULL,
          body TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(cluster_id) REFERENCES clusters(id), FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS crews (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, specialty TEXT,
          status TEXT NOT NULL DEFAULT 'available', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS crew_assignments (
          id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, crew_id TEXT NOT NULL,
          assigned_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          assigned_at TEXT NOT NULL, FOREIGN KEY(cluster_id) REFERENCES clusters(id),
          FOREIGN KEY(crew_id) REFERENCES crews(id), FOREIGN KEY(assigned_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS resolution_records (
          id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, issue_id TEXT,
          submitted_by TEXT NOT NULL, note TEXT NOT NULL, image_id TEXT,
          status TEXT NOT NULL DEFAULT 'pending_verification', created_at TEXT NOT NULL, verification_at TEXT,
          FOREIGN KEY(cluster_id) REFERENCES clusters(id), FOREIGN KEY(issue_id) REFERENCES issues(id),
          FOREIGN KEY(submitted_by) REFERENCES users(id), FOREIGN KEY(image_id) REFERENCES issue_images(id)
        );
        """
    )
    cluster_columns = {row[1] for row in db.execute("PRAGMA table_info(clusters)").fetchall()}
    if "affected_count" not in cluster_columns:
        db.execute("ALTER TABLE clusters ADD COLUMN affected_count INTEGER NOT NULL DEFAULT 1")
    if "recurrence_count" not in cluster_columns:
        db.execute("ALTER TABLE clusters ADD COLUMN recurrence_count INTEGER NOT NULL DEFAULT 0")
    issue_columns = {row[1] for row in db.execute("PRAGMA table_info(issues)").fetchall()}
    if "evidence_request_status" not in issue_columns:
        db.execute("ALTER TABLE issues ADD COLUMN evidence_request_status TEXT NOT NULL DEFAULT 'none'")
    if "evidence_request_note" not in issue_columns:
        db.execute("ALTER TABLE issues ADD COLUMN evidence_request_note TEXT")
    columns = {row[1] for row in db.execute("PRAGMA table_info(issue_images)").fetchall()}
    if "image_role" not in columns:
        db.execute("ALTER TABLE issue_images ADD COLUMN image_role TEXT NOT NULL DEFAULT 'report'")
    if "perceptual_hash" not in columns:
        db.execute("ALTER TABLE issue_images ADD COLUMN perceptual_hash TEXT")
    resolution_columns = {row[1] for row in db.execute("PRAGMA table_info(resolution_records)").fetchall()}
    if "verification_at" not in resolution_columns:
        db.execute("ALTER TABLE resolution_records ADD COLUMN verification_at TEXT")
    # No fictional users, crews, or incidents are created at startup. Public
    # metrics and maps must reflect only reports actually submitted here.
    db.executescript("""
      CREATE TABLE IF NOT EXISTS timeline_events (
        id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, issue_id TEXT,
        event_type TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
        source_name TEXT, source_url TEXT, actor_type TEXT NOT NULL,
        verification_status TEXT NOT NULL DEFAULT 'unverified', created_at TEXT NOT NULL,
        FOREIGN KEY(cluster_id) REFERENCES clusters(id), FOREIGN KEY(issue_id) REFERENCES issues(id)
      );
      CREATE TABLE IF NOT EXISTS official_statements (
        id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, statement TEXT NOT NULL,
        promised_action TEXT, promised_by TEXT, published_at TEXT NOT NULL,
        source_name TEXT NOT NULL, source_url TEXT NOT NULL, created_at TEXT NOT NULL,
        record_type TEXT NOT NULL DEFAULT 'response', promised_by_date TEXT,
        FOREIGN KEY(cluster_id) REFERENCES clusters(id)
      );
      CREATE TABLE IF NOT EXISTS verification_records (
        id TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, verifier_id TEXT NOT NULL,
        evidence TEXT NOT NULL, evidence_url TEXT, decision TEXT NOT NULL,
        created_at TEXT NOT NULL, FOREIGN KEY(cluster_id) REFERENCES clusters(id),
        FOREIGN KEY(verifier_id) REFERENCES users(id)
      );
    """)
    statement_columns = {row[1] for row in db.execute("PRAGMA table_info(official_statements)").fetchall()}
    if "record_type" not in statement_columns:
        db.execute("ALTER TABLE official_statements ADD COLUMN record_type TEXT NOT NULL DEFAULT 'response'")
    if "promised_by_date" not in statement_columns:
        db.execute("ALTER TABLE official_statements ADD COLUMN promised_by_date TEXT")
    if os.getenv("DEMO_MODE", "false").lower() == "true" and not db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
        db.execute("INSERT INTO users(id,display_name,phone,role,balance,created_at) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), "Demo Administrator", "admin@nagarsetu.local", "admin", 0, now_iso()))
    db.commit()
    db.close()


@app.on_event("startup")
def startup() -> None:
    init_db()


class GuestRequest(BaseModel):
    display_name: str = Field(default="Citizen", max_length=80)


class PhoneRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=30)


class PhoneVerifyRequest(PhoneRequest):
    code: str = Field(min_length=4, max_length=8)


class IssueRequest(BaseModel):
    category: str = Field(min_length=2, max_length=40)
    description: str = Field(min_length=5, max_length=2000)
    address: str = Field(min_length=2, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class VerifyRequest(BaseModel):
    approved: bool


class ResolveRequest(BaseModel):
    resolution_note: str = Field(default="Resolved by municipal maintenance team.", max_length=500)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, min_length=5, max_length=30)


class SettingsRequest(BaseModel):
    notifications: bool | None = None
    location: bool | None = None
    display_name: str | None = Field(default=None, max_length=80)


class CommentRequest(BaseModel):
    body: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=2000)


class AssignmentRequest(BaseModel):
    crew_id: str


class StatementRequest(BaseModel):
    record_type: str = Field(default="response", pattern="^(response|commitment)$")
    statement: str = Field(min_length=5, max_length=3000)
    promised_action: str | None = Field(default=None, max_length=1000)
    promised_by: str | None = Field(default=None, max_length=200)
    promised_by_date: str | None = Field(default=None, max_length=10)
    published_at: str = Field(min_length=10, max_length=40)
    source_name: str = Field(min_length=2, max_length=200)
    source_url: str = Field(min_length=8, max_length=1000)


class IndependentVerificationRequest(BaseModel):
    evidence: str = Field(min_length=10, max_length=2000)
    evidence_url: str | None = Field(default=None, max_length=1000)
    decision: str = Field(pattern="^(verified|not_verified)$")


class AnalyzeRequest(BaseModel):
    description: str = Field(min_length=5, max_length=2000)


def analyze_description(description: str) -> dict[str, Any]:
    text = " ".join(description.lower().split())
    keywords = {
        "Roads and potholes": ("pothole", "road", "asphalt", "pavement", "crack", "street surface"),
        "Water supply": ("water", "pipe", "leak", "tap", "supply", "drinking"),
        "Waste management": ("garbage", "waste", "trash", "rubbish", "dump", "bin"),
        "Electricity": ("electric", "power", "outage", "wire", "streetlight", "lamp"),
        "Pollution": ("pollution", "smoke", "emissions", "odor", "odour", "noise"),
        "Drainage": ("drain", "sewer", "flood", "blocked water", "stormwater"),
        "Public infrastructure": ("footpath", "sidewalk", "bench", "park", "bus stop", "playground"),
    }
    scores = {category: sum(text.count(word) for word in words) for category, words in keywords.items()}
    best = max(scores, key=scores.get)
    count = scores[best]
    category = best if count else "Other civic issues"
    matched = [word for word in keywords.get(best, ()) if word in text]
    confidence = round(min(0.92, 0.48 + count * 0.14), 2) if count else 0.0
    high_signals = ("injury", "injured", "crash", "accident", "live wire", "electric shock", "unsafe", "collapse")
    medium_signals = ("blocked", "leaking", "overflow", "dark", "uncollected", "damaged")
    severity = "high" if any(word in text for word in high_signals) else "medium" if any(word in text for word in medium_signals) else "low"
    basis = [f"category keywords: {', '.join(matched)}"] if matched else ["no category keyword matched"]
    triggers = [word for word in (*high_signals, *medium_signals) if word in text]
    basis.append(f"severity signals: {', '.join(triggers)}" if triggers else "no elevated severity keyword matched")
    summary = text[:220] + ("…" if len(text) > 220 else "")
    return {"analysis_type": "transparent_keyword_rules", "suggested_category": category, "category_confidence": confidence, "severity": severity, "severity_basis": basis, "summary": summary, "human_review_required": True}


def token_for(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user_id
    return token


def current_user(authorization: str | None) -> sqlite3.Row:
    if not authorization:
        raise HTTPException(401, "Sign in to continue")
    token = authorization.replace("Bearer ", "", 1)
    user_id = SESSIONS.get(token)
    if not user_id:
        raise HTTPException(401, "Session expired")
    db = connect()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def user_payload(user: sqlite3.Row) -> dict[str, Any]:
    return {"id": user["id"], "display_name": user["display_name"], "role": user["role"], "balance": user["balance"]}


def issue_payload(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["is_fix_submitted"] = bool(data["is_fix_submitted"])
    return data


ESCALATION_THRESHOLD_DAYS = 3.0


def cluster_age_days(created_at: str | None) -> float:
    if not created_at:
        return 0.0
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400)


def cluster_payload(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["report_count"] = data.pop("report_count", 0)
    data["affected_count"] = data.get("affected_count", data["report_count"])
    age_days = cluster_age_days(data.get("created_at"))
    data["age_days"] = round(age_days, 1)
    # Escalation: a case with no officer action past the SLA window is
    # surfaced to admins instead of silently aging in the queue — the
    # "no escalation matrix" gap reported against comparable civic apps.
    data["escalated"] = data.get("status") == "open" and age_days >= ESCALATION_THRESHOLD_DAYS
    return data


def image_payload(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data.pop("c2pa_manifest_json", None)
    data.pop("analysis_error", None)
    data["has_c2pa_manifest"] = data.get("c2pa_status") == "valid"
    data["url"] = f"/api/images/{data['id']}"
    return data


def add_notification(db: sqlite3.Connection, user_id: str, issue_id: str | None, kind: str, title: str, message: str) -> None:
    db.execute(
        "INSERT INTO notifications(id,user_id,issue_id,type,title,message,is_read,created_at) VALUES(?,?,?,?,?,?,0,?)",
        (str(uuid.uuid4()), user_id, issue_id, kind, title, message, now_iso()),
    )


def ensure_settings(db: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    db.execute(
        "INSERT OR IGNORE INTO user_settings(user_id,notifications,location,created_at,updated_at) VALUES(?,?,?, ?, ?)",
        (user_id, 1, 1, now_iso(), now_iso()),
    )
    return db.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()


def profile_payload(db: sqlite3.Connection, user: sqlite3.Row) -> dict[str, Any]:
    result = user_payload(user)
    result["phone"] = user["phone"]
    result["total_reports"] = db.execute("SELECT COUNT(*) AS n FROM issues WHERE reporter_id=?", (user["id"],)).fetchone()["n"]
    result["resolved_reports"] = db.execute("SELECT COUNT(*) AS n FROM issues WHERE reporter_id=? AND status='resolved'", (user["id"],)).fetchone()["n"]
    if user["role"] == "admin":
        result["department"] = "Municipal Operations"
        result["active_assignments"] = db.execute("SELECT COUNT(*) AS n FROM crew_assignments WHERE assigned_by=? AND status='active'", (user["id"],)).fetchone()["n"]
        result["current_workload"] = db.execute("SELECT COUNT(*) AS n FROM issues WHERE status IN ('reported','in_progress','reopened')").fetchone()["n"]
        result["resolved_clusters"] = db.execute("SELECT COUNT(*) AS n FROM clusters WHERE status='resolved'").fetchone()["n"]
    return result


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance between two GPS coordinates in kilometres."""
    radius_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(min(1.0, a)))


def require_admin(authorization: str | None) -> sqlite3.Row:
    user = current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nagarsetu"}


@app.get("/api/public/overview")
def public_overview() -> dict[str, Any]:
    """A transparent civic pulse, calculated only from persisted submissions."""
    db = connect()
    total = db.execute("SELECT COUNT(*) n FROM issues").fetchone()["n"]
    unresolved = db.execute("SELECT COUNT(*) n FROM issues WHERE status IN ('reported','in_progress','reopened') AND is_fix_submitted=0").fetchone()["n"]
    claimed = db.execute("SELECT COUNT(*) n FROM issues WHERE is_fix_submitted=1 OR status='resolved'").fetchone()["n"]
    verified = db.execute("SELECT COUNT(*) n FROM (SELECT cluster_id,decision,ROW_NUMBER() OVER(PARTITION BY cluster_id ORDER BY created_at DESC,id DESC) AS rank FROM verification_records) WHERE rank=1 AND decision='verified'").fetchone()["n"]
    recurring = db.execute("SELECT COUNT(*) n FROM clusters WHERE recurrence_count>0 OR affected_count>1").fetchone()["n"]
    responses = db.execute("SELECT COUNT(DISTINCT cluster_id) n FROM official_statements").fetchone()["n"]
    categories = [dict(row) for row in db.execute("SELECT category,COUNT(*) AS count FROM issues GROUP BY category ORDER BY count DESC,category")]
    recent = [dict(row) for row in db.execute("SELECT i.tracking_id,i.title,i.category,i.address,i.lat,i.lng,i.status,i.created_at,COUNT(DISTINCT e.id) AS evidence_count FROM issues i LEFT JOIN issue_images e ON e.issue_id=i.id GROUP BY i.id ORDER BY i.created_at DESC LIMIT 8")]
    db.close()
    return {"counts": {"reports": total, "unresolved": unresolved, "recurring": recurring, "official_responses": responses, "resolution_claimed": claimed, "independently_verified": verified}, "categories": categories, "recent": recent, "data_basis": "Citizen-submitted reports stored in NagarSetu", "empty": total == 0}


@app.get("/api/public/incidents")
def public_incidents(category: str | None = None, status: str | None = None) -> dict[str, Any]:
    db = connect()
    public_status_sql = "CASE WHEN (SELECT v.decision FROM verification_records v WHERE v.cluster_id=i.cluster_id ORDER BY v.created_at DESC,v.id DESC LIMIT 1)='verified' THEN 'independently_verified' WHEN (SELECT v.decision FROM verification_records v WHERE v.cluster_id=i.cluster_id ORDER BY v.created_at DESC,v.id DESC LIMIT 1)='not_verified' THEN 'not_verified' WHEN i.status='resolved' THEN 'citizen_confirmed' WHEN i.status='reopened' THEN 'not_verified' WHEN i.is_fix_submitted=1 OR EXISTS(SELECT 1 FROM resolution_records r WHERE r.cluster_id=i.cluster_id) THEN 'resolution_claimed' WHEN EXISTS(SELECT 1 FROM official_statements s WHERE s.cluster_id=i.cluster_id) THEN 'response_published' WHEN i.status='in_progress' THEN 'under_review' ELSE 'reported' END"
    query = f"SELECT i.tracking_id,i.title,i.description,i.category,i.address,ROUND(i.lat,3) AS lat,ROUND(i.lng,3) AS lng,{public_status_sql} AS status,i.priority,i.created_at,COUNT(DISTINCT e.id) AS evidence_count FROM issues i LEFT JOIN issue_images e ON e.issue_id=i.id WHERE 1=1"
    args: list[Any] = []
    if category:
        query += " AND i.category=?"; args.append(category)
    if status in {"reported", "under_review", "response_published", "resolution_claimed", "citizen_confirmed", "independently_verified", "not_verified"}:
        query += f" AND ({public_status_sql})=?"; args.append(status)
    query += " GROUP BY i.id ORDER BY i.created_at DESC"
    incidents = [dict(row) for row in db.execute(query, args)]
    db.close()
    return {"incidents": incidents, "empty": not incidents}


@app.get("/api/public/incidents/{tracking_id}")
def public_incident(tracking_id: str) -> dict[str, Any]:
    db = connect()
    issue = db.execute("SELECT i.id,i.tracking_id,i.title,i.description,i.category,i.address,ROUND(i.lat,3) AS lat,ROUND(i.lng,3) AS lng,i.status,i.is_fix_submitted,i.priority,i.created_at,i.resolved_at,i.resolution_note,i.cluster_id FROM issues i WHERE i.tracking_id=?", (tracking_id,)).fetchone()
    if not issue:
        db.close(); raise HTTPException(404, "Incident not found")
    item = dict(issue)
    item["status"] = db.execute("SELECT CASE WHEN (SELECT decision FROM verification_records WHERE cluster_id=? ORDER BY created_at DESC,id DESC LIMIT 1)='verified' THEN 'independently_verified' WHEN (SELECT decision FROM verification_records WHERE cluster_id=? ORDER BY created_at DESC,id DESC LIMIT 1)='not_verified' THEN 'not_verified' WHEN ?='resolved' THEN 'citizen_confirmed' WHEN ?='reopened' THEN 'not_verified' WHEN (SELECT is_fix_submitted FROM issues WHERE id=?)=1 OR EXISTS(SELECT 1 FROM resolution_records WHERE issue_id=?) THEN 'resolution_claimed' WHEN EXISTS(SELECT 1 FROM official_statements WHERE cluster_id=?) THEN 'response_published' WHEN ?='in_progress' THEN 'under_review' ELSE 'reported' END", (issue["cluster_id"], issue["cluster_id"], issue["status"], issue["status"], issue["id"], issue["id"], issue["cluster_id"], issue["status"])).fetchone()[0]
    item["timeline"] = [dict(row) for row in db.execute("SELECT event_type,title,body,source_name,source_url,actor_type,verification_status,created_at FROM timeline_events WHERE cluster_id=? ORDER BY created_at,id", (issue["cluster_id"],))]
    statements = [dict(row) for row in db.execute("SELECT id,record_type,statement,promised_action,promised_by,published_at,promised_by_date,source_name,source_url,created_at AS recorded_at FROM official_statements WHERE cluster_id=? ORDER BY published_at,id", (issue["cluster_id"],))]
    item["official_statements"] = statements
    item["evidence"] = [{**dict(row), "url": f"/api/images/{row['id']}"} for row in db.execute("SELECT e.id,e.issue_id,i.tracking_id,i.title AS report_title,e.image_role,e.original_filename,e.created_at,e.final_authenticity_state,e.sha256,e.width,e.height FROM issue_images e JOIN issues i ON i.id=e.issue_id WHERE i.cluster_id=? ORDER BY e.created_at,e.id", (issue["cluster_id"],))]
    claims = [dict(row) for row in db.execute("SELECT r.id,r.issue_id,i.tracking_id,r.note,r.status,r.created_at,r.verification_at,r.image_id FROM resolution_records r LEFT JOIN issues i ON i.id=r.issue_id WHERE r.cluster_id=? ORDER BY r.created_at,r.id", (issue["cluster_id"],))]
    for claim in claims:
        claim["evidence_url"] = f"/api/images/{claim['image_id']}" if claim.get("image_id") else None
    item["resolution_claims"] = claims
    item["verification"] = [dict(row) for row in db.execute("SELECT v.evidence,v.evidence_url,v.decision,v.created_at,u.role AS reviewer_role FROM verification_records v JOIN users u ON u.id=v.verifier_id WHERE v.cluster_id=? ORDER BY v.created_at,v.id", (issue["cluster_id"],))]
    for statement in statements:
        if statement["record_type"] != "commitment":
            continue
        later_verifications = [record for record in item["verification"] if record["created_at"] >= statement["published_at"]]
        later_claims = [claim for claim in claims if claim["created_at"] >= statement["published_at"]]
        last_verification = later_verifications[-1] if later_verifications else None
        last_claim = later_claims[-1] if later_claims else None
        claim_updated_at = (last_claim or {}).get("verification_at") or (last_claim or {}).get("created_at")
        review_is_latest = last_verification and (not claim_updated_at or last_verification["created_at"] >= claim_updated_at)
        if review_is_latest and last_verification["decision"] == "verified":
            outcome = "independently_verified"
        elif review_is_latest and last_verification["decision"] == "not_verified":
            outcome = "not_verified"
        elif last_claim and last_claim["status"] == "citizen_rejected":
            outcome = "not_verified"
        elif last_claim and last_claim["status"] == "citizen_confirmed":
            outcome = "citizen_confirmed_not_independently_verified"
        elif last_claim:
            outcome = "resolution_claimed_awaiting_verification"
        elif statement["promised_by_date"] and statement["promised_by_date"] < datetime.now(timezone.utc).date().isoformat():
            outcome = "deadline_passed_no_resolution_recorded"
        else:
            outcome = "awaiting_follow_up"
        statement["reality_status"] = outcome
        statement["subsequent_evidence"] = [e for e in item["evidence"] if e["created_at"] >= statement["published_at"]]
        statement["subsequent_resolution_claims"] = later_claims
        statement["subsequent_reviews"] = later_verifications
    # Reporter identity and contact details are intentionally excluded.
    db.close()
    return item


@app.post("/api/intelligence/analyze")
def analyze_report(body: AnalyzeRequest) -> dict[str, Any]:
    """Return transparent local triage hints; the citizen remains in control."""
    return analyze_description(body.description)


@app.post("/api/admin/clusters/{cluster_id}/statements")
def add_official_statement(cluster_id: str, body: StatementRequest, authorization: str | None = Header(default=None)) -> dict[str, str]:
    user = require_admin(authorization)
    if not body.source_url.startswith(("https://", "http://")):
        raise HTTPException(400, "Provide the published source URL")
    if body.record_type == "commitment" and not (body.promised_action or "").strip():
        raise HTTPException(400, "A commitment needs a clearly stated promised action")
    try:
        datetime.fromisoformat(body.published_at.replace("Z", "+00:00"))
        if body.promised_by_date:
            datetime.strptime(body.promised_by_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, "Enter a valid publication date and promised deadline") from exc
    db = connect()
    if not db.execute("SELECT 1 FROM clusters WHERE id=?", (cluster_id,)).fetchone():
        db.close(); raise HTTPException(404, "Incident not found")
    stamp = now_iso(); event_id = str(uuid.uuid4())
    db.execute("INSERT INTO official_statements(id,cluster_id,statement,promised_action,promised_by,published_at,source_name,source_url,created_at,record_type,promised_by_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (event_id, cluster_id, body.statement.strip(), body.promised_action.strip() if body.promised_action else None, body.promised_by.strip() if body.promised_by else None, body.published_at, body.source_name.strip(), body.source_url, stamp, body.record_type, body.promised_by_date))
    title = "Official commitment published" if body.record_type == "commitment" else "Authority response published"
    db.execute("INSERT INTO timeline_events(id,cluster_id,event_type,title,body,source_name,source_url,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, body.record_type, title, body.statement.strip(), body.source_name.strip(), body.source_url, "official", "source_linked", stamp))
    db.commit(); db.close()
    return {"id": event_id, "status": "recorded", "record_type": body.record_type, "recorded_at": stamp}


@app.post("/api/admin/clusters/{cluster_id}/verification")
def record_independent_verification(cluster_id: str, body: IndependentVerificationRequest, authorization: str | None = Header(default=None)) -> dict[str, str]:
    user = require_admin(authorization)
    if body.evidence_url and not body.evidence_url.startswith(("https://", "http://")):
        raise HTTPException(400, "Evidence URL must use HTTP or HTTPS")
    db = connect()
    if not db.execute("SELECT 1 FROM clusters WHERE id=?", (cluster_id,)).fetchone():
        db.close(); raise HTTPException(404, "Incident not found")
    if body.decision == "verified" and len(body.evidence.strip()) < 10:
        db.close(); raise HTTPException(400, "Evidence is required for independent verification")
    if body.decision == "verified" and db.execute("SELECT 1 FROM resolution_records WHERE cluster_id=? AND submitted_by=? LIMIT 1", (cluster_id, user["id"])).fetchone():
        db.close(); raise HTTPException(403, "The person who submitted the resolution claim cannot independently verify it")
    stamp = now_iso()
    db.execute("INSERT INTO verification_records(id,cluster_id,verifier_id,evidence,evidence_url,decision,created_at) VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, user["id"], body.evidence.strip(), body.evidence_url, body.decision, stamp))
    claim_status = "independently_verified" if body.decision == "verified" else "independently_not_verified"
    db.execute("UPDATE resolution_records SET status=?,verification_at=? WHERE cluster_id=? AND status='pending_verification'", (claim_status, stamp, cluster_id))
    db.execute("INSERT INTO timeline_events(id,cluster_id,event_type,title,body,source_url,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, "verification", "Resolution independently verified" if body.decision == "verified" else "Resolution not verified", body.evidence.strip(), body.evidence_url, "reviewer", body.decision, stamp))
    db.commit(); db.close()
    return {"status": body.decision, "recorded_at": stamp}


@app.post("/api/auth/guest")
def guest(body: GuestRequest) -> dict[str, Any]:
    db = connect()
    user_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO users(id, display_name, role, balance, created_at) VALUES(?,?,?,?,?)",
        (user_id, body.display_name.strip() or "Citizen", "citizen", 0, now_iso()),
    )
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    return {"access_token": token_for(user_id), "user": user_payload(user)}


@app.post("/api/auth/google")
def google() -> dict[str, Any]:
    raise HTTPException(501, "Google sign-in is not configured. Use guest access or configure an OAuth provider.")


@app.post("/api/auth/phone/request")
def phone_request(body: PhoneRequest) -> dict[str, Any]:
    if os.getenv("DEMO_MODE", "false").lower() != "true":
        raise HTTPException(503, "Phone verification is unavailable because no SMS provider is configured.")
    code = "123456"
    db = connect()
    existing = db.execute("SELECT id FROM users WHERE phone = ?", (body.phone,)).fetchone()
    if not existing:
        db.execute(
            "INSERT INTO users(id, display_name, phone, role, balance, created_at) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), "Citizen", body.phone, "citizen", 0, now_iso()),
        )
    db.execute(
        "INSERT INTO otp_codes(phone, code, expires_at) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET code=excluded.code, expires_at=excluded.expires_at",
        (body.phone, code, (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()),
    )
    db.commit()
    db.close()
    return {"verification_sent": True, "phone": body.phone, "dev_code": code}


@app.post("/api/auth/phone/verify")
def phone_verify(body: PhoneVerifyRequest) -> dict[str, Any]:
    db = connect()
    otp = db.execute("SELECT * FROM otp_codes WHERE phone = ?", (body.phone,)).fetchone()
    if not otp:
        db.close()
        raise HTTPException(400, "No active verification code. Request a new code.")
    if datetime.fromisoformat(otp["expires_at"]) < datetime.now(timezone.utc):
        db.execute("DELETE FROM otp_codes WHERE phone = ?", (body.phone,))
        db.commit()
        db.close()
        raise HTTPException(400, "Verification code expired. Request a new code.")
    if otp["code"] != body.code:
        db.close()
        raise HTTPException(400, "Incorrect verification code.")
    user = db.execute("SELECT * FROM users WHERE phone = ?", (body.phone,)).fetchone()
    db.execute("DELETE FROM otp_codes WHERE phone = ?", (body.phone,))
    db.commit()
    db.close()
    return {"access_token": token_for(user["id"]), "user": user_payload(user)}


@app.get("/api/auth/admin/demo")
def admin_demo() -> dict[str, Any]:
    if os.getenv("DEMO_MODE", "false").lower() != "true":
        raise HTTPException(403, "Demo administrator sign-in is disabled")
    db = connect()
    admin = db.execute("SELECT * FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    db.close()
    return {"access_token": token_for(admin["id"]), "user": user_payload(admin)}


@app.get("/api/me")
def me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return {"user": user_payload(current_user(authorization))}


@app.get("/api/citizen/profile")
def citizen_profile(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "citizen":
        raise HTTPException(403, "Citizen access required")
    db = connect()
    profile = profile_payload(db, user)
    db.close()
    return {"profile": profile}


@app.put("/api/citizen/profile")
def update_citizen_profile(body: ProfileUpdateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "citizen":
        raise HTTPException(403, "Citizen access required")
    db = connect()
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(400, "Display name cannot be empty")
        db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
    if body.phone is not None and body.phone != user["phone"]:
        try:
            db.execute("UPDATE users SET phone=? WHERE id=?", (body.phone.strip(), user["id"]))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Phone number is already in use") from exc
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    result = profile_payload(db, updated)
    db.close()
    return {"profile": result, "user": user_payload(updated)}


@app.get("/api/admin/profile")
def admin_profile(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    result = profile_payload(db, user)
    db.close()
    return {"profile": result}


@app.put("/api/admin/profile")
def update_admin_profile(body: ProfileUpdateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(400, "Display name cannot be empty")
        db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
    if body.phone is not None and body.phone != user["phone"]:
        try:
            db.execute("UPDATE users SET phone=? WHERE id=?", (body.phone.strip(), user["id"]))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Contact is already in use") from exc
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    result = profile_payload(db, updated)
    db.close()
    return {"profile": result, "user": user_payload(updated)}


@app.get("/api/citizen/settings")
def citizen_settings(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    settings = ensure_settings(db, user["id"])
    db.commit()
    db.close()
    return {"settings": {"notifications": bool(settings["notifications"]), "location": bool(settings["location"])}}


@app.put("/api/citizen/settings")
def update_citizen_settings(body: SettingsRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    old = ensure_settings(db, user["id"])
    notifications = int(old["notifications"] if body.notifications is None else body.notifications)
    location = int(old["location"] if body.location is None else body.location)
    db.execute("UPDATE user_settings SET notifications=?, location=?, updated_at=? WHERE user_id=?", (notifications, location, now_iso(), user["id"]))
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(400, "Display name cannot be empty")
        db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
    db.commit()
    db.close()
    return {"settings": {"notifications": bool(notifications), "location": bool(location)}}


@app.get("/api/admin/settings")
def admin_settings(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    settings = ensure_settings(db, user["id"])
    db.commit()
    db.close()
    return {"settings": {"notifications": bool(settings["notifications"]), "location": bool(settings["location"])}}


@app.put("/api/admin/settings")
def update_admin_settings(body: SettingsRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    old = ensure_settings(db, user["id"])
    notifications = int(old["notifications"] if body.notifications is None else body.notifications)
    location = int(old["location"] if body.location is None else body.location)
    db.execute("UPDATE user_settings SET notifications=?, location=?, updated_at=? WHERE user_id=?", (notifications, location, now_iso(), user["id"]))
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(400, "Display name cannot be empty")
        db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
    db.commit()
    db.close()
    return {"settings": {"notifications": bool(notifications), "location": bool(location)}}


@app.get("/api/citizen/dashboard")
def citizen_dashboard(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    issues = db.execute("SELECT * FROM issues WHERE reporter_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    pending = db.execute("SELECT * FROM issues WHERE reporter_id = ? AND is_fix_submitted = 1 AND status = 'in_progress' ORDER BY created_at DESC LIMIT 1", (user["id"],)).fetchone()
    evidence_request = db.execute("SELECT * FROM issues WHERE reporter_id = ? AND evidence_request_status = 'requested' ORDER BY created_at DESC LIMIT 1", (user["id"],)).fetchone()
    notifications = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY is_read ASC, created_at DESC LIMIT 20", (user["id"],)).fetchall()
    db.close()
    return {"user": user_payload(user), "issues": [issue_payload(x) for x in issues], "pending_verification": issue_payload(pending) if pending else None, "pending_evidence_request": issue_payload(evidence_request) if evidence_request else None, "notifications": [dict(x) for x in notifications]}


def issue_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, " ".join(a.lower().split()), " ".join(b.lower().split())).ratio()

def compute_priority(category: str, report_count: int, age_days: float, description: str, recurrence: int = 0) -> int:
    severity = {"Pothole": 28, "Water Leak": 30, "Streetlight": 18, "Garbage": 16, "Park Issue": 12}.get(category, 14)
    evidence = min(15, round(max(0, len(description.strip()) - 20) / 25))
    impact = min(25, report_count * 4)
    age = min(15, round(age_days * 2))
    recurrence_bonus = min(12, recurrence * 4)
    return max(1, min(100, severity + evidence + impact + age + recurrence_bonus))

@app.post("/api/issues")
def create_issue(body: IssueRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if not body.description.strip():
        raise HTTPException(400, "Please add a description of the issue.")
    db = connect()
    candidates = db.execute("SELECT * FROM clusters WHERE category = ? AND status != 'resolved'", (body.category,)).fetchall()
    nearby = None
    best_distance = 999.0
    best_similarity = 0.0
    for c in candidates:
        distance = haversine_km(c["lat"], c["lng"], body.lat, body.lng)
        if distance <= 0.1:
            existing = db.execute("SELECT description FROM issues WHERE cluster_id=? ORDER BY created_at DESC LIMIT 5", (c["id"],)).fetchall()
            similarity = max([issue_similarity(body.description, r["description"]) for r in existing] or [0.0])
            if distance < best_distance and (similarity >= 0.25 or not existing):
                nearby, best_distance, best_similarity = c, distance, similarity
    duplicate = nearby is not None
    if nearby:
        cluster_id = nearby["id"]
        report_count = db.execute("SELECT COUNT(*) AS n FROM issues WHERE cluster_id=?", (cluster_id,)).fetchone()["n"] + 1
        recurrence = nearby["recurrence_count"]
    else:
        cluster_id = str(uuid.uuid4())
        report_count = 1
        recurrence = 0
        db.execute("INSERT INTO clusters VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (cluster_id, body.category, f"{body.category} reported", body.address, body.lat, body.lng, "open", 55, 1, 0, now_iso(), None))
    issue_id = str(uuid.uuid4())
    tracking_id = f"CL-{secrets.randbelow(900) + 100}"
    while db.execute("SELECT 1 FROM issues WHERE tracking_id = ?", (tracking_id,)).fetchone():
        tracking_id = f"CL-{secrets.randbelow(900) + 100}"
    title = f"{body.category} near {body.address}"
    db.execute("INSERT INTO issues(id,tracking_id,reporter_id,cluster_id,category,title,description,address,lat,lng,status,priority,votes,reward,is_fix_submitted,created_at,resolved_at,resolution_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (issue_id, tracking_id, user["id"], cluster_id, body.category, title, body.description.strip(), body.address, body.lat, body.lng, "reported", "medium", 1, 0, 0, now_iso(), None, None))
    stamp = now_iso()
    db.execute("INSERT INTO timeline_events(id,cluster_id,issue_id,event_type,title,body,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, issue_id, "citizen_report", "Citizen report received", body.description.strip(), "citizen", "unverified", stamp))
    if nearby:
        db.execute("UPDATE clusters SET affected_count=?, priority_score=? WHERE id=?", (report_count, compute_priority(body.category, report_count, 0, body.description, recurrence), cluster_id))
    else:
        db.execute("UPDATE clusters SET priority_score=? WHERE id=?", (compute_priority(body.category, 1, 0, body.description), cluster_id))
    message = f"Your report {tracking_id} has been submitted." + (f" It joined an existing cluster with {report_count} reports." if duplicate else " A new civic issue cluster was created.")
    add_notification(db, user["id"], issue_id, "issue_submitted", "Issue submitted", message)
    for admin_row in db.execute("SELECT id FROM users WHERE role='admin'").fetchall():
        add_notification(db, admin_row["id"], issue_id, "new_issue", "New civic issue", f"{title} was reported at {body.address}.")
    db.commit()
    issue = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    updated = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    cluster = db.execute("SELECT c.*, COUNT(i.id) AS report_count FROM clusters c LEFT JOIN issues i ON i.cluster_id=c.id WHERE c.id=? GROUP BY c.id", (cluster_id,)).fetchone()
    db.close()
    return {"issue": issue_payload(issue), "cluster": cluster_payload(cluster), "user": user_payload(updated), "duplicate": duplicate, "match_distance_m": round(best_distance * 1000, 1) if duplicate else None, "text_similarity": round(best_similarity, 2) if duplicate else None}

@app.post("/api/issues/{issue_id}/images")
async def upload_issue_image(
    issue_id: str,
    image: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    issue = db.execute("SELECT id FROM issues WHERE id = ? AND reporter_id = ?", (issue_id, user["id"])).fetchone()
    db.close()
    if not issue:
        raise HTTPException(404, "Issue not found")
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    try:
        image_meta = validate_image_bytes(raw, image.content_type)
        visual_hash = perceptual_hash_bytes(raw)
    except ValueError as exc:
        reason = str(exc)
        status_code = 413 if reason in {"file_too_large", "too_many_pixels"} else 415 if reason == "unsupported_media_type" else 400
        raise HTTPException(status_code, reason) from exc
    image_id = str(uuid.uuid4())
    suffix = Path(image.filename or "upload").suffix.lower() or ".bin"
    object_key = f"{image_id}{suffix}"
    path = UPLOAD_DIR / object_key
    path.write_bytes(raw)
    c2pa_result = inspect_c2pa(path)
    detector_result = await inspect_with_sightengine(path, image.content_type or "application/octet-stream")
    final_state, review_status = combine_evidence(c2pa_result, detector_result)
    analysis_errors = [str(result["error"]) for result in (c2pa_result, detector_result) if result.get("error")]
    db = connect()
    db.execute(
        """INSERT INTO issue_images(
          id, issue_id, image_role, original_filename, detected_media_type, sha256, perceptual_hash, object_key,
          byte_size, width, height, c2pa_status, c2pa_trust_status, c2pa_manifest_json,
          ai_detector_provider, ai_probability, ai_detector_status, review_status,
          final_authenticity_state, provider_request_id, analysis_error, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            image_id, issue_id, "report", Path(image.filename or "upload").name, image.content_type or "unknown",
            image_meta["sha256"], visual_hash, object_key, len(raw), image_meta["width"], image_meta["height"],
            c2pa_result.get("status", "error"), c2pa_result.get("trust_status", "unknown"),
            json.dumps(c2pa_result.get("manifest_store"), default=str) if c2pa_result.get("manifest_store") else None,
            detector_result.get("provider") or ("sightengine" if os.getenv("SIGHTENGINE_API_USER") and os.getenv("SIGHTENGINE_API_SECRET") else "local"),
            detector_result.get("probability"), detector_result.get("status", "not_run"), review_status,
            final_state, detector_result.get("request_id"), "; ".join(analysis_errors) or None, now_iso(),
        ),
    )
    db.execute("INSERT INTO timeline_events(id,cluster_id,issue_id,event_type,title,body,actor_type,verification_status,created_at) SELECT ?,cluster_id,id,'evidence_added','Citizen photo evidence added','A citizen-submitted photograph was attached to this report. Image provenance checks are advisory.', 'citizen','unverified',? FROM issues WHERE id=?", (str(uuid.uuid4()), now_iso(), issue_id))
    db.commit()
    stored = db.execute("SELECT * FROM issue_images WHERE id = ?", (image_id,)).fetchone()
    matches = []
    for row in db.execute("SELECT i.tracking_id,i.title,i.category,i.address,e.perceptual_hash FROM issue_images e JOIN issues i ON i.id=e.issue_id WHERE e.id!=? AND e.perceptual_hash IS NOT NULL", (image_id,)):
        distance = (int(visual_hash, 16) ^ int(row["perceptual_hash"], 16)).bit_count()
        if distance <= 8:
            matches.append({"tracking_id": row["tracking_id"], "title": row["title"], "category": row["category"], "address": row["address"], "hash_distance": distance, "review_required": True})
    matches.sort(key=lambda item: item["hash_distance"])
    db.close()
    return {"image": image_payload(stored), "c2pa": c2pa_result, "ai_detector": detector_result, "final_authenticity_state": final_state, "review_status": review_status, "similar_evidence_suggestions": matches[:5]}


MAX_VIDEO_BYTES = 25 * 1024 * 1024  # 25MB — supplementary evidence only
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}


@app.post("/api/issues/{issue_id}/videos")
async def upload_issue_video(
    issue_id: str,
    video: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    # Video is SUPPLEMENTARY context only — it is never a substitute for the
    # required report photo and never satisfies the evidence gate on its own.
    # There is no authenticity pipeline (C2PA / AI-detector) for video yet,
    # so treating it as equivalent to the photo evidence would reopen the
    # exact "unverified proof" gap the photo pipeline exists to close.
    user = current_user(authorization)
    db = connect()
    issue = db.execute("SELECT id FROM issues WHERE id = ? AND reporter_id = ?", (issue_id, user["id"])).fetchone()
    db.close()
    if not issue:
        raise HTTPException(404, "Issue not found")
    if video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(415, "unsupported_media_type")
    raw = await video.read(MAX_VIDEO_BYTES + 1)
    if len(raw) > MAX_VIDEO_BYTES:
        raise HTTPException(413, "file_too_large")
    video_id = str(uuid.uuid4())
    suffix = Path(video.filename or "upload").suffix.lower() or ".mp4"
    object_key = f"{video_id}{suffix}"
    path = UPLOAD_DIR / object_key
    path.write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    db = connect()
    db.execute(
        """INSERT INTO issue_images(
          id, issue_id, image_role, original_filename, detected_media_type, sha256, object_key,
          byte_size, width, height, c2pa_status, c2pa_trust_status, c2pa_manifest_json,
          ai_detector_provider, ai_probability, ai_detector_status, review_status,
          final_authenticity_state, provider_request_id, analysis_error, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            video_id, issue_id, "report_video", Path(video.filename or "upload").name,
            video.content_type or "unknown", sha256, object_key, len(raw), None, None,
            "not_applicable", "unknown", None, None, None, "not_applicable",
            "not_required", "supplementary_unverified", None, None, now_iso(),
        ),
    )
    db.commit()
    stored = db.execute("SELECT * FROM issue_images WHERE id = ?", (video_id,)).fetchone()
    db.close()
    return {"video": image_payload(stored)}


@app.get("/api/issues/{tracking_id}")
def get_issue(tracking_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    issue = db.execute("SELECT * FROM issues WHERE tracking_id = ? AND reporter_id = ?", (tracking_id, user["id"])).fetchone()
    db.close()
    if not issue:
        raise HTTPException(404, "Issue not found")
    return {"issue": issue_payload(issue)}


@app.get("/api/citizen/verify-target")
def verify_target(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    issue = db.execute("SELECT * FROM issues WHERE reporter_id = ? AND is_fix_submitted = 1 AND status = 'in_progress' ORDER BY created_at DESC LIMIT 1", (user["id"],)).fetchone()
    if not issue:
        db.close()
        return {"issue": None}
    images = db.execute("SELECT * FROM issue_images WHERE issue_id = ? ORDER BY CASE image_role WHEN 'report' THEN 0 ELSE 1 END, created_at", (issue["id"],)).fetchall()
    db.close()
    payload = issue_payload(issue)
    payload["images"] = [image_payload(image) for image in images]
    return {"issue": payload}


@app.get("/api/citizen/notifications")
def citizen_notifications(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    rows = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY is_read ASC, created_at DESC", (user["id"],)).fetchall()
    db.close()
    return {"notifications": [dict(row) for row in rows]}


@app.post("/api/citizen/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, authorization: str | None = Header(default=None)) -> dict[str, bool]:
    user = current_user(authorization)
    db = connect()
    updated = db.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, user["id"])).rowcount
    db.commit()
    db.close()
    if not updated:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


@app.get("/api/admin/notifications")
def admin_notifications(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY is_read ASC, created_at DESC", (user["id"],)).fetchall()
    db.close()
    return {"notifications": [dict(row) for row in rows]}


@app.post("/api/admin/notifications/{notification_id}/read")
def mark_admin_notification_read(notification_id: str, authorization: str | None = Header(default=None)) -> dict[str, bool]:
    user = require_admin(authorization)
    db = connect()
    updated = db.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notification_id, user["id"])).rowcount
    db.commit()
    db.close()
    if not updated:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


@app.get("/api/images/{image_id}")
def serve_image(image_id: str) -> FileResponse:
    db = connect()
    image = db.execute("SELECT object_key, detected_media_type FROM issue_images WHERE id = ?", (image_id,)).fetchone()
    db.close()
    if not image:
        raise HTTPException(404, "Image not found")
    path = (UPLOAD_DIR / Path(image["object_key"]).name).resolve()
    if path.parent != UPLOAD_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "Image file not found")
    return FileResponse(path, media_type=image["detected_media_type"])



@app.post("/api/admin/issues/{issue_id}/request-real-photo")
def request_real_photo(issue_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    admin = require_admin(authorization)
    db = connect()
    issue = db.execute(
        "SELECT * FROM issues WHERE id=?",
        (issue_id,),
    ).fetchone()
    if not issue:
        db.close()
        raise HTTPException(404, "Issue not found")
    if issue["status"] == "resolved":
        db.close()
        raise HTTPException(400, "This issue is already resolved.")
    note = "The submitted image appears AI-generated. Please upload a real photograph of the reported issue for verification."
    db.execute(
        "UPDATE issues SET evidence_request_status='requested', evidence_request_note=? WHERE id=?",
        (note, issue_id),
    )
    add_notification(
        db,
        issue["reporter_id"],
        issue_id,
        "real_photo_requested",
        "Real photo requested",
        note,
    )
    db.commit()
    updated = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    db.close()
    return {"ok": True, "issue": issue_payload(updated), "message": "Request sent to the citizen."}


@app.post("/api/citizen/issues/{issue_id}/evidence")
async def upload_requested_evidence(
    issue_id: str,
    image: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "citizen":
        raise HTTPException(403, "Citizen access required")
    db = connect()
    issue = db.execute(
        "SELECT * FROM issues WHERE id=? AND reporter_id=?",
        (issue_id, user["id"]),
    ).fetchone()
    db.close()
    if not issue:
        raise HTTPException(404, "Issue not found")
    if issue["evidence_request_status"] != "requested":
        raise HTTPException(400, "This issue does not currently have a real-photo request.")

    raw = await image.read(MAX_IMAGE_BYTES + 1)
    try:
        image_meta = validate_image_bytes(raw, image.content_type)
    except ValueError as exc:
        reason = str(exc)
        status_code = 413 if reason in {"file_too_large", "too_many_pixels"} else 415 if reason == "unsupported_media_type" else 400
        raise HTTPException(status_code, reason) from exc

    image_id = str(uuid.uuid4())
    suffix = Path(image.filename or "real-evidence").suffix.lower() or ".bin"
    object_key = f"{image_id}{suffix}"
    path = UPLOAD_DIR / object_key
    path.write_bytes(raw)
    c2pa_result = inspect_c2pa(path)
    detector_result = await inspect_with_sightengine(path, image.content_type or "application/octet-stream")
    final_state, review_status = combine_evidence(c2pa_result, detector_result)
    errors = [str(result["error"]) for result in (c2pa_result, detector_result) if result.get("error")]

    db = connect()
    db.execute(
        """INSERT INTO issue_images(
          id, issue_id, image_role, original_filename, detected_media_type, sha256, object_key,
          byte_size, width, height, c2pa_status, c2pa_trust_status, c2pa_manifest_json,
          ai_detector_provider, ai_probability, ai_detector_status, review_status,
          final_authenticity_state, provider_request_id, analysis_error, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            image_id, issue_id, "replacement", Path(image.filename or "real-evidence").name,
            image.content_type or "unknown", image_meta["sha256"], object_key, len(raw),
            image_meta["width"], image_meta["height"],
            c2pa_result.get("status", "error"), c2pa_result.get("trust_status", "unknown"),
            json.dumps(c2pa_result.get("manifest_store"), default=str) if c2pa_result.get("manifest_store") else None,
            detector_result.get("provider") or ("sightengine" if os.getenv("SIGHTENGINE_API_USER") and os.getenv("SIGHTENGINE_API_SECRET") else "local"),
            detector_result.get("probability"), detector_result.get("status", "not_run"),
            review_status, final_state, detector_result.get("request_id"),
            "; ".join(errors) or None, now_iso(),
        ),
    )
    db.execute(
        "UPDATE issues SET evidence_request_status='submitted', evidence_request_note=? WHERE id=?",
        ("Citizen submitted replacement evidence for officer review.", issue_id),
    )
    for admin_row in db.execute("SELECT id FROM users WHERE role='admin'").fetchall():
        add_notification(
            db, admin_row["id"], issue_id, "replacement_evidence_submitted",
            "Replacement evidence received",
            f"{issue['tracking_id']} has a new citizen-uploaded replacement photo for review.",
        )
    db.commit()
    stored = db.execute("SELECT * FROM issue_images WHERE id=?", (image_id,)).fetchone()
    updated = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    db.close()
    return {
        "ok": True,
        "issue": issue_payload(updated),
        "image": image_payload(stored),
        "c2pa": c2pa_result,
        "ai_detector": detector_result,
        "final_authenticity_state": final_state,
        "review_status": review_status,
        "message": "Real photo uploaded and sent to the municipal officer for review.",
    }


@app.post("/api/issues/{issue_id}/verify")
def verify_issue(issue_id: str, body: VerifyRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    db = connect()
    issue = db.execute("SELECT * FROM issues WHERE id = ? AND reporter_id = ?", (issue_id, user["id"])).fetchone()
    if not issue:
        db.close()
        raise HTTPException(404, "Issue not found")
    if issue["status"] != "in_progress" or not issue["is_fix_submitted"]:
        db.close()
        raise HTTPException(400, "This issue is not awaiting verification")
    stamp = now_iso()
    if body.approved:
        db.execute("UPDATE issues SET status='resolved', resolved_at=? WHERE id=?", (stamp, issue_id))
        remaining = db.execute("SELECT COUNT(*) AS n FROM issues WHERE cluster_id=? AND id != ? AND status NOT IN ('resolved','reopened')", (issue["cluster_id"], issue_id)).fetchone()["n"]
        if remaining == 0:
            db.execute("UPDATE clusters SET status='resolved', resolved_at=? WHERE id=?", (stamp, issue["cluster_id"]))
        else:
            db.execute("UPDATE clusters SET status='in_progress', resolved_at=NULL WHERE id=?", (issue["cluster_id"],))
        add_notification(db, user["id"], issue_id, "issue_resolved", "Issue resolved", "Thank you for confirming the fix.")
        db.execute("UPDATE resolution_records SET status='citizen_confirmed',verification_at=? WHERE issue_id=? AND status='pending_verification'", (stamp, issue_id))
        message = "Thank you for confirming the fix."
        event_title, event_body = "Citizen confirmed the reported fix", "The original reporter confirmed the reported fix. This is a citizen confirmation, not an independent verification."
    else:
        db.execute("UPDATE issues SET status='reopened', is_fix_submitted=0 WHERE id=?", (issue_id,))
        db.execute("UPDATE clusters SET status='open', resolved_at=NULL, recurrence_count=recurrence_count+1, priority_score=MIN(100, priority_score+8) WHERE id=?", (issue["cluster_id"],))
        add_notification(db, user["id"], issue_id, "issue_reopened", "Issue reopened", "The issue was reopened for the municipal team.")
        db.execute("UPDATE resolution_records SET status='citizen_rejected',verification_at=? WHERE issue_id=? AND status='pending_verification'", (stamp, issue_id))
        message = "The issue was reopened for the municipal team."
        event_title, event_body = "Citizen did not confirm the fix", "The original reporter did not confirm the reported fix; the issue was reopened."
    db.execute("INSERT INTO timeline_events(id,cluster_id,issue_id,event_type,title,body,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), issue["cluster_id"], issue_id, "citizen_follow_up", event_title, event_body, "citizen", "citizen_confirmed" if body.approved else "not_confirmed", stamp))
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    db.close()
    return {"message": message, "user": user_payload(updated)}


@app.get("/api/admin/clusters")
def admin_clusters(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    db = connect()
    rows = db.execute(
        "SELECT c.*, COUNT(i.id) AS report_count FROM clusters c LEFT JOIN issues i ON i.cluster_id=c.id GROUP BY c.id ORDER BY CASE c.status WHEN 'open' THEN 0 ELSE 1 END, c.priority_score DESC"
    ).fetchall()
    db.close()
    return {"clusters": [cluster_payload(x) for x in rows]}


@app.get("/api/admin/issues")
def admin_issues(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    rows = db.execute(
        """SELECT i.*, c.title AS cluster_title, c.address AS cluster_address, c.priority_score AS cluster_priority
           FROM issues i LEFT JOIN clusters c ON c.id=i.cluster_id
           ORDER BY i.created_at DESC LIMIT 50"""
    ).fetchall()
    db.close()
    return {"issues": [issue_payload(x) | {"cluster_title": x["cluster_title"], "cluster_address": x["cluster_address"], "cluster_priority": x["cluster_priority"]} for x in rows]}


@app.get("/api/admin/clusters/{cluster_id}")
def admin_cluster_detail(cluster_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    db = connect()
    cluster = db.execute("SELECT c.*, COUNT(i.id) AS report_count FROM clusters c LEFT JOIN issues i ON i.cluster_id=c.id WHERE c.id=? GROUP BY c.id", (cluster_id,)).fetchone()
    issues = db.execute("SELECT * FROM issues WHERE cluster_id=? ORDER BY created_at DESC", (cluster_id,)).fetchall()
    images = db.execute("SELECT * FROM issue_images WHERE issue_id IN (SELECT id FROM issues WHERE cluster_id=?) ORDER BY created_at DESC", (cluster_id,)).fetchall()
    assignment = db.execute("SELECT a.*, c.name AS crew_name, c.specialty FROM crew_assignments a JOIN crews c ON c.id=a.crew_id WHERE a.cluster_id=? AND a.status='active' ORDER BY a.assigned_at DESC LIMIT 1", (cluster_id,)).fetchone()
    comments = db.execute("SELECT c.*, u.display_name AS author_name FROM comments c JOIN users u ON u.id=c.user_id WHERE c.cluster_id=? ORDER BY c.created_at ASC", (cluster_id,)).fetchall()
    db.close()
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    images_by_issue: dict[str, list[dict[str, Any]]] = {}
    for image in images:
        images_by_issue.setdefault(image["issue_id"], []).append(image_payload(image))
    issue_data = []
    for issue in issues:
        item = issue_payload(issue)
        item["images"] = images_by_issue.get(issue["id"], [])
        issue_data.append(item)
    return {"cluster": cluster_payload(cluster), "issues": issue_data, "assignment": dict(assignment) if assignment else None, "comments": [dict(row) for row in comments]}


@app.get("/api/admin/escalations")
def admin_escalations(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    db = connect()
    rows = db.execute("SELECT c.*, COUNT(i.id) AS report_count FROM clusters c LEFT JOIN issues i ON i.cluster_id=c.id WHERE c.status != 'resolved' GROUP BY c.id ORDER BY c.priority_score DESC, c.created_at ASC").fetchall()
    escalations = []
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            age_days = (now - datetime.fromisoformat(row["created_at"])).total_seconds() / 86400
        except (TypeError, ValueError):
            age_days = 0
        reasons = []
        if row["priority_score"] >= 75:
            reasons.append("high priority")
        if row["status"] == "reopened":
            reasons.append("reopened by citizen")
        if row["recurrence_count"] > 0:
            reasons.append("recurring issue")
        if age_days >= 3:
            reasons.append("overdue")
        if reasons:
            item = cluster_payload(row)
            item.update({"id": row["id"], "cluster_id": row["id"], "reason": ", ".join(reasons), "age_days": round(age_days, 1)})
            escalations.append(item)
    db.close()
    return {"escalations": escalations}


@app.get("/api/admin/clusters/{cluster_id}/comments")
def get_cluster_comments(cluster_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    db = connect()
    if not db.execute("SELECT id FROM clusters WHERE id=?", (cluster_id,)).fetchone():
        db.close()
        raise HTTPException(404, "Cluster not found")
    rows = db.execute("SELECT c.*, u.display_name AS author_name, u.role AS author_role FROM comments c JOIN users u ON u.id=c.user_id WHERE c.cluster_id=? ORDER BY c.created_at ASC", (cluster_id,)).fetchall()
    db.close()
    return {"comments": [dict(row) for row in rows]}


@app.post("/api/admin/clusters/{cluster_id}/comments")
def add_cluster_comment(cluster_id: str, body: CommentRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    text = (body.body or body.text or "").strip()
    if not text:
        raise HTTPException(400, "Comment cannot be empty")
    db = connect()
    if not db.execute("SELECT id FROM clusters WHERE id=?", (cluster_id,)).fetchone():
        db.close()
        raise HTTPException(404, "Cluster not found")
    comment_id = str(uuid.uuid4())
    stamp = now_iso()
    db.execute("INSERT INTO comments(id,cluster_id,user_id,body,created_at) VALUES(?,?,?,?,?)", (comment_id, cluster_id, user["id"], text, stamp))
    db.commit()
    row = db.execute("SELECT c.*, u.display_name AS author_name, u.role AS author_role FROM comments c JOIN users u ON u.id=c.user_id WHERE c.id=?", (comment_id,)).fetchone()
    db.close()
    return {"comment": dict(row)}


@app.get("/api/admin/crews")
def admin_crews(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    db = connect()
    rows = db.execute("SELECT c.*, COUNT(a.id) AS active_assignments FROM crews c LEFT JOIN crew_assignments a ON a.crew_id=c.id AND a.status='active' GROUP BY c.id ORDER BY c.name").fetchall()
    db.close()
    return {"crews": [dict(row) for row in rows]}


class CrewCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    specialty: str = Field(default="General civic maintenance", max_length=120)


@app.post("/api/admin/crews")
def create_admin_crew(body: CrewCreateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    db = connect()
    crew_id = str(uuid.uuid4())
    db.execute("INSERT INTO crews(id,name,specialty,status,created_at) VALUES(?,?,?,?,?)", (crew_id, body.name.strip(), body.specialty.strip() or "General civic maintenance", "available", now_iso()))
    db.commit()
    crew = db.execute("SELECT * FROM crews WHERE id=?", (crew_id,)).fetchone()
    db.close()
    return {"crew": dict(crew)}


@app.post("/api/admin/clusters/{cluster_id}/assign")
def assign_cluster_crew(cluster_id: str, body: AssignmentRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    if not db.execute("SELECT id FROM clusters WHERE id=?", (cluster_id,)).fetchone():
        db.close()
        raise HTTPException(404, "Cluster not found")
    crew = db.execute("SELECT * FROM crews WHERE id=?", (body.crew_id,)).fetchone()
    if not crew:
        db.close()
        raise HTTPException(404, "Crew not found")
    db.execute("UPDATE crew_assignments SET status='reassigned' WHERE cluster_id=? AND status='active'", (cluster_id,))
    assignment_id = str(uuid.uuid4())
    stamp = now_iso()
    db.execute("INSERT INTO crew_assignments(id,cluster_id,crew_id,assigned_by,status,assigned_at) VALUES(?,?,?,?,?,?)", (assignment_id, cluster_id, crew["id"], user["id"], "active", stamp))
    db.execute("UPDATE clusters SET status=CASE WHEN status='open' THEN 'in_progress' ELSE status END WHERE id=?", (cluster_id,))
    reporters = db.execute("SELECT DISTINCT reporter_id,id FROM issues WHERE cluster_id=? AND status!='resolved'", (cluster_id,)).fetchall()
    for reporter in reporters:
        add_notification(db, reporter["reporter_id"], reporter["id"], "crew_assigned", "Crew assigned", f"{crew['name']} has been assigned to your issue.")
    db.commit()
    assignment = db.execute("SELECT a.*, c.name, c.specialty FROM crew_assignments a JOIN crews c ON c.id=a.crew_id WHERE a.id=?", (assignment_id,)).fetchone()
    db.close()
    return {"assignment": dict(assignment), "crew": dict(crew)}


@app.post("/api/admin/clusters/{cluster_id}/resolve")
def resolve_cluster(cluster_id: str, body: ResolveRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    db = connect()
    cluster = db.execute("SELECT id FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    if not cluster:
        db.close()
        raise HTTPException(404, "Cluster not found")
    stamp = now_iso()
    db.execute("UPDATE clusters SET status='in_progress', resolved_at=NULL WHERE id=?", (cluster_id,))
    db.execute("UPDATE issues SET status='in_progress', is_fix_submitted=1, resolution_note=? WHERE cluster_id=? AND status != 'resolved'", (body.resolution_note, cluster_id))
    for affected in db.execute("SELECT reporter_id,id FROM issues WHERE cluster_id=? AND status='in_progress'", (cluster_id,)).fetchall():
        add_notification(db, affected["reporter_id"], affected["id"], "resolution_submitted", "Resolution submitted", "Municipal team has submitted a resolution for your issue.")
        db.execute("INSERT INTO resolution_records(id,cluster_id,issue_id,submitted_by,note,status,created_at) VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, affected["id"], user["id"], body.resolution_note, "pending_verification", now_iso()))
        db.execute("INSERT INTO timeline_events(id,cluster_id,issue_id,event_type,title,body,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, affected["id"], "resolution_claim", "Resolution claimed", body.resolution_note, "administrator", "awaiting_review", now_iso()))
    db.commit()
    db.close()
    return {"status": "in_progress", "cluster_id": cluster_id, "message": "Resolution submitted. Citizen verification is now pending."}


@app.post("/api/admin/clusters/{cluster_id}/resolution")
async def submit_resolution(
    cluster_id: str,
    resolution_note: str = Form(default="Resolved by municipal maintenance team."),
    image: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user = require_admin(authorization)
    db = connect()
    cluster = db.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    issue = db.execute("SELECT * FROM issues WHERE cluster_id = ? AND status != 'resolved' ORDER BY created_at DESC LIMIT 1", (cluster_id,)).fetchone()
    db.close()
    if not cluster or not issue:
        raise HTTPException(404, "Open issue or cluster not found")
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    try:
        image_meta = validate_image_bytes(raw, image.content_type)
    except ValueError as exc:
        reason = str(exc)
        status_code = 413 if reason in {"file_too_large", "too_many_pixels"} else 415 if reason == "unsupported_media_type" else 400
        raise HTTPException(status_code, reason) from exc
    image_id = str(uuid.uuid4())
    suffix = Path(image.filename or "resolution").suffix.lower() or ".bin"
    object_key = f"{image_id}{suffix}"
    (UPLOAD_DIR / object_key).write_bytes(raw)
    path = UPLOAD_DIR / object_key
    c2pa_result = inspect_c2pa(path)
    detector_result = await inspect_with_sightengine(path, image.content_type or "application/octet-stream")
    final_state, review_status = combine_evidence(c2pa_result, detector_result)
    errors = [str(result["error"]) for result in (c2pa_result, detector_result) if result.get("error")]
    db = connect()
    affected = db.execute("SELECT reporter_id, id FROM issues WHERE cluster_id=? AND status != 'resolved'", (cluster_id,)).fetchall()
    if not affected:
        db.close()
        raise HTTPException(404, "No open issues remain in this cluster.")
    row_image_id = str(uuid.uuid4())
    db.execute(
            """INSERT INTO issue_images(
              id, issue_id, image_role, original_filename, detected_media_type, sha256, object_key,
              byte_size, width, height, c2pa_status, c2pa_trust_status, c2pa_manifest_json,
              ai_detector_provider, ai_probability, ai_detector_status, review_status,
              final_authenticity_state, provider_request_id, analysis_error, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row_image_id, issue["id"], "resolution", Path(image.filename or "resolution").name, image.content_type or "unknown",
             image_meta["sha256"], object_key, len(raw), image_meta["width"], image_meta["height"],
             c2pa_result.get("status", "error"), c2pa_result.get("trust_status", "unknown"),
             json.dumps(c2pa_result.get("manifest_store"), default=str) if c2pa_result.get("manifest_store") else None,
             detector_result.get("provider") or ("sightengine" if os.getenv("SIGHTENGINE_API_USER") and os.getenv("SIGHTENGINE_API_SECRET") else "local"),
             detector_result.get("probability"), detector_result.get("status", "not_run"), review_status, final_state,
             detector_result.get("request_id"), "; ".join(errors) or None, now_iso()),
        )
    stamp = now_iso()
    db.execute("UPDATE clusters SET status='in_progress', resolved_at=NULL WHERE id=?", (cluster_id,))
    db.execute("UPDATE issues SET status='in_progress', is_fix_submitted=1, resolution_note=? WHERE cluster_id=? AND status != 'resolved'", (resolution_note.strip() or "Resolved by municipal maintenance team.", cluster_id))
    for row in affected:
        add_notification(db, row["reporter_id"], row["id"], "resolution_submitted", "Resolution submitted", "Municipal team has submitted a resolution for your issue.")
        db.execute("INSERT INTO resolution_records(id,cluster_id,issue_id,submitted_by,note,status,created_at,image_id) VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, row["id"], user["id"], resolution_note.strip() or "Resolution evidence submitted by administrator.", "pending_verification", stamp, row_image_id))
        db.execute("INSERT INTO timeline_events(id,cluster_id,issue_id,event_type,title,body,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, row["id"], "resolution_claim", "Resolution claimed", resolution_note.strip() or "Resolution evidence submitted by administrator.", "administrator", "awaiting_review", stamp))
    db.execute("INSERT INTO timeline_events(id,cluster_id,issue_id,event_type,title,body,actor_type,verification_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), cluster_id, issue["id"], "evidence_added", "Authority submitted resolution evidence", "A photograph was attached to the resolution claim; its upload timestamp and image checks are shown in the evidence log.", "administrator", final_state, stamp))
    db.commit()
    stored = db.execute("SELECT * FROM issue_images WHERE id=?", (row_image_id,)).fetchone()
    db.close()
    return {"cluster_id": cluster_id, "issue_id": issue["id"], "image": image_payload(stored), "c2pa": c2pa_result, "ai_detector": detector_result, "final_authenticity_state": final_state, "review_status": review_status, "status": "in_progress"}


@app.get("/api/admin/metrics")
def admin_metrics(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    db = connect()
    total = db.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"]
    resolved = db.execute("SELECT COUNT(*) AS n FROM issues WHERE status='resolved'").fetchone()["n"]
    pending = db.execute("SELECT COUNT(*) AS n FROM issues WHERE status IN ('reported','in_progress')").fetchone()["n"]
    reopened = db.execute("SELECT COUNT(*) AS n FROM issues WHERE status='reopened'").fetchone()["n"]
    open_count = db.execute("SELECT COUNT(*) AS n FROM issues WHERE status IN ('reported','in_progress','reopened')").fetchone()["n"]
    clustered_reports = db.execute("SELECT COALESCE(SUM(CASE WHEN report_count > 1 THEN report_count - 1 ELSE 0 END),0) AS n FROM (SELECT cluster_id, COUNT(*) AS report_count FROM issues GROUP BY cluster_id)").fetchone()["n"]
    recurring = db.execute("SELECT COUNT(*) AS n FROM clusters WHERE recurrence_count > 0").fetchone()["n"]
    avg_resolution = db.execute("SELECT AVG((julianday(resolved_at)-julianday(created_at))*24.0) AS h FROM issues WHERE resolved_at IS NOT NULL").fetchone()["h"] or 0
    db.close()
    fixed_pct = round(resolved / total * 100) if total else 0
    return {"outcomes": {"fixed": fixed_pct, "pending": round(pending / total * 100) if total else 0, "reopened": round(reopened / total * 100) if total else 0}, "total_issues": total, "resolved_issues": resolved, "open_issues": open_count, "overdue_count": max(0, open_count - 1), "recurrence_rate": round(recurring / max(1, total) * 100, 1), "avg_resolution_hours": round(avg_resolution, 1), "clustered_reports": int(clustered_reports), "recurring_clusters": int(recurring)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


app.mount("/", StaticFiles(directory=ROOT, html=True), name="frontend")
