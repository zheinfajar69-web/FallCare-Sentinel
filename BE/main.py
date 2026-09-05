import cv2
import time
import requests
import subprocess
import numpy as np
from ultralytics import YOLO
from typing import Dict, Optional
import threading

from .database import get_all_pushover_devices, get_setting

# ================= KONDISI & KONFIGURASI =================
# CATATAN: PUSHOVER_TOKEN di bawah ini adalah APP TOKEN Pushover (satu untuk
# seluruh aplikasi ByteCraft, didaftarkan sekali di pushover.net/apps/build).
# Ini BEDA dengan "user key" per perangkat yang sekarang disimpan di tabel
# `pushover_devices` (lihat database.py) dan diatur lewat settings.html —
# app token tetap 1 untuk semua, tapi user key-nya banyak (hingga 5 orang).
PUSHOVER_TOKEN = "aks9st43qwxmogx7uchat36inzztie"
YOLO_MODEL = "yolov8n-pose.pt"

STATE_NORMAL = "NORMAL"
STATE_POTENTIAL = "POTENTIAL_FALL"
STATE_FAINTED = "FAINTED"
STATE_ALERT = "ALERT_SENT"

FALL_TIME_THRESHOLD = 7.0
ALARM_AUDIO_PATH = "/usr/share/sounds/alsa/Front_Center.wav"

# Pemetaan notifMode (dipilih user di camera.html, tersimpan di tabel
# `settings` key 'notifMode') -> parameter Pushover di HP penerima.
# - 'getar'    : tanpa suara khusus (device pakai getar/silent sesuai
#                pengaturan HP masing-masing), priority normal.
# - 'dering'   : suara alarm (sound='siren') + priority tinggi (2) supaya
#                Pushover mengulang notifikasi sampai di-acknowledge.
# - 'keduanya' : sama seperti 'dering' — priority 2 + sound siren akan tetap
#                membuat HP bergetar DAN berbunyi (perilaku default HP saat
#                menerima notifikasi prioritas tinggi), jadi ini yang paling
#                mendekati "getar dan dering" tanpa perlu API terpisah untuk
#                getar (Pushover tidak punya kontrol getar independen).
NOTIF_MODE_PARAMS = {
    "getar":    {"sound": "none",  "priority": 0},
    "dering":   {"sound": "siren", "priority": 2},
    "keduanya": {"sound": "siren", "priority": 2},
}
# =========================================================

