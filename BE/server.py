from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import cv2
import base64
from typing import Dict, Optional
import threading
import time

# Import CV Engine & Database (Gunakan relative import titik agar terbaca dalam folder BE)
from .main import FallDetectionEngine
from .database import get_all_settings, update_setting

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

# ==================== ROUTES ====================

@app.on_event("startup")
async def startup_event():
    """
    PENTING: CV engine TIDAK auto-start di sini lagi.
    Kamera fisik hanya dinyalakan saat user menekan tombol "Nyalakan kamera"
    di Web UI, yang memanggil POST /api/start.

    Ini juga yang membuat kamera "tidak mau masuk" sebelumnya: engine sempat
    auto-start di thread terpisah tanpa ada jalur pengiriman frame ke browser
    (endpoint /ws/video belum ada), jadi video tidak pernah sampai ke Web UI
    walau kamera fisik sudah menyala.
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
    """
    Nyalakan kamera fisik + CV engine.
    Ini endpoint yang sebelumnya HILANG — camera.html sudah memanggil
    fetch('/api/start', {method:'POST'}) tapi server belum punya route-nya,
    sehingga request selalu 404 dan cv_engine.start() tidak pernah terpanggil.
    """
    if not cv_engine.is_running:
        cv_engine.start()
        # Beri jeda singkat supaya thread kamera sempat membuka device
        # sebelum kita balas ke frontend (mencegah race condition ringan).
        for _ in range(20):  # maksimal ~2 detik menunggu
            if cv_engine.is_running:
                break
            await asyncio.sleep(0.1)

        update_setting('cameraStatus', 'on')

        if not cv_engine.is_running:
            # Kamera gagal dibuka (mis. device index salah / dipakai app lain)
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
        update_setting('cameraStatus', 'off')  # Sinkronisasi state ke database
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
        update_setting(key, value)  # Simpan ke DB

        # Reaksi langsung (Real-time trigger) jika setting tertentu diubah
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

# ==================== WEBSOCKET STREAMING ====================

@app.websocket("/ws/video")
async def video_stream(websocket: WebSocket):
    """
    WebSocket endpoint yang HILANG sebelumnya.
    camera.html sudah menunggu pesan berformat:
        {"type": "frame", "data": "<base64 jpeg>"}
    dari alamat ws://<host>/ws/video — tapi server belum pernah
    mendefinisikan route ini, sehingga koneksi WebSocket gagal total
    dan gambar kamera tidak pernah muncul di Web UI meski kamera fisik
    sudah menyala.

    Endpoint ini mengambil cv_engine.current_frame (frame terbaru yang
    sudah digambar bounding box + label oleh YOLO di main.py), meng-encode
    ke JPEG, lalu mengirimnya sebagai base64 melalui WebSocket ini.
    """
    await websocket.accept()
    client_id = id(websocket)
    active_websockets[client_id] = websocket

    try:
        while True:
            if cv_engine.current_frame is not None:
                # Encode frame (numpy array BGR dari OpenCV) ke JPEG
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
                # Belum ada frame (mis. kamera baru saja start dan belum
                # sempat membaca frame pertama). Jangan putus koneksi,
                # cukup tunggu siklus berikutnya.
                pass

            # ~15 fps ke browser. Bisa dinaikkan/diturunkan sesuai kekuatan
            # jaringan/CPU; menaikkan terlalu tinggi hanya membebani tanpa
            # menambah kejelasan visual karena kamera sumber juga terbatas fps-nya.
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
            # Check for new alerts
            if cv_engine.alert_count > last_alert_count:
                await websocket.send_json({
                    "type": "alert",
                    "message": "Fall detected!",
                    "timestamp": time.time(),
                    "tracking_data": cv_engine.tracking_states
                })
                last_alert_count = cv_engine.alert_count

            # Send periodic heartbeat
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
    WebSocket khusus untuk mengirim KOORDINAT bounding box saja (tanpa gambar),
    dipakai jika suatu saat video mentah ditampilkan lewat <video>/getUserMedia
    di sisi klien dan overlay box digambar terpisah di <canvas> klien.

    Saat ini alur utama TIDAK memakai endpoint ini — camera.html memakai
    /ws/video yang mengirim frame yang SUDAH digambar box+label di server
    (lihat process_frame di main.py). Endpoint ini tetap disediakan untuk
    kebutuhan lanjutan (mis. jika ingin overlay yang bisa di-toggle terpisah
    dari gambar kamera).
    """
    await websocket.accept()
    client_id = id(websocket)
    active_websockets[client_id] = websocket

    try:
        while True:
            boxes_data = []  # TODO: isi dari cv_engine.current_boxes jika sudah diimplementasikan
            await websocket.send_json(boxes_data)
            await asyncio.sleep(0.1)  # Refresh ~10 kali per detik

    except WebSocketDisconnect:
        print(f"Detect client {client_id} disconnected")
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