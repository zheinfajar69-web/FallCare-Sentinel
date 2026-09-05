from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import asyncio
import cv2
import base64
from typing import Dict, Optional
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
    description="Real-time Computer Vision Fall Detection with Direct WebSocket Alert",
    version="2.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize CV Engine
cv_engine = FallDetectionEngine()
cv_thread: Optional[threading.Thread] = None

# WebSocket connections tracking
active_websockets: Dict[int, WebSocket] = {}

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
    notifMode: Optional[str] = None  # 'getar', 'dering', 'keduanya'
    fall_threshold: Optional[float] = None
    alarm_duration: Optional[int] = Field(None, ge=20, le=900)  # 20 detik s/d 15 menit (900 detik)
    ringtone_type: Optional[str] = None  # 'alarm', 'ringtone', 'notification'

# ==================== LIFECYCLE ====================

@app.on_event("startup")
async def startup_event():
    # Pastikan default setting alarm tersimpan di SQLite jika belum ada
    if not get_setting("alarm_duration"):
        update_setting("alarm_duration", 30)  # default 30 detik
    if not get_setting("ringtone_type"):
        update_setting("ringtone_type", "alarm")
    if not get_setting("notifMode"):
        update_setting("notifMode", "keduanya")

    saved_status = get_all_settings().get("cameraStatus", "off")
    print(f"✓ Server Sentinel siap. Status kamera tersimpan: {saved_status}")

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
        "alerts": cv_engine.alert_count
    }

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
            raise HTTPException(
                status_code=500,
                detail="Kamera gagal dibuka. Periksa index webcam."
            )
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

@app.delete("/api/tracking/{track_id}")
async def reset_tracking(track_id: int):
    if track_id in cv_engine.tracking_states:
        del cv_engine.tracking_states[track_id]
        return {"message": f"Track {track_id} reset"}
    raise HTTPException(status_code=404, detail="Track ID not found")

# ==================== WEBSOCKET STREAMING ====================

@app.websocket("/ws/video")
async def video_stream(websocket: WebSocket):
    await websocket.accept()
    client_id = id(websocket)
    active_websockets[client_id] = websocket

    try:
        while True:
            if cv_engine.current_frame is not None:
                success, buffer = cv2.imencode(
                    ".jpg",
                    cv_engine.current_frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 75]
                )
                if success:
                    jpg_as_text = base64.b64encode(buffer).decode("utf-8")
                    await websocket.send_json({
                        "type": "frame",
                        "data": jpg_as_text
                    })
            await asyncio.sleep(1 / 15)
    except WebSocketDisconnect:
        print(f"Video client {client_id} disconnected")
    finally:
        if client_id in active_websockets:
            del active_websockets[client_id]

@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    """Mengirim event bahaya instan beserta durasi dan pilihan ringtone ke HP"""
    await websocket.accept()
    client_id = id(websocket)

    try:
        last_alert_count = cv_engine.alert_count

        while True:
            if cv_engine.alert_count > last_alert_count:
                # Ambil konfigurasi custom alert dari SQLite
                current_mode = get_setting("notifMode", "keduanya")
                raw_duration = int(get_setting("alarm_duration", 30))
                # Validasi batas minimal 20 detik dan maksimal 900 detik (15 menit)
                duration_sec = max(20, min(900, raw_duration))
                ringtone_type = get_setting("ringtone_type", "alarm")

                await websocket.send_json({
                    "type": "alert",
                    "message": "Fall detected!",
                    "mode": current_mode,
                    "duration": duration_sec,
                    "ringtone": ringtone_type,
                    "timestamp": time.time(),
                    "tracking_data": cv_engine.tracking_states
                })
                last_alert_count = cv_engine.alert_count

            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": time.time(),
                "active_tracks": len(cv_engine.tracking_states)
            })

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print(f"Event client {client_id} disconnected")

@app.websocket("/ws/performance")
async def performance_stream(websocket: WebSocket):
    await websocket.accept()
    client_id = id(websocket)
    active_websockets[client_id] = websocket

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
        print(f"Performance client {client_id} disconnected")
    finally:
        if client_id in active_websockets:
            del active_websockets[client_id]

# ==================== HEALTH CHECK ====================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "cv_engine": "running" if cv_engine.is_running else "stopped",
        "timestamp": time.time()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
