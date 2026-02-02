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
            player_name TEXT,
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
    version="4.0.0"
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
def verify_root(
    request: Request,
    x_api_key: str = Header(...)
):
    if x_api_key != ROOT_API_KEY:
        raise HTTPException(status_code=403, detail="Root API Key required")

    return {
        "api_key": "ROOT",
        "role": "root",
        "player_name": None,
        "ip": request.client.host
    }

def verify_api_key(
    request: Request,
    x_api_key: str = Header(...)
):
    if x_api_key == ROOT_API_KEY:
        return {
            "api_key": "ROOT",
            "role": "root",
            "player_name": None,
            "ip": request.client.host
        }

    with get_db() as conn:
        cur = conn.execute(
            "SELECT role, player_name FROM api_keys WHERE key = ?",
            (x_api_key,)
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    return {
        "api_key": x_api_key,
        "role": row[0],
        "player_name": row[1],
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
def get_audit_logs(user=Depends(verify_root)):
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
# API Key 管理（プレイヤー名対応）
# =============================
class CreateKeyRequest(BaseModel):
    player_name: str
    role: str = "player"

@app.post("/auth/keys", tags=["Auth"])
def create_api_key(req: CreateKeyRequest, user=Depends(verify_root)):
    """
    プレイヤー名に紐付いたAPIキーを発行
    """
    key = secrets.token_hex(32)
    created = datetime.datetime.now().isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO api_keys VALUES (?, ?, ?, ?)",
            (key, req.role, req.player_name, created)
        )

    log_action(user, "create_api_key", f"player={req.player_name}, role={req.role}")
    return {"api_key": key, "role": req.role, "player_name": req.player_name}

@app.get("/auth/keys", tags=["Auth"])
def list_api_keys(user=Depends(verify_root)):
    with get_db() as conn:
        cur = conn.execute("SELECT key, role, player_name, created FROM api_keys")
        return [
            {"api_key": k, "role": r, "player_name": p, "created": c}
            for k, r, p, c in cur.fetchall()
        ]

@app.get("/auth/keys/my", tags=["Auth"])
def get_my_key_info(user=Depends(verify_api_key)):
    """
    自分のAPIキー情報を取得
    """
    return {
        "api_key": user["api_key"],
        "role": user["role"],
        "player_name": user["player_name"]
    }

@app.delete("/auth/keys/{key}", tags=["Auth"])
def delete_api_key(key: str, user=Depends(verify_root)):
    with get_db() as conn:
        conn.execute("DELETE FROM api_keys WHERE key = ?", (key,))
    log_action(user, "delete_api_key", key)
    return {"deleted": key}

# =============================
# Whitelist 管理
# =============================
def rcon(cmd: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "mc-server", "rcon-cli", cmd],
        capture_output=True,
        text=True
    )
    return (result.stdout or result.stderr).strip()

@app.post("/whitelist/add/{player}", tags=["Whitelist"])
def whitelist_add(player: str, user=Depends(verify_api_key)):
    """
    ホワイトリストにプレイヤーを追加
    """
    output = rcon(f"whitelist add {player}")
    log_action(user, "whitelist_add", player)
    return {"player": player, "output": output}

@app.post("/whitelist/remove/{player}", tags=["Whitelist"])
def whitelist_remove(player: str, user=Depends(verify_api_key)):
    """
    ホワイトリストからプレイヤーを削除
    """
    output = rcon(f"whitelist remove {player}")
    log_action(user, "whitelist_remove", player)
    return {"player": player, "output": output}

@app.get("/whitelist", tags=["Whitelist"])
def whitelist_list(user=Depends(verify_api_key)):
    """
    ホワイトリストを表示
    """
    output = rcon("whitelist list")
    log_action(user, "whitelist_list")
    
    # 出力例: "There are 3 whitelisted players: Steve, Alex, Notch"
    if ":" in output:
        players_str = output.split(":", 1)[1].strip()
        players = [p.strip() for p in players_str.split(",")] if players_str else []
    else:
        players = []
    
    return {"players": players, "raw_output": output}

@app.post("/whitelist/enable", tags=["Whitelist"])
def whitelist_enable(user=Depends(verify_api_key)):
    """
    ホワイトリストを有効化
    """
    output = rcon("whitelist on")
    log_action(user, "whitelist_enable")
    return {"output": output}