class FallDetectionEngine:
    def __init__(self):
        self.model = YOLO(YOLO_MODEL)
        self.tracking_states: Dict = {}
        self.current_frame: Optional[np.ndarray] = None
        self.is_running = False
        self.fall_time_threshold = FALL_TIME_THRESHOLD
        self.model_path = YOLO_MODEL
        self.pushover_token = PUSHOVER_TOKEN
        self.alert_count = 0
        self.current_fps = 0
        # BARU: waktu inferensi YOLO frame terakhir (ms), dibaca oleh
        # server.py di endpoint /ws/performance untuk grafik "Latensi
        # Inferensi (YOLO)" di performance.html. Sebelumnya field ini tidak
        # ada sama sekali sehingga grafik itu selalu menampilkan 0 ms.
        self.last_inference_ms: float = 0.0
        self._stop_event = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None

    def trigger_pushover_alert(self, track_id: int):
        """
        Kirim notifikasi darurat ke SEMUA perangkat Pushover yang terdaftar
        di database (tabel pushover_devices, diatur lewat settings.html),
        dengan sound/priority mengikuti notifMode yang dipilih user di
        camera.html (tabel settings, key 'notifMode').

        Sebelumnya fungsi ini hanya mengirim ke SATU user key hardcode
        (PUSHOVER_USER) dan mengabaikan notifMode sepenuhnya. Sekarang:
        1. Ambil daftar device dari database (bisa 0-5 device).
        2. Ambil notifMode tersimpan, default 'keduanya' kalau belum diatur.
        3. Kirim satu request per device, dengan sound/priority sesuai mode.
        """
        devices = get_all_pushover_devices()
        if not devices:
            print("Pushover: tidak ada perangkat terdaftar di Pengaturan — alert tidak dikirim ke HP manapun.")
            return

        notif_mode = get_setting("notifMode", "keduanya")
        mode_params = NOTIF_MODE_PARAMS.get(notif_mode, NOTIF_MODE_PARAMS["keduanya"])

        url = "https://api.pushover.net/1/messages.json"
        for device in devices:
            data = {
                "token": self.pushover_token,
                "user": device["api_key"],
                "message": f"EMERGENCY: Person {track_id} has fainted and remained down!",
                "priority": mode_params["priority"],
                "sound": mode_params["sound"],
            }
            # Priority 2 (emergency) WAJIB menyertakan retry & expire di API
            # Pushover, kalau tidak request akan ditolak dengan error 400.
            if mode_params["priority"] == 2:
                data["retry"] = 30
                data["expire"] = 3600

            try:
                response = requests.post(url, data=data, timeout=3)
                if response.status_code != 200:
                    print(f"Pushover Error ({device['name']}): {response.text}")
            except Exception as e:
                print(f"Pushover Connection Failed ({device['name']}): {e}")

    def play_alarm(self):
        """Play alarm sound"""
        try:
            subprocess.Popen(["aplay", "-q", ALARM_AUDIO_PATH],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Process single frame for fall detection"""
        _inference_start = time.time()
        results = self.model.track(frame, persist=True, classes=0, verbose=False)
        # Dicatat segera setelah inferensi YOLO selesai (sebelum semua
        # perhitungan state machine di bawah, yang bukan bagian dari
        # "latensi inferensi" itu sendiri).
        self.last_inference_ms = (time.time() - _inference_start) * 1000
        current_ids = []

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.int().cpu().tolist()
            keypoints = results[0].keypoints.data.cpu().numpy()

            for box, track_id, kpts in zip(boxes, track_ids, keypoints):
                current_ids.append(track_id)

                x1, y1, x2, y2 = map(int, box)
                w = x2 - x1
                h = y2 - y1

                # Inisialisasi state & memori postur
                if track_id not in self.tracking_states:
                    self.tracking_states[track_id] = {
                        'state': STATE_NORMAL,
                        'timestamp': None,
                        'max_h': h
                    }

                state_info = self.tracking_states[track_id]

                # Adaptasi Baseline
                if state_info['state'] == STATE_NORMAL and h > w:
                    state_info['max_h'] = max(state_info['max_h'] * 0.95 + h * 0.05, h)

                baseline_h = state_info['max_h']

                s_l, s_r = kpts[5], kpts[6]
                h_l, h_r = kpts[11], kpts[12]

                valid_keypoints = all(pt[2] > 0.4 for pt in [s_l, s_r, h_l, h_r])

                # EVALUASI 3 KONDISI
                is_horizontal = w > (1.3 * h)
                is_crumpled = h < (0.5 * baseline_h)

                keypoint_collapse = False
                if valid_keypoints:
                    shoulder_y = (s_l[1] + s_r[1]) / 2.0
                    hip_y = (h_l[1] + h_r[1]) / 2.0
                    if abs(shoulder_y - hip_y) < (0.2 * baseline_h):
                        keypoint_collapse = True

                is_falling_condition = is_horizontal or is_crumpled or keypoint_collapse

                # STATE MACHINE
                current_time = time.time()

                if is_falling_condition:
                    if state_info['state'] == STATE_NORMAL:
                        state_info['state'] = STATE_POTENTIAL
                        state_info['timestamp'] = current_time

                    elif state_info['state'] == STATE_POTENTIAL:
                        elapsed = current_time - state_info['timestamp']
                        if elapsed >= self.fall_time_threshold:
                            state_info['state'] = STATE_FAINTED

                    elif state_info['state'] == STATE_FAINTED:
                        self.play_alarm()
                        self.trigger_pushover_alert(track_id)
                        state_info['state'] = STATE_ALERT
                        self.alert_count += 1

                    elif state_info['state'] == STATE_ALERT:
                        if int(current_time * 10) % 20 == 0:
                            self.play_alarm()
                else:
                    state_info['state'] = STATE_NORMAL
                    state_info['timestamp'] = None

                # VISUALISASI
                color = (0, 255, 0)
                label = f"ID: {track_id} | {state_info['state']} | H:{h}/{int(baseline_h)}"

                if state_info['state'] == STATE_POTENTIAL:
                    color = (0, 165, 255)
                    elapsed = current_time - state_info['timestamp']
                    label += f" | {max(0, int(self.fall_time_threshold - elapsed))}s"
                elif state_info['state'] in [STATE_FAINTED, STATE_ALERT]:
                    color = (0, 0, 255)

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, label, (x1, max(y1 - 10, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Cleanup Memory
        stale_ids = [tid for tid in self.tracking_states if tid not in current_ids]
        for tid in stale_ids:
            del self.tracking_states[tid]

        return frame

    def run(self):
        """Main loop - run in separate thread"""
        # BUKA KAMERA DI SINI: Saat thread mulai berjalan
        self._cap = cv2.VideoCapture(0) # Coba pakai index 0 dulu

        if not self._cap.isOpened():
            print("🚨 ERROR: Kamera gagal dibuka! Coba ganti index ke 1 atau 2.")
            self.is_running = False
            return

        self.is_running = True
        prev_time = time.time()
        frame_count = 0

        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if not ret:
                break

            # Process frame
            processed_frame = self.process_frame(frame)
            self.current_frame = processed_frame

            # Calculate FPS
            frame_count += 1
            if frame_count % 30 == 0:
                current_time = time.time()
                self.current_fps = frame_count / (current_time - prev_time)
                prev_time = current_time
                frame_count = 0

            # Optional: Display locally (can be disabled in server mode)
            # cv2.imshow("Advanced Fall Detection", processed_frame)
            # if cv2.waitKey(1) & 0xFF == ord('q'):
            #     break

        self._cap.release()
        # cv2.destroyAllWindows()
        self.is_running = False

    def start(self):
        """Start detection engine"""
        if not self.is_running:
            self._stop_event.clear()
            thread = threading.Thread(target=self.run, daemon=True)
            thread.start()

    def stop(self):
        """Stop detection engine"""
        self._stop_event.set()
        self.is_running = False

    def get_status(self) -> dict:
        """Get current engine status"""
        return {
            "running": self.is_running,
            "active_tracks": len(self.tracking_states),
            "fps": self.current_fps,
            "alerts": self.alert_count
        }

# Legacy compatibility (if run directly)
if __name__ == "__main__":
    engine = FallDetectionEngine()
    engine.run()