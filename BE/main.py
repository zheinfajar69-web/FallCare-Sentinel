import cv2
import time
import requests
import subprocess
import numpy as np
from ultralytics import YOLO

# ================= KONDISI & KONFIGURASI =================
PUSHOVER_TOKEN = "GANTI_DENGAN_APP_TOKEN_ANDA"
PUSHOVER_USER = "GANTI_DENGAN_USER_KEY_ANDA"
YOLO_MODEL = "yolov8n-pose.pt"

STATE_NORMAL = "NORMAL"
STATE_POTENTIAL = "POTENTIAL_FALL"
STATE_FAINTED = "FAINTED"
STATE_ALERT = "ALERT_SENT"

FALL_TIME_THRESHOLD = 7.0 
ALARM_AUDIO_PATH = "/usr/share/sounds/alsa/Front_Center.wav" 
# =========================================================

model = YOLO(YOLO_MODEL)
tracking_states = {}

def trigger_pushover_alert(track_id):
    url = "https://api.pushover.net/1/messages.json"
    data = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "message": f"EMERGENCY: Person {track_id} has fainted and remained down!",
        "priority": 2,          
        "retry": 30,            
        "expire": 3600,         
        "sound": "siren"
    }
    try:
        response = requests.post(url, data=data, timeout=3)
        if response.status_code != 200:
            print(f"Pushover Error: {response.text}")
    except Exception as e:
        print(f"Pushover Connection Failed: {e}")

def play_alarm():
    try:
        # Menggunakan paplay (PulseAudio) atau aplay (ALSA)
        subprocess.Popen(["aplay", "-q", ALARM_AUDIO_PATH], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass # Hindari terminal spam jika file/command tidak ada

cap = cv2.VideoCapture(0)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
        
    results = model.track(frame, persist=True, classes=0, verbose=False)
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
            if track_id not in tracking_states:
                tracking_states[track_id] = {
                    'state': STATE_NORMAL, 
                    'timestamp': None,
                    'max_h': h # Simpan tinggi awal sebagai baseline
                }
                
            state_info = tracking_states[track_id]
            
            # Adaptasi Baseline: Hanya update tinggi maksimal jika objek sedang NORMAL dan berdiri (h > w)
            if state_info['state'] == STATE_NORMAL and h > w:
                # Moving average untuk beradaptasi dengan perubahan jarak ke kamera
                state_info['max_h'] = max(state_info['max_h'] * 0.95 + h * 0.05, h)
                
            baseline_h = state_info['max_h']
            
            s_l, s_r = kpts[5], kpts[6]
            h_l, h_r = kpts[11], kpts[12]
            
            valid_keypoints = all(pt[2] > 0.4 for pt in [s_l, s_r, h_l, h_r])
            
            # EVALUASI 3 KONDISI BAD CASES
            is_horizontal = w > (1.3 * h)
            is_crumpled = h < (0.5 * baseline_h)
            
            keypoint_collapse = False
            if valid_keypoints:
                shoulder_y = (s_l[1] + s_r[1]) / 2.0
                hip_y = (h_l[1] + h_r[1]) / 2.0
                # Jika jarak vertikal bahu ke pinggul kurang dari 20% tinggi normal objek
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
                    if elapsed >= FALL_TIME_THRESHOLD:
                        state_info['state'] = STATE_FAINTED
                        
                elif state_info['state'] == STATE_FAINTED:
                    play_alarm()
                    trigger_pushover_alert(track_id)
                    state_info['state'] = STATE_ALERT
                    
                elif state_info['state'] == STATE_ALERT:
                    # Delay pemanggilan alarm agar audio tidak bertumpuk patah-patah
                    if int(current_time * 10) % 20 == 0: 
                        play_alarm()
            else:
                # Jika berdiri kembali, interupsi siklus pingsan
                state_info['state'] = STATE_NORMAL
                state_info['timestamp'] = None

            # VISUALISASI
            color = (0, 255, 0)
            label = f"ID: {track_id} | {state_info['state']} | H:{h}/{int(baseline_h)}"
            
            if state_info['state'] == STATE_POTENTIAL:
                color = (0, 165, 255)
                elapsed = current_time - state_info['timestamp']
                label += f" | {max(0, int(FALL_TIME_THRESHOLD - elapsed))}s"
            elif state_info['state'] in [STATE_FAINTED, STATE_ALERT]:
                color = (0, 0, 255)
                
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 10, 0)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    # Cleanup Memory
    stale_ids = [tid for tid in tracking_states if tid not in current_ids]
    for tid in stale_ids:
        del tracking_states[tid]

    cv2.imshow("Advanced Fall Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