@app.post("/whitelist/disable", tags=["Whitelist"])
def whitelist_disable(user=Depends(verify_api_key)):
    """
    ホワイトリストを無効化
    """
    output = rcon("whitelist off")
    log_action(user, "whitelist_disable")
    return {"output": output}

# =============================
# Operator 管理
# =============================
@app.post("/op/add/{player}", tags=["Operator"])
def op_add(player: str, user=Depends(verify_api_key)):
    """
    プレイヤーにOP権限を付与
    """
    # OP権限の付与は管理者のみ許可
    if user["role"] not in ["root", "admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    output = rcon(f"op {player}")
    log_action(user, "op_add", player)
    return {"player": player, "output": output}

@app.post("/op/remove/{player}", tags=["Operator"])
def op_remove(player: str, user=Depends(verify_api_key)):
    """
    プレイヤーからOP権限を削除
    """
    if user["role"] not in ["root", "admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    output = rcon(f"deop {player}")
    log_action(user, "op_remove", player)
    return {"player": player, "output": output}

# =============================
# Plugin 管理（PAPER/SPIGOT用）
# =============================
PLUGINS_DIR = os.path.join(MC_DATA_DIR, "plugins")

@app.get("/plugins", tags=["Plugins"])
def list_plugins(user=Depends(verify_api_key)):
    """
    インストール済みプラグイン一覧
    """
    if not os.path.exists(PLUGINS_DIR):
        return {"plugins": [], "message": "plugins directory not found"}
    
    plugins = []
    for filename in os.listdir(PLUGINS_DIR):
        if filename.endswith(".jar"):
            filepath = os.path.join(PLUGINS_DIR, filename)
            size_mb = round(os.path.getsize(filepath) / (1024*1024), 2)
            plugins.append({
                "name": filename,
                "size_mb": size_mb
            })
    
    log_action(user, "list_plugins")
    return {"plugins": plugins, "count": len(plugins)}

@app.post("/plugins/upload", tags=["Plugins"])
async def upload_plugin(
    file: UploadFile = File(...),
    user=Depends(verify_api_key)
):
    """
    プラグインファイル(.jar)をアップロード
    """
    if user["role"] not in ["root", "admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    if not file.filename.endswith(".jar"):
        raise HTTPException(status_code=400, detail="Only .jar files allowed")
    
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    
    filepath = os.path.join(PLUGINS_DIR, file.filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    log_action(user, "upload_plugin", file.filename)
    return {"status": "uploaded", "plugin": file.filename, "note": "Server restart required"}

@app.delete("/plugins/{filename}", tags=["Plugins"])
def delete_plugin(filename: str, user=Depends(verify_api_key)):
    """
    プラグインを削除
    """
    if user["role"] not in ["root", "admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    filepath = os.path.join(PLUGINS_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    if not filename.endswith(".jar"):
        raise HTTPException(status_code=400, detail="Invalid file")
    
    os.remove(filepath)
    log_action(user, "delete_plugin", filename)
    
    return {"status": "deleted", "plugin": filename, "note": "Server restart required"}

@app.post("/plugins/reload", tags=["Plugins"])
def reload_plugins(user=Depends(verify_api_key)):
    """
    プラグインをリロード（Bukkit/Spigot/Paper）
    """
    if user["role"] not in ["root", "admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    # plugmanがインストールされていれば使用
    output = rcon("plugman reload all")
    
    # なければBukkitの標準コマンド（あまり推奨されないが）
    if "Unknown command" in output or "plugman" not in output.lower():
        output = rcon("reload confirm")
    
    log_action(user, "reload_plugins")
    return {"output": output}

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

# =============================
# Players
# =============================
@app.get("/players", tags=["Players"])
def list_players(user=Depends(verify_api_key)):
    """
    オンラインプレイヤー一覧
    """
    output = rcon("list")

    # 例: There are 2 of a max of 20 players online: Steve, Alex
    if ":" not in output:
        return {"players": []}

    players = output.split(":", 1)[1].strip()
    player_list = [p.strip() for p in players.split(",")] if players else []

    log_action(user, "players_list")
    return {
        "count": len(player_list),
        "players": player_list
    }


@app.get("/players/{name}", tags=["Players"])
def player_detail(name: str, user=Depends(verify_api_key)):
    """
    プレイヤー詳細情報（NBT）
    """
    raw = rcon(f"data get entity {name}")

    if "No entity was found" in raw:
        raise HTTPException(status_code=404, detail="Player not online")

    log_action(user, "player_detail", name)

    return {
        "player": name,
        "raw_nbt": raw
    }