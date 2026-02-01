from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import shutil
import subprocess
import os
import zipfile
import datetime
import psutil
import secrets
import sqlite3

# =============================
# 設定
# =============================
MC_DATA_DIR = "/mc-data"
BACKUP_DIR = "/backups"
LOG_FILE = os.path.join(MC_DATA_DIR, "logs", "latest.log")

ROOT_API_KEY = os.getenv("ROOT_API_KEY", "dev-root-key")

DB_DIR = "/data"
DB_PATH = os.path.join(DB_DIR, "api.db")

os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)

# =============================
# DB
# =============================
def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            created TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            api_key TEXT,
            role TEXT,
            action TEXT,
            detail TEXT,
            ip TEXT
        )
        """)

# =============================
# FastAPI
# =============================
app = FastAPI(
    title="Minecraft Server Control API",
    description="Minecraft サーバー管理用 Web API",
    version="3.0.0"
)

@app.on_event("startup")
def startup():
    init_db()

# =============================
# CORS
# =============================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================
# Auth
# =============================
def verify_root(x_api_key: str = Header(...)):
    if x_api_key != ROOT_API_KEY:
        raise HTTPException(status_code=403, detail="Root API Key required")

def verify_api_key(
    request: Request,
    x_api_key: str = Header(...)
):
    if x_api_key == ROOT_API_KEY:
        return {
            "api_key": "ROOT",
            "role": "root",
            "ip": request.client.host
        }

    with get_db() as conn:
        cur = conn.execute(
            "SELECT role FROM api_keys WHERE key = ?",
            (x_api_key,)
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    return {
        "api_key": x_api_key,
        "role": row[0],
        "ip": request.client.host
    }

# =============================
# Audit Log
# =============================
def log_action(user, action, detail=""):
    with get_db() as conn:
        conn.execute("""
        INSERT INTO audit_logs (time, api_key, role, action, detail, ip)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.datetime.now().isoformat(),
            user["api_key"],
            user["role"],
            action,
            detail,
            user["ip"]
        ))

@app.get("/audit/logs", tags=["Audit"])
def get_audit_logs(_: None = Depends(verify_root)):
    with get_db() as conn:
        cur = conn.execute("""
        SELECT time, api_key, role, action, detail, ip
        FROM audit_logs
        ORDER BY id DESC
        LIMIT 100
        """)
        return [
            dict(time=t, api_key=k, role=r, action=a, detail=d, ip=i)
            for t, k, r, a, d, i in cur.fetchall()
        ]

# =============================
# API Key 管理
# =============================
@app.post("/auth/keys", tags=["Auth"])
def create_api_key(role: str = "admin", _: None = Depends(verify_root)):
    key = secrets.token_hex(32)
    created = datetime.datetime.now().isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO api_keys VALUES (?, ?, ?)",
            (key, role, created)
        )

    return {"api_key": key, "role": role}

@app.get("/auth/keys", tags=["Auth"])
def list_api_keys(_: None = Depends(verify_root)):
    with get_db() as conn:
        cur = conn.execute("SELECT key, role, created FROM api_keys")
        return [
            {"api_key": k, "role": r, "created": c}
            for k, r, c in cur.fetchall()
        ]

@app.delete("/auth/keys/{key}", tags=["Auth"])
def delete_api_key(key: str, _: None = Depends(verify_root)):
    with get_db() as conn:
        conn.execute("DELETE FROM api_keys WHERE key = ?", (key,))
    return {"deleted": key}

# =============================
# Upload
# =============================
@app.post("/upload", tags=["File"])
async def upload(
    file: UploadFile = File(...),
    user=Depends(verify_api_key)
):
    path = os.path.join(MC_DATA_DIR, file.filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if file.filename.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zip_ref:
            zip_ref.extractall(MC_DATA_DIR)
        os.remove(path)

    subprocess.run(["docker", "restart", "mc-server"])
    log_action(user, "upload", file.filename)

    return {"status": "uploaded"}

# =============================
# Server Control
# =============================
@app.post("/start", tags=["Server"])
def start(user=Depends(verify_api_key)):
    subprocess.run(["docker", "start", "mc-server"])
    log_action(user, "start")
    return {"status": "started"}

@app.post("/stop", tags=["Server"])
def stop(user=Depends(verify_api_key)):
    subprocess.run(["docker", "stop", "mc-server"])
    log_action(user, "stop")
    return {"status": "stopped"}

@app.get("/status", tags=["Server"])
def status(user=Depends(verify_api_key)):
    result = subprocess.run(
        ["docker", "ps", "-f", "name=mc-server", "--format", "{{.Status}}"],
        capture_output=True, text=True
    )
    log_action(user, "status")
    return {"status": result.stdout.strip() or "stopped"}

# =============================
# Backup
# =============================
@app.post("/backup", tags=["Backup"])
def backup(user=Depends(verify_api_key)):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"mc_backup_{ts}.zip")

    with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(MC_DATA_DIR):
            for f in files:
                full = os.path.join(root, f)
                zipf.write(full, os.path.relpath(full, MC_DATA_DIR))

    log_action(user, "backup", backup_file)
    return {"backup": backup_file}

# =============================
# Logs
# =============================
@app.get("/logs", tags=["Log"])
def logs(user=Depends(verify_api_key)):
    if not os.path.exists(LOG_FILE):
        return {"logs": ""}
    log_action(user, "logs")
    with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
        return {"logs": f.read()}

# =============================
# Console
# =============================
class ExecHistory(BaseModel):
    time: str
    command: str
    output: str

EXEC_HISTORY: list[ExecHistory] = []

@app.post("/exec", tags=["Console"])
def exec_cmd(
    command: str = Form(...),
    user=Depends(verify_api_key)
):
    result = subprocess.run(
        ["docker", "exec", "mc-server", "rcon-cli", command],
        capture_output=True, text=True
    )
    output = result.stdout.strip() or result.stderr.strip()

    entry = ExecHistory(
        time=datetime.datetime.now().isoformat(),
        command=command,
        output=output
    )

    EXEC_HISTORY.append(entry)
    EXEC_HISTORY[:] = EXEC_HISTORY[-100:]

    log_action(user, "exec", command)
    return entry

@app.get("/exec/history", tags=["Console"])
def exec_history(user=Depends(verify_api_key)):
    return EXEC_HISTORY

# =============================
# Metrics
# =============================
@app.get("/metrics", tags=["Metrics"])
def metrics(user=Depends(verify_api_key)):
    mem = psutil.virtual_memory()
    log_action(user, "metrics")
    return {
        "memory": {
            "total_gb": round(mem.total / 1024**3, 2),
            "used_gb": round(mem.used / 1024**3, 2),
            "percent": mem.percent
        }
    }
