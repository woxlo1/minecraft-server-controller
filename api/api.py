from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import shutil, subprocess, os, zipfile, datetime

app = FastAPI()

MC_DATA_DIR = "/mc-data"       # マインクラフトサーバーデータディレクトリ
BACKUP_DIR = "/backups"        # バックアップ保存先
LOG_FILE = os.path.join(MC_DATA_DIR, "logs", "latest.log")

os.makedirs(BACKUP_DIR, exist_ok=True)

# -----------------------------
# 1️⃣ ファイル・フォルダアップロード
# -----------------------------
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    filepath = os.path.join(MC_DATA_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # zipなら自動展開
    if filename.endswith(".zip"):
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(MC_DATA_DIR)
        os.remove(filepath)  # zipは削除

    # サーバー再起動
    subprocess.run(["docker", "restart", "mc-server"])
    return {"status": "uploaded and server restarted", "file": filename}

# -----------------------------
# 2️⃣ サーバー制御
# -----------------------------
@app.post("/start")
def start_server():
    subprocess.run(["docker", "start", "mc-server"])
    return {"status": "started"}

@app.post("/stop")
def stop_server():
    subprocess.run(["docker", "stop", "mc-server"])
    return {"status": "stopped"}

@app.get("/status")
def status():
    result = subprocess.run(
        ["docker", "ps", "-f", "name=mc-server", "--format", "{{.Status}}"],
        capture_output=True, text=True
    )
    return {"status": result.stdout.strip() or "stopped"}

# -----------------------------
# 3️⃣ サーバー自動バックアップ
# -----------------------------
@app.post("/backup")
async def backup():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"mc_backup_{timestamp}.zip")
    
    with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(MC_DATA_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                zipf.write(filepath, os.path.relpath(filepath, MC_DATA_DIR))
    
    return {"backup_file": backup_file, "message": "Backup completed successfully"}

# -----------------------------
# 4️⃣ ログ表示
# -----------------------------
@app.get("/logs")
async def get_logs():
    if not os.path.exists(LOG_FILE):
        return JSONResponse(content={"logs": "", "message": "Log file not found"})
    
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        logs = f.read()
    return {"logs": logs}
