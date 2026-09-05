from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import asyncio
import json
import cv2
import base64
from typing import Dict, Optional, List
import threading
import time
import os
import psutil

# Import CV Engine & Database (Gunakan relative import titik agar terbaca dalam folder BE)
from .main import FallDetectionEngine
from .database import (
    get_all_settings,
    update_setting,
    get_all_pushover_devices,
    replace_all_pushover_devices,
    verify_user,
)

app = FastAPI(
    title="Fall Detection System API",
    description="Computer Vision-based Fall Detection with FastAPI",
    version="1.0.0"
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

# Proses saat ini, dipakai untuk baca penggunaan RAM/CPU proses Python
# (bukan CPU/RAM seluruh mesin, tapi punya server FastAPI+CV Engine ini saja)
_process = psutil.Process(os.getpid())
# Panggilan pertama cpu_percent() selalu 0.0, jadi "dipanaskan" sekali di sini
_process.cpu_percent(interval=None)

# Dicatat saat modul ini di-load (mendekati saat server mulai jalan),
# dipakai untuk hitung uptime_sec di /ws/performance
_server_start_time = time.time()

# Batas jumlah perangkat Pushover, sama seperti batas yang sudah
# ditegakkan di sisi UI settings.html (MAX_DEVICES = 5 di JS-nya).
MAX_PUSHOVER_DEVICES = 5

# ==================== SKEMA REQUEST ====================

class PushoverDeviceIn(BaseModel):
    """Satu baris device dari form settings.html."""
    name: str = Field(min_length=1)
    key: str = Field(min_length=1)

class PushoverSettingsIn(BaseModel):
    pushover_devices: List[PushoverDeviceIn]

class LoginIn(BaseModel):
    """Payload dari login.html: { username, password }"""
    username: str
    password: str

# ==================== ROUTES ====================

@app.on_event("startup")
async def startup_event():
    """
    PENTING: CV engine TIDAK auto-start di sini lagi.
    Kamera fisik hanya dinyalakan saat user menekan tombol "Nyalakan kamera"
    di Web UI, yang memanggil POST /api/start.
    """
    saved_status = get_all_settings().get("cameraStatus", "off")
    print(f"✓ Server siap. Status kamera tersimpan: {saved_status} (tidak auto-start; tunggu perintah dari UI)")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop CV engine on server shutdown"""
    if cv_engine.is_running:
        cv_engine.stop()
    print("✓ CV Engine stopped")

# Serve Frontend
app.mount("/static", StaticFiles(directory="FE"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve main camera page"""
    with open("FE/camera.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/performance")
async def performance_page():
    """Serve performance monitoring page"""
    with open("FE/performance.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/settings")
async def settings_page():
    """Serve settings page"""
    with open("FE/settings.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/login")
async def login_page():
    """Serve halaman login"""
    with open("FE/login.html", "r") as f:
        return HTMLResponse(content=f.read())

# ==================== AUTH ====================

@app.post("/api/auth/login")
async def login(payload: LoginIn):
    """Cek username+password terhadap tabel users di SQLite."""
    if verify_user(payload.username, payload.password):
        return {"message": "Login berhasil"}
    raise HTTPException(status_code=401, detail="Username atau password salah")

# ==================== API ENDPOINTS ====================

@app.get("/api/status")
async def get_status():
    """Get current system status"""
    return {
        "status": "running" if cv_engine.is_running else "stopped",
        "active_tracks": len(cv_engine.tracking_states),
        "fps": cv_engine.current_fps,
        "alerts": cv_engine.alert_count
    }

@app.post("/api/start")
async def start_detection():
    """Nyalakan kamera fisik + CV engine."""
    if not cv_engine.is_running:
        cv_engine.start()
        for _ in range(20):  # maksimal ~2 detik menunggu
            if cv_engine.is_running:
                break
            await asyncio.sleep(0.1)

        update_setting('cameraStatus', 'on')

        if not cv_engine.is_running:
            raise HTTPException(
                status_code=500,
                detail="Kamera gagal dibuka. Periksa index kamera di main.py atau pastikan tidak dipakai aplikasi lain."
            )
        return {"message": "Detection started", "status": "running"}
    return {"message": "Already running", "status": "running"}

@app.post("/api/stop")
async def stop_detection():
    """Stop fall detection"""
    if cv_engine.is_running:
        cv_engine.stop()
        update_setting('cameraStatus', 'off')
        return {"message": "Detection stopped", "status": "stopped"}
    return {"message": "Already stopped", "status": "stopped"}

@app.get("/api/settings")
async def get_settings():
    """Get current configuration langsung dari Database SQLite"""
    return get_all_settings()

@app.put("/api/settings")
async def update_settings(settings: dict):
    """Update configuration dan simpan ke Database"""
    for key, value in settings.items():
        update_setting(key, value)

        if key == "fall_threshold":
            cv_engine.fall_time_threshold = float(value)

        elif key == "cameraStatus":
            if value == "on" and not cv_engine.is_running:
                cv_engine.start()
            elif value == "off" and cv_engine.is_running:
                cv_engine.stop()

    return {"message": "Settings updated", "settings": settings}

@app.delete("/api/tracking/{track_id}")
async def reset_tracking(track_id: int):
    """Reset specific tracking state"""
    if track_id in cv_engine.tracking_states:
        del cv_engine.tracking_states[track_id]
        return {"message": f"Track {track_id} reset"}
    raise HTTPException(status_code=404, detail="Track ID not found")

# ==================== PUSHOVER DEVICE SETTINGS ====================

@app.get("/api/settings/pushover")
async def get_pushover_settings():
    """
    Kembalikan semua perangkat Pushover tersimpan, dengan bentuk yang
    langsung cocok dipakai settings.html (field 'key', bukan 'api_key').
    """
    devices = get_all_pushover_devices()
    return {
        "pushover_devices": [
            {"name": d["name"], "key": d["api_key"]} for d in devices
        ]
    }

@app.post("/api/settings/pushover")
async def update_pushover_settings(payload: PushoverSettingsIn):
    """
    Ganti seluruh daftar perangkat Pushover sekaligus.
    Validasi batas 5 perangkat dilakukan di sini juga (bukan hanya di JS).
    """
    if len(payload.pushover_devices) > MAX_PUSHOVER_DEVICES:
        raise HTTPException(
            status_code=400,
            detail=f"Maksimal {MAX_PUSHOVER_DEVICES} perangkat Pushover diperbolehkan."
        )

    devices_for_db = [
        {"name": d.name.strip(), "api_key": d.key.strip()}
        for d in payload.pushover_devices
    ]

    replace_all_pushover_devices(devices_for_db)

    return {
        "message": "Pengaturan Pushover disimpan",
        "count": len(devices_for_db),
    }

# ==================== WEBSOCKET STREAMING ====================

@app.websocket("/ws/video")
async def video_stream(websocket: WebSocket):
    """
    camera.html menunggu pesan berformat:
        {"type": "frame", "data": "<base64 jpeg>"}
    dari alamat ws://<host>/ws/video.
    """
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
            else:
                pass

            await asyncio.sleep(1 / 15)

    except WebSocketDisconnect:
        print(f"Video client {client_id} disconnected")
    finally:
        if client_id in active_websockets:
            del active_websockets[client_id]

@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    """WebSocket endpoint for fall detection events"""
    await websocket.accept()
    client_id = id(websocket)

    try:
        last_alert_count = cv_engine.alert_count

        while True:
            if cv_engine.alert_count > last_alert_count:
                await websocket.send_json({
                    "type": "alert",
                    "message": "Fall detected!",
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

@app.websocket("/ws/detect")
async def detect_stream(websocket: WebSocket):
    """
    WebSocket khusus untuk mengirim KOORDINAT bounding box saja (tanpa gambar).
    Saat ini alur utama TIDAK memakai endpoint ini — camera.html memakai /ws/video.
    """
    await websocket.accept()
    client_id = id(websocket)
    active_websockets[client_id] = websocket

    try:
        while True:
            boxes_data = []  # TODO: isi dari cv_engine.current_boxes jika sudah diimplementasikan
            await websocket.send_json(boxes_data)
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print(f"Detect client {client_id} disconnected")
    finally:
        if client_id in active_websockets:
            del active_websockets[client_id]


@app.websocket("/ws/performance")
async def performance_stream(websocket: WebSocket):
    """
    Mengirim data ASLI tiap 1 detik sesuai skema yang diharapkan
    performance.html:
        {
          "cpu": <float, persen CPU proses server ini>,
          "ram_mb": <float, RAM proses server ini dalam MB>,
          "latency_ms": <float, waktu inferensi YOLO frame terakhir>,
          "uptime_sec": <float, lama server ini sudah menyala>
        }
    """
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
    """Health check endpoint"""
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