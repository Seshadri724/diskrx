import json as _json
import os
import re
import sqlite3
import logging
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("dxcli.server")

# Maximum accepted payload size: 1 MB
MAX_PAYLOAD_BYTES = 1 * 1024 * 1024

# Host ID must be a safe identifier (UUID, alphanumeric with hyphens)
_HOST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


def get_connection():
    db_path = os.environ.get("DX_FLEET_DB", "fleet_snapshots.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hosts (
            host_id TEXT PRIMARY KEY,
            hostname TEXT,
            platform TEXT,
            risk_level TEXT,
            risk_score INTEGER,
            last_seen_at REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS partitions (
            host_id TEXT,
            device TEXT,
            mountpoint TEXT,
            fstype TEXT,
            total_bytes INTEGER,
            used_bytes INTEGER,
            free_bytes INTEGER,
            usage_percent REAL,
            PRIMARY KEY (host_id, mountpoint),
            FOREIGN KEY (host_id) REFERENCES hosts(host_id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="dxcli Fleet Receiver", lifespan=lifespan)
security = HTTPBearer()


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    expected_token = os.environ.get("DX_API_TOKEN")

    if not expected_token:
        logger.error(
            "Security configuration error: DX_API_TOKEN is not configured on the server."
        )
        raise HTTPException(
            status_code=500,
            detail="Server security configuration error: auth token is missing",
        )

    if not secrets.compare_digest(token, expected_token):
        logger.warning("Unauthorized access attempt with invalid token.")
        raise HTTPException(status_code=401, detail="Invalid token")

    return token


async def validate_snapshot_payload(request: Request) -> dict:
    """Async dependency: reads and validates the raw request body before the
    synchronous handler touches SQLite.  This runs on the event-loop thread
    (no DB access), so there is no cross-thread issue."""
    # SEC: Enforce payload size limit to prevent memory exhaustion (CWE-400)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_PAYLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Payload exceeds {MAX_PAYLOAD_BYTES} byte limit",
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"Payload exceeds {MAX_PAYLOAD_BYTES} byte limit"
        )

    try:
        snapshot = _json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    host_id = snapshot.get("host_id")
    if not host_id:
        raise HTTPException(status_code=400, detail="Missing host_id")

    # SEC: Validate host_id format to prevent log injection (CWE-117)
    if not isinstance(host_id, str) or not _HOST_ID_PATTERN.match(host_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid host_id format. Must be 1-128 alphanumeric characters, hyphens, or underscores.",
        )

    return snapshot


@app.post("/v1/snapshots", status_code=202)
def receive_snapshot(
    token: str = Depends(verify_token),
    snapshot: dict = Depends(validate_snapshot_payload),
    db: sqlite3.Connection = Depends(get_db),
):
    host_id = snapshot["host_id"]
    hostname = str(snapshot.get("hostname", "unknown"))[:256]
    platform = str(snapshot.get("platform", "unknown"))[:128]
    risk_level = str(snapshot.get("risk_level", "healthy"))[:32]
    risk_score = int(snapshot.get("risk_score", 0))
    timestamp = float(snapshot.get("timestamp", 0.0))

    # SEC: Sanitize log output -- strip newlines to prevent log injection
    safe_hostname = hostname.replace("\n", "").replace("\r", "")
    logger.info(
        "Ingesting snapshot for host=%s (id=%s, risk=%s/%d)",
        safe_hostname,
        host_id,
        risk_level,
        risk_score,
    )

    try:
        cur = db.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO hosts (host_id, hostname, platform, risk_level, risk_score, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (host_id, hostname, platform, risk_level, risk_score, timestamp),
        )

        # Clear old partitions for this host
        cur.execute("DELETE FROM partitions WHERE host_id = ?", (host_id,))

        partitions = snapshot.get("partitions", [])
        if not isinstance(partitions, list):
            partitions = []

        for part in partitions:
            if not isinstance(part, dict):
                continue
            device = str(part.get("device", ""))[:128]
            mountpoint = str(part.get("mountpoint", ""))[:256]
            fstype = str(part.get("fstype", ""))[:64]
            total_bytes = int(part.get("total_bytes", 0))
            used_bytes = int(part.get("used_bytes", 0))
            free_bytes = int(part.get("free_bytes", 0))
            usage_percent = float(part.get("usage_percent", 0.0))

            cur.execute(
                """
                INSERT OR REPLACE INTO partitions (host_id, device, mountpoint, fstype, total_bytes, used_bytes, free_bytes, usage_percent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host_id,
                    device,
                    mountpoint,
                    fstype,
                    total_bytes,
                    used_bytes,
                    free_bytes,
                    usage_percent,
                ),
            )

        db.commit()
    except Exception:
        logger.exception("Database insertion failed for host=%s", host_id)
        raise HTTPException(
            status_code=500, detail="Internal storage insertion failure"
        )

    return {"status": "accepted"}


@app.get("/v1/fleet/status")
def get_fleet_status(
    token: str = Depends(verify_token), db: sqlite3.Connection = Depends(get_db)
):
    logger.info("Fleet status query requested.")
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM hosts")
        hosts = [dict(row) for row in cur.fetchall()]

        for host in hosts:
            cur.execute(
                "SELECT * FROM partitions WHERE host_id = ?", (host["host_id"],)
            )
            host["partitions"] = [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Failed to query fleet status from database")
        raise HTTPException(
            status_code=500, detail="Internal storage retrieval failure"
        )

    return {"hosts": hosts}
