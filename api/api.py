from fastapi import FastAPI, UploadFile, File
import shutil, subprocess, os
import zipfile

app = FastAPI()
MC_DATA_DIR = "/mc-data"

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
    
    subprocess.run(["docker", "restart", "mc-server"])
    return {"status": "uploaded and server restarted", "file": filename}

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
