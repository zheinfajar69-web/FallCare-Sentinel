import cv2
import time
import torch
import requests
import winsound
from ultralytics import YOLO

PUSHOVER_APP_TOKEN = "GANTI_DENGAN_APP_TOKEN_PUSHOVER"
PUSHOVER_USER_KEY = "GANTI_DENGAN_USER_KEY_PUSHOVER"
THRESHOLD_JATUH = 0.60 
DURASI_PINGSAN = 7 

def kirim_pushover_emergency(pesan):
    """Mengirim notifikasi darurat Pushover (Priority 2 / Siren)."""
    url = "https://api.pushover.net/1/messages.json"
    payload = {
        "token": PUSHOVER_APP_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "message": pesan,
        "title": "🚨 EMERGENCY: ORANG PINGSAN!",
        "priority": 2,
        "retry": 30,
        "expire": 3600,
        "sound": "siren"
    }
    try:
        response = requests.post(url, data=payload, timeout=5)
        if response.status_code == 200:
            print("[PUSHOVER] Notifikasi darurat berhasil terkirim!")
        else:
            print(f"[PUSHOVER] Gagal kirim. Status: {response.status_code}")
    except Exception as e:
        print(f"[PUSHOVER] Gangguan internet: {e}")

# Menggunakan GPU RTX 4050 jika CUDA tersedia, jika tidak otomatis ke CPU
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"=== SISTER DETEKSI PINGSAN MULTI-PERSON (YOLOv8) ===")
print(f"Running on Device: {device.upper()}")

# Load model YOLOv8 Pose (Otomatis mendownload weights jika belum ada)
model = YOLO('yolov8n-pose.pt')

cap = cv2.VideoCapture(0)

# Dictionary untuk menyimpan state tracking per ID orang:
# { person_id: {'status': 'NORMAL', 'waktu_jatuh': 0} }
person_states = {}

print("Sistem aktif! Tekan tombol 'q' untuk berhenti.")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("Gagal mengambil frame dari kamera.")
        break

# ... existing code ...
    frame = cv2.flip(frame, 1)

    # Deteksi dan Tracking Multi-Person (Conf 0.15 agar tetap peka saat orang tergeletak)
    results = model.track(frame, persist=True, device=device, verbose=False, conf=0.15)

    annotated_frame = frame.copy()

    # Pengecekan ada objek terdeteksi (tidak tergantung boxes.id != None)
    if results and len(results) > 0 and results[0].boxes is not None and len(results[0].boxes) > 0:
        boxes = results[0].boxes
        keypoints = results[0].keypoints.xyn  # Koord ter-normalisasi (N, 17, 2)
        
        # Ambil ID dari tracker, jika tracker belum siap gunakan ID fallback (1, 2, dst)
        if boxes.id is not None:
            track_ids = boxes.id.int().cpu().tolist()
        else:
            track_ids = list(range(1, len(boxes) + 1))

        for i, p_id in enumerate(track_ids):
            # Inisialisasi state jika ID baru terdeteksi
            if p_id not in person_states:
                person_states[p_id] = {'status': 'NORMAL', 'waktu_jatuh': 0}

            kpts = keypoints[i] # Keypoints untuk person ID ini (17, 2)
            
            # Keypoint COCO Pose: 5=Bahu Kiri, 6=Bahu Kanan, 11=Pinggul Kiri, 12=Pinggul Kanan
            x_bahu = (kpts[5][0].item() + kpts[6][0].item()) / 2.0
            y_bahu = (kpts[5][1].item() + kpts[6][1].item()) / 2.0

            x_pinggul = (kpts[11][0].item() + kpts[12][0].item()) / 2.0
            y_pinggul = (kpts[11][1].item() + kpts[12][1].item()) / 2.0

            delta_x = abs(x_bahu - x_pinggul)
            delta_y = abs(y_bahu - y_pinggul)

            # Kondisi Horisontal & Rendah (Mencegah false alarm saat jongkok)
            posisi_horisontal = delta_x > (delta_y * 0.7)
            posisi_rendah = y_bahu > THRESHOLD_JATUH
            tergeletak = posisi_rendah and posisi_horisontal

            st = person_states[p_id]['status']

            if st == "NORMAL":
                if tergeletak:
                    person_states[p_id]['status'] = "POTENTIAL_FALL"
                    person_states[p_id]['waktu_jatuh'] = time.time()
                    print(f"[LOG] ID #{p_id} terindikasi tergeletak/pingsan. Menghitung durasi...")

            elif st == "POTENTIAL_FALL":
                if not tergeletak:
                    person_states[p_id]['status'] = "NORMAL"
                    print(f"[LOG] ID #{p_id} bangkit/berdiri tegak. Status reset ke NORMAL.")
                elif (time.time() - person_states[p_id]['waktu_jatuh']) > DURASI_PINGSAN:
                    person_states[p_id]['status'] = "FAINTED"

            elif st == "FAINTED":
                print(f"[ALARM] WARNING! ID #{p_id} TERDETEKSI PINGSAN!")
                winsound.Beep(1000, 500)
                kirim_pushover_emergency(f"🚨 ALERT! ID #{p_id} pingsan di area pantauan kamera!")
                person_states[p_id]['status'] = "ALERT_SENT"

            elif st == "ALERT_SENT":
                if not tergeletak:
                    person_states[p_id]['status'] = "NORMAL"
                    print(f"[AUTO-RESET] ID #{p_id} telah bangkit atau dievakuasi. Reset ke NORMAL.")

            box = boxes[i].xyxy[0].cpu().numpy().astype(int)
            x1, y1, x2, y2 = box[0], box[1], box[2], box[3]

            curr_st = person_states[p_id]['status']
            warna_hud = (0, 255, 0) # Hijau
            if curr_st == "POTENTIAL_FALL":
                warna_hud = (0, 165, 255) # Oranye
            elif curr_st in ["FAINTED", "ALERT_SENT"]:
                warna_hud = (0, 0, 255) # Merah

            # Gambar Bounding Box & Label Status untuk Setiap Orang
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), warna_hud, 2)
            cv2.putText(annotated_frame, f"ID #{p_id} | {curr_st}", (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, warna_hud, 2)
            cv2.putText(annotated_frame, f"Y-Bahu: {y_bahu:.2f}", (x1, y1 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            if curr_st == "POTENTIAL_FALL":
                sisa_waktu = int(DURASI_PINGSAN - (time.time() - person_states[p_id]['waktu_jatuh']))
                cv2.putText(annotated_frame, f"Mengecek Pingsan: {sisa_waktu}s", (x1, y1 + 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

    cv2.imshow('Sistem Deteksi Pingsan Multi-Person (YOLOv8)', annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
