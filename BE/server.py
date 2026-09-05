from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import asyncio
import cv2
import base64
from typing import Dict, Optional, List
import threading
import time
import os
import psutil

# Import CV Engine & Database
from .main import FallDetectionEngine
from .database import (
    get_all_settings,
    update_setting,
    get_setting,
    verify_user,
)

app = FastAPI(
    title="FallCare Sentinel API",
    description="Multi-Device Direct Emergency Alerting System",
    version="2.1.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cv_engine = FallDetectionEngine()
cv_thread: Optional[threading.Thread] = None

# Tracking Active WebSockets
active_video_websockets: Dict[int, WebSocket] = {}

# POOL MULTI-DEVICE ANDROID:
# Menyimpan data: { client_id: {"ws": WebSocket, "ip": str, "name": str, "connected_at": str} }
connected_emergency_devices: Dict[int, dict] = {}

# Resource Monitoring
_process = psutil.Process(os.getpid())
_process.cpu_percent(interval=None)
_server_start_time = time.time()

# ==================== SKEMA REQUEST ====================

class LoginIn(BaseModel):
    username: str
    password: str

class SettingsUpdateIn(BaseModel):
    cameraStatus: Optional[str] = None
    notifMode: Optional[str] = None
    fall_threshold: Optional[float] = None
    alarm_duration: Optional[int] = Field(None, ge=20, le=900)
    ringtone_type: Optional[str] = None
    max_devices: Optional[int] = Field(None, ge=1, le=20)

# ==================== LIFECYCLE ====================

@app.on_event("startup")
async def startup_event():
    if not get_setting("alarm_duration"):
        update_setting("alarm_duration", 30)
    if not get_setting("ringtone_type"):
        update_setting("ringtone_type", "alarm")
    if not get_setting("notifMode"):
        update_setting("notifMode", "keduanya")
    if not get_setting("max_devices"):
        update_setting("max_devices", 5)

    saved_status = get_all_settings().get("cameraStatus", "off")
    print(f"✓ Server Siaga Multi-Device. Status Kamera: {saved_status}")

@app.on_event("shutdown")
async def shutdown_event():
    if cv_engine.is_running:
        cv_engine.stop()
    print("✓ CV Engine stopped")

# ==================== SERVE FRONTEND ====================

app.mount("/static", StaticFiles(directory="FE"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("FE/camera.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/performance")
async def performance_page():
    with open("FE/performance.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/settings")
async def settings_page():
    with open("FE/settings.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/login")
async def login_page():
    with open("FE/login.html", "r") as f:
        return HTMLResponse(content=f.read())

# ==================== AUTH ====================

@app.post("/api/auth/login")
async def login(payload: LoginIn):
    if verify_user(payload.username, payload.password):
        return {"message": "Login berhasil"}
    raise HTTPException(status_code=401, detail="Username atau password salah")

# ==================== API ENDPOINTS ====================

@app.get("/api/status")
async def get_status():
    return {
        "status": "running" if cv_engine.is_running else "stopped",
        "active_tracks": len(cv_engine.tracking_states),
        "fps": cv_engine.current_fps,
        "alerts": cv_engine.alert_count,
        "connected_devices": len(connected_emergency_devices)
    }

@app.get("/api/devices")
async def get_connected_devices():
    """Mengembalikan daftar HP darurat yang saat ini terhubung dan siaga."""
    device_list = []
    for cid, info in connected_emergency_devices.items():
        device_list.append({
            "id": cid,
            "ip": info["ip"],
            "name": info["name"],
            "connected_at": info["connected_at"]
        })
    max_dev = int(get_setting("max_devices", 5))
    return {"devices": device_list, "total": len(device_list), "max_allowed": max_dev}

@app.post("/api/start")
async def start_detection():
    if not cv_engine.is_running:
        cv_engine.start()
        for _ in range(20):
            if cv_engine.is_running:
                break
            await asyncio.sleep(0.1)

        update_setting('cameraStatus', 'on')
        if not cv_engine.is_running:
            raise HTTPException(status_code=500, detail="Kamera gagal dibuka.")
        return {"message": "Detection started", "status": "running"}
    return {"message": "Already running", "status": "running"}

@app.post("/api/stop")
async def stop_detection():
    if cv_engine.is_running:
        cv_engine.stop()
        update_setting('cameraStatus', 'off')
        return {"message": "Detection stopped", "status": "stopped"}
    return {"message": "Already stopped", "status": "stopped"}

@app.get("/api/settings")
async def get_settings():
    return get_all_settings()

@app.put("/api/settings")
async def update_settings(payload: SettingsUpdateIn):
    data = payload.dict(exclude_unset=True)
    for key, value in data.items():
        update_setting(key, value)
        if key == "fall_threshold":
            cv_engine.fall_time_threshold = float(value)
        elif key == "cameraStatus":
            if value == "on" and not cv_engine.is_running:
                cv_engine.start()
            elif value == "off" and cv_engine.is_running:
                cv_engine.stop()

    return {"message": "Settings updated", "settings": get_all_settings()}

# ==================== WEBSOCKET STREAMING ====================

@app.websocket("/ws/video")
async def video_stream(websocket: WebSocket):
    await websocket.accept()
    client_id = id(websocket)
    active_video_websockets[client_id] = websocket

    try:
        while True:
            if cv_engine.current_frame is not None:
                success, buffer = cv2.imencode(".jpg", cv_engine.current_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if success:
                    jpg_as_text = base64.b64encode(buffer).decode("utf-8")
                    await websocket.send_json({"type": "frame", "data": jpg_as_text})
            await asyncio.sleep(1 / 15)
    except WebSocketDisconnect:
        pass
    finally:
        if client_id in active_video_websockets:
            del active_video_websockets[client_id]

@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    """Menerima koneksi dari banyak HP Android sekaligus & broadcast serentak."""
    await websocket.accept()
    client_id = id(websocket)
    client_ip = websocket.client.host if websocket.client else "Unknown"

    # Periksa batas maksimal device
    max_allowed = int(get_setting("max_devices", 5))
    if len(connected_emergency_devices) >= max_allowed:
        await websocket.close(code=1008, reason="Kuota perangkat darurat penuh.")
        return

    # Registrasi device darurat ke pool
    connected_emergency_devices[client_id] = {
        "ws": websocket,
        "ip": client_ip,
        "name": f"Device-{client_ip.split('.')[-1]}", # Default penamaan otomatis
        "connected_at": time.strftime("%H:%M:%S")
    }
    print(f"[+] Device Darurat Baru Terhubung: {client_ip} (Total Siaga: {len(connected_emergency_devices)})")

    try:
        last_alert_count = cv_engine.alert_count

        while True:
            # 1. Mendeteksi handshake / update nama dari Android
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                data = json.loads(msg)
                if data.get("type") == "register_name":
                    connected_emergency_devices[client_id]["name"] = data.get("name", "Unknown")
            except asyncio.TimeoutError:
                pass

            # 2. Trigger Jatuh Terdeteksi -> Broadcast ke SELURUH device secara paralel
            if cv_engine.alert_count > last_alert_count:
                current_mode = get_setting("notifMode", "keduanya")
                raw_duration = int(get_setting("alarm_duration", 30))
                duration_sec = max(20, min(900, raw_duration))
                ringtone_type = get_setting("ringtone_type", "alarm")

                alert_payload = {
                    "type": "alert",
                    "message": "Fall detected!",
                    "mode": current_mode,
                    "duration": duration_sec,
                    "ringtone": ringtone_type,
                    "timestamp": time.time(),
                    "tracking_data": cv_engine.tracking_states
                }

                # Kirim serentak ke semua HP tanpa menunggu antrian
                tasks = [dev["ws"].send_json(alert_payload) for dev in connected_emergency_devices.values()]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                last_alert_count = cv_engine.alert_count

            # 3. Heartbeat keeping
            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": time.time(),
                "connected_devices": len(connected_emergency_devices)
            })
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
    finally:
        if client_id in connected_emergency_devices:
            del connected_emergency_devices[client_id]
            print(f"[-] Device Darurat Terputus: {client_ip} (Sisa: {len(connected_emergency_devices)})")

@app.websocket("/ws/performance")
async def performance_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            cpu_percent = _process.cpu_percent(interval=None)
            ram_mb = _process.memory_info().rss / (1024 * 1024)
            latency_ms = float(getattr(cv_engine, "last_inference_ms", 0.0) or 0.0)
            uptime_sec = time.time() - _server_start_time

            await websocket.send_json({
                "cpu": cpu_percent,
                "ram_mb": ram_mb,
                "latency_ms": latency_ms,
                "uptime_sec": uptime_sec,
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
