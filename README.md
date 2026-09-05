FallCare-Sentinel
FallCare-Sentinel adalah sistem dasbor pengawasan cerdas berbasis web yang dirancang untuk memantau dan mendeteksi insiden jatuh secara real-time. Sistem ini menggabungkan pemrosesan postur tubuh di sisi peramban (client-side) dan inferensi model kecerdasan buatan di sisi server (backend) untuk memberikan peringatan darurat yang cepat dan akurat.

Fitur Utama
Pemantauan Kamera Real-time: Menampilkan aliran video langsung dari antarmuka web dengan overlay rangka tubuh (skeleton) yang diproses langsung di peramban, bersanding dengan kotak pembatas (bounding box) deteksi jatuh dari server.

Mode Tampilan Visual: Dilengkapi dengan filter visual (Normal, Inversi Warna, dan Hitam Putih) untuk membantu pemantauan dalam berbagai kondisi pencahayaan, tanpa mengganggu proses deteksi AI.

Pemantauan Performa Sistem (Live): Menyediakan grafik real-time untuk penggunaan CPU, alokasi RAM server, latensi inferensi model (YOLO), dan waktu aktif (uptime) server menggunakan Chart.js dan WebSocket.

Manajemen Notifikasi Darurat (Pushover): Mendukung hingga 5 integrasi perangkat menggunakan Pushover API. Sistem akan mengirimkan notifikasi instan (getar/dering) ke perangkat yang terdaftar apabila insiden jatuh terdeteksi. Pengaturan ini dikelola dan disimpan dengan aman di basis data lokal.

Antarmuka Responsif & Mode Gelap: Desain antarmuka yang bersih, semantik, dan responsif untuk penggunaan di desktop maupun perangkat seluler (mobile), lengkap dengan fitur peralihan Mode Gelap (Dark Mode).

Arsitektur Teknologi
Sisi Klien (Frontend):

HTML5 & Vanilla JavaScript

Tailwind CSS (via CDN)

MediaPipe Pose (Pemetaan rangka tubuh di peramban)

Chart.js (Visualisasi metrik performa)

WebSocket API (Penerimaan data deteksi dan performa secara real-time)

Sisi Server (Backend):

Python (Engine utama pengolahan data)

Model YOLO (Deteksi objek/jatuh)

WebSocket Server (Komunikasi dua arah dengan klien)

SQLite (Penyimpanan konfigurasi API Pushover dan pengaturan sistem)

Struktur File Frontend
camera.html - Antarmuka utama untuk pemantauan video, filter visual, dan rendering deteksi (MediaPipe & YOLO).

performance.html - Dasbor analitik untuk memantau kesehatan server, penggunaan CPU, RAM, dan latensi inferensi secara real-time.

settings.html - Halaman konfigurasi untuk mengatur dan mengelola User Key Pushover API sebagai target notifikasi darurat.

login.html - Halaman autentikasi untuk mengamankan akses ke dasbor pengawas.

Prasyarat
Sebelum menjalankan FallCare-Sentinel, pastikan sistem Anda telah memiliki:

Python versi 3.8 atau lebih baru.

Lingkungan virtual (opsional namun direkomendasikan) untuk dependensi backend.

Peramban web modern (Chrome, Firefox, Edge, atau Safari) yang mendukung WebRTC (MediaDevices API) dan WebSocket.

Instalasi dan Penggunaan
Kloning repositori ini ke dalam mesin lokal atau server Anda:

Bash
git clone https://github.com/username/FallCare-Sentinel.git
cd FallCare-Sentinel
Konfigurasi Backend:
Instal dependensi Python yang dibutuhkan (sesuaikan dengan requirements.txt dari sisi backend) dan jalankan server WebSocket/Deteksi.

Bash
pip install -r requirements.txt
python main.py
Akses Antarmuka:
Buka file login.html atau akses localhost sesuai dengan port server yang Anda tetapkan melalui peramban web. Pastikan peramban memberikan izin akses kamera (jika menggunakan webcam lokal) untuk menjalankan fungsi MediaPipe Pose.

Konfigurasi Notifikasi:
Masuk ke menu Pengaturan, tambahkan Nama Pemilik dan User Key dari Pushover, lalu simpan. Sistem akan mulai merutekan peringatan ke perangkat tersebut.
