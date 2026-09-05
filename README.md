# FallCare-Sentinel

> Sistem dasbor pengawasan cerdas berbasis web untuk memantau dan mendeteksi insiden jatuh secara real-time melalui peramban.
**Repositori Resmi:** [https://github.com/zheinfajar69-web/FallCare-Sentinel](https://github.com/zheinfajar69-web/FallCare-Sentinel)
---
## Ringkasan Proyek

FallCare-Sentinel dirancang untuk mengintegrasikan pemrosesan visual di sisi klien dan inferensi kecerdasan buatan di sisi server. Sistem ini tidak hanya memantau aliran video, tetapi juga menyediakan dasbor analitik performa server dan manajemen notifikasi darurat yang terpusat.

## Fitur Utama
| Modul | Fungsi & Spesifikasi |
|---|---|
| **Pemantauan Kamera** | Menampilkan video langsung dengan overlay rangka tubuh (*MediaPipe*) dan kotak pembatas (*YOLO Bounding Box*) tanpa jeda. |
| **Filter Visibilitas** | Dilengkapi filter Normal, Inversi Warna, dan Hitam Putih untuk adaptasi lingkungan tanpa merusak akurasi deteksi *backend*. |
| **Dasbor Performa** | Visualisasi metrik *real-time* 30 detik terakhir untuk CPU, RAM, latensi inferensi, dan *uptime* menggunakan grafik dinamis. |
| **Notifikasi Pushover** | Mendukung hingga 5 target perangkat. Mengirimkan sinyal darurat berupa getaran dan dering saat target terdeteksi jatuh. |
| **Antarmuka Modern** | Dibangun dengan prinsip *Semantic HTML* dan *Tailwind CSS*. Responsif untuk semua perangkat dan mendukung *Dark Mode*. |
---

## Arsitektur & Teknologi
Proyek ini dipisahkan menjadi dua lapisan utama untuk memastikan beban komputasi terdistribusi dengan baik:
### Lapisan Klien (Frontend)
*   **Struktur & Desain:** HTML5, Tailwind CSS
*   **Logika Interaktif:** Vanilla JavaScript
*   **Pemrosesan Rangka Visual:** MediaPipe Pose (*WebAssembly*)
*   **Visualisasi Data:** Chart.js
### Lapisan Server (Backend)
*   **Engine Utama:** Python
*   **Deteksi Objek:** Model YOLO
*   **Lalu Lintas Data:** WebSocket Server (Komunikasi dua arah latensi rendah)
*   **Basis Data:** SQLite (Penyimpanan konfigurasi sistem)
---

## Peta Direktori Antarmuka
```text
/frontend
├── camera.html       # Kanvas utama pemantauan dan kontrol filter video
├── performance.html  # Dasbor pemantauan kesehatan server (CPU/RAM/Latensi)
├── settings.html     # Manajemen kunci API Pushover dan perangkat notifikasi
└── login.html        # Portal autentikasi untuk mengamankan dasbor

Panduan Instalasi dan Penggunaan
1. Persiapan Sistem
Pastikan mesin Anda telah dilengkapi dengan Python 3.8+ dan Anda menggunakan peramban web modern yang mendukung WebRTC serta protokol WebSocket.

2. Unduh Repositori
Lakukan kloning repositori ini ke dalam direktori lokal Anda:

Bash
git clone [https://github.com/zheinfajar69-web/FallCare-Sentinel.git](https://github.com/zheinfajar69-web/FallCare-Sentinel.git)
cd FallCare-Sentinel
3. Konfigurasi Backend
Disarankan untuk menggunakan virtual environment. Instal seluruh dependensi yang diperlukan, kemudian jalankan server utama:

Bash
pip install -r requirements.txt
python main.py
4. Akses Dasbor
Buka berkas login.html melalui peramban web, atau gunakan ekstensi Live Server pada code editor Anda agar fungsi pengambilan jaringan berjalan optimal.

Izinkan akses kamera pada peramban agar sistem pemetaan rangka dari MediaPipe dapat beroperasi.

Masuk ke halaman Pengaturan untuk mendaftarkan nama pemilik dan User Key Pushover agar notifikasi darurat dapat dirutekan dengan benar.
