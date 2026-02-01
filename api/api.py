from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import shutil
import subprocess
import os
import zipfile
import datetime
import psutil
import secrets

# =============================
# 設定
# =============================
MC_DATA_DIR = "/mc-data"
BACKUP_DIR = "/backups"
LOG_FILE = os.path.join(MC_DATA_DIR, "logs", "latest.log")

ROOT_API_KEY = os.getenv("ROOT_API_KEY", "dev-root-key")

os.makedirs(BACKUP_DIR, exist_ok=True)

# =============================
# FastAPI
# =============================
app = FastAPI(
    title="Minecraft Server Control API",
    description="Minecraft サーバー管理用 Web API",
    version="2.1.0"
)

# =============================
# CORS（Webフロント用）
# =============================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================
# API Key 管理（メモリ）
# =============================
API_KEYS: dict[str, dict] = {}

def verify_root(x_api_key: str = Header(...)):
    if x_api_key != ROOT_API_KEY:
        raise HTTPException(status_code=403, detail="Root API Key required")

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key == ROOT_API_KEY:
        return
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API Key")

# =============================
# exec 履歴
# =============================
class ExecHistory(BaseModel):
    time: str
    command: str
    output: str

EXEC_HISTORY: list[ExecHistory] = []

# =============================
# API Key 発行・管理
# =============================
@app.post("/auth/keys", tags=["Auth"], summary="API Key 発行（root専用）")
def create_api_key(role: str = "admin", _: None = Depends(verify_root)):
    key = secrets.token_hex(32)
    API_KEYS[key] = {
        "role": role,
        "created": datetime.datetime.now().isoformat()
    }
    return {"api_key": key, "role": role}

@app.get("/auth/keys", tags=["Auth"], summary="API Key 一覧（root専用）")
def list_api_keys(_: None = Depends(verify_root)):
    return API_KEYS

@app.delete("/auth/keys/{key}", tags=["Auth"], summary="API Key 削除（root専用）")
def delete_api_key(key: str, _: None = Depends(verify_root)):
    API_KEYS.pop(key, None)
    return {"deleted": key}

# =============================
# ファイルアップロード
# =============================
@app.post("/upload", tags=["File"], summary="ファイル / フォルダアップロード",
          dependencies=[Depends(verify_api_key)])
async def upload(file: UploadFile = File(...)):
    path = os.path.join(MC_DATA_DIR, file.filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if file.filename.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zip_ref:
            zip_ref.extractall(MC_DATA_DIR)
        os.remove(path)

    subprocess.run(["docker", "restart", "mc-server"])
    return {"status": "uploaded", "filename": file.filename}

# =============================
# サーバー制御
# =============================
@app.post("/start", tags=["Server"], dependencies=[Depends(verify_api_key)])
def start():
    subprocess.run(["docker", "start", "mc-server"])
    return {"status": "started"}

@app.post("/stop", tags=["Server"], dependencies=[Depends(verify_api_key)])
def stop():
    subprocess.run(["docker", "stop", "mc-server"])
    return {"status": "stopped"}

@app.get("/status", tags=["Server"], dependencies=[Depends(verify_api_key)])
def status():
    result = subprocess.run(
        ["docker", "ps", "-f", "name=mc-server", "--format", "{{.Status}}"],
        capture_output=True, text=True
    )
    return {"status": result.stdout.strip() or "stopped"}

# =============================
# バックアップ
# =============================
@app.post("/backup", tags=["Backup"], dependencies=[Depends(verify_api_key)])
def backup():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"mc_backup_{ts}.zip")

    with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(MC_DATA_DIR):
            for f in files:
                full = os.path.join(root, f)
                zipf.write(full, os.path.relpath(full, MC_DATA_DIR))

    return {"backup": backup_file}

# =============================
# ログ
# =============================
@app.get("/logs", tags=["Log"], dependencies=[Depends(verify_api_key)])
def logs():
    if not os.path.exists(LOG_FILE):
        return {"logs": ""}
    with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
        return {"logs": f.read()}

# =============================
# コンソール実行
# =============================
@app.post("/exec", tags=["Console"], dependencies=[Depends(verify_api_key)])
def exec_cmd(command: str = Form(...)):
    try:
        result = subprocess.run(
            ["docker", "exec", "mc-server", "rcon-cli", command],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        output = str(e)

    entry = ExecHistory(
        time=datetime.datetime.now().isoformat(),
        command=command,
        output=output
    )
    EXEC_HISTORY.append(entry)

    return entry

@app.get("/exec/history", tags=["Console"],
         response_model=list[ExecHistory],
         dependencies=[Depends(verify_api_key)])
def exec_history():
    return EXEC_HISTORY[-50:]

# =============================
# サーバー情報
# =============================
@app.get("/metrics", tags=["Metrics"], dependencies=[Depends(verify_api_key)])
def metrics():
    mem = psutil.virtual_memory()
    return {
        "memory": {
            "total_gb": round(mem.total / 1024**3, 2),
            "used_gb": round(mem.used / 1024**3, 2),
            "percent": mem.percent
        },
        "note": "TPS は exec で /tps を実行してください"
    }
