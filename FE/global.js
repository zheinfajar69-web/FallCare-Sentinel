/* =====================================================================
   global.js — Logika bersama untuk semua halaman ByteCraft / Sentra Pengawas
   (camera, performance, settings, login)

   Muat file ini via <script src="global.js"></script> SEBELUM script
   khusus tiap halaman, lalu panggil ByteCraft.init() begitu DOM siap.
   Setiap sub-modul aman dipanggil walau elemen terkait tidak ada di
   halaman tersebut (mis. login.html tidak punya sidebar).
===================================================================== */

const ByteCraft = (() => {

  /* ---------- Tema (dark/light) ---------- */
  const Theme = {
    STORAGE_KEY: 'sentra_theme',

    isDark(){
      return document.documentElement.classList.contains('dark');
    },

    apply(dark){
      document.documentElement.classList.toggle('dark', dark);
      localStorage.setItem(this.STORAGE_KEY, dark ? 'dark' : 'light');

      const iconMoon = document.getElementById('iconMoon');
      const iconSun = document.getElementById('iconSun');
      if(iconMoon) iconMoon.classList.toggle('hidden', dark);
      if(iconSun) iconSun.classList.toggle('hidden', !dark);

      // Hook opsional untuk halaman yang punya chart (mis. performance.html)
      if(typeof window.updateChartColors === 'function') window.updateChartColors(dark);
    },

    toggle(){
      this.apply(!this.isDark());
    },

    init(){
      this.apply(localStorage.getItem(this.STORAGE_KEY) === 'dark');

      const btn = document.getElementById('themeToggle');
      const btnMobile = document.getElementById('themeToggleMobile');
      if(btn) btn.addEventListener('click', () => this.toggle());
      if(btnMobile) btnMobile.addEventListener('click', () => this.toggle());
    }
  };

  /* ---------- Sidebar desktop (pin dengan dobel klik) ---------- */
  const Sidebar = {
    init(){
      const sidebar = document.getElementById('sidebar');
      if(!sidebar) return;
      sidebar.addEventListener('dblclick', () => sidebar.classList.toggle('pinned-open'));
    }
  };

  /* ---------- Menu mobile (hamburger + overlay) ---------- */
  const MobileMenu = {
    init(){
      const hamburgerBtn = document.getElementById('hamburgerBtn');
      const overlay = document.getElementById('mobileMenuOverlay');
      const overlayBg = document.getElementById('mobileOverlayBg');
      if(!hamburgerBtn || !overlay || !overlayBg) return;

      const open = () => {
        overlay.classList.remove('hidden');
        hamburgerBtn.setAttribute('aria-expanded', 'true');
      };
      const close = () => {
        overlay.classList.add('hidden');
        hamburgerBtn.setAttribute('aria-expanded', 'false');
      };

      hamburgerBtn.addEventListener('click', open);
      overlayBg.addEventListener('click', close);
    }
  };

  /* ---------- Jam realtime (format id-ID, 24 jam) ---------- */
  const Clock = {
    _timer: null,

    tick(){
      const el = document.getElementById('clock');
      if(el) el.textContent = new Date().toLocaleTimeString('id-ID', { hour12: false });
    },

    init(){
      if(!document.getElementById('clock')) return;
      this.tick();
      this._timer = setInterval(() => this.tick(), 1000);
    }
  };

  /* ---------- Helper: escape HTML (dipakai saat render data dinamis) ---------- */
  function escapeHtml(str){
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /* ---------- Helper: simpan satu key pengaturan ke backend (PUT /api/settings) ---------- */
  async function saveSettingToServer(key, value){
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value })
      });
      return res.ok;
    } catch (err) {
      return false;
    }
  }

  /* ---------- Init semua modul umum sekaligus ---------- */
  function init(){
    Theme.init();
    Sidebar.init();
    MobileMenu.init();
    Clock.init();
  }

  return { init, Theme, Sidebar, MobileMenu, Clock, escapeHtml, saveSettingToServer };
})();