package com.sentinel.fallcare

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.TimeUnit

class AlertService : Service() {

    private lateinit var client: OkHttpClient
    private var webSocket: WebSocket? = null

    // Controller Audio, Getar, dan WakeLock
    private var activeRingtone: Ringtone? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private val alarmHandler = Handler(Looper.getMainLooper())
    private var stopAlarmRunnable: Runnable? = null

    override fun onCreate() {
        super.onCreate()
        startForegroundServiceNotification()
        connectWebSocket()
    }

    private fun startForegroundServiceNotification() {
        val channelId = "sentinel_service_channel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Sentinel Emergency Monitoring",
                NotificationManager.IMPORTANCE_HIGH
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("FallCare-Sentinel Siaga")
            .setContentText("Terhubung sebagai perangkat darurat aktif...")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setOngoing(true)
            .build()

        startForeground(101, notification)
    }

    private fun connectWebSocket() {
        // Ambil IP server dinamis yang tersimpan di SharedPreferences
        val prefs = getSharedPreferences("SentinelPrefs", Context.MODE_PRIVATE)
        val ip = prefs.getString("server_ip", "192.168.1.50") ?: "192.168.1.50"
        val serverUrl = "ws://$ip:8000/ws/events"

        client = OkHttpClient.Builder()
            .pingInterval(5, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()

        val request = Request.Builder().url(serverUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                // Beri tahu UI bahwa koneksi aktif (Hijau)
                val statusIntent = Intent("com.sentinel.fallcare.CONNECTION_STATUS").apply {
                    putExtra("is_connected", true)
                    setPackage(packageName)
                }
                sendBroadcast(statusIntent)

                // Kirim identitas HP ke server
                val manufacturer = Build.MANUFACTURER.replaceFirstChar {
                    if (it.isLowerCase()) it.titlecase(Locale.ROOT) else it.toString()
                }
                val deviceName = "$manufacturer ${Build.MODEL}"

                val registerPayload = JSONObject().apply {
                    put("type", "register_name")
                    put("name", deviceName)
                }
                webSocket.send(registerPayload.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    if (json.optString("type") == "alert") {
                        val mode = json.optString("mode", "keduanya")
                        val duration = json.optInt("duration", 30)
                        val ringtoneType = json.optString("ringtone", "alarm")

                        triggerInstantAlarm(mode, duration, ringtoneType)
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                // Beri tahu UI bahwa koneksi terputus (Merah)
                val statusIntent = Intent("com.sentinel.fallcare.CONNECTION_STATUS").apply {
                    putExtra("is_connected", false)
                    setPackage(packageName)
                }
                sendBroadcast(statusIntent)

                Handler(Looper.getMainLooper()).postDelayed({ connectWebSocket() }, 3000)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                val statusIntent = Intent("com.sentinel.fallcare.CONNECTION_STATUS").apply {
                    putExtra("is_connected", false)
                    setPackage(packageName)
                }
                sendBroadcast(statusIntent)
            }
        })
    }

    private fun triggerInstantAlarm(mode: String, durationSec: Int, ringtoneType: String) {
        alarmHandler.post {
            stopAlarm()

            val durationMs = durationSec * 1000L

            // 1. Bangunkan layar HP selama durasi alarm
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = powerManager.newWakeLock(
                PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
                "Sentinel:AlarmWakeLock"
            )
            wakeLock?.acquire(durationMs)

            // 2. Mainkan nada dering (looping)
            if (mode == "dering" || mode == "keduanya") {
                val soundUri: Uri = when (ringtoneType) {
                    "notification" -> RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
                    "ringtone" -> RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                    else -> RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                        ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                }

                activeRingtone = RingtoneManager.getRingtone(applicationContext, soundUri)
                activeRingtone?.let {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        it.isLooping = true
                    }
                    it.audioAttributes = AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                    it.play()
                }
            }

            // 3. Mainkan getaran (looping)
            if (mode == "getar" || mode == "keduanya") {
                val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                val pattern = longArrayOf(0, 800, 400) // 800ms getar, 400ms jeda
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0))
                } else {
                    @Suppress("DEPRECATION")
                    vibrator.vibrate(pattern, 0)
                }
            }

            // 4. Timer berhenti otomatis sesuai batas durasi yang diterima
            stopAlarmRunnable = Runnable { stopAlarm() }
            stopAlarmRunnable?.let { alarmHandler.postDelayed(it, durationMs) }
        }
    }

    private fun stopAlarm() {
        stopAlarmRunnable?.let { alarmHandler.removeCallbacks(it) }

        activeRingtone?.let {
            if (it.isPlaying) {
                it.stop()
            }
        }
        activeRingtone = null

        val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        vibrator.cancel()

        if (wakeLock?.isHeld == true) {
            wakeLock?.release()
        }
        wakeLock = null
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopAlarm()
        webSocket?.close(1000, "Service dimatikan")
        super.onDestroy()
    }
}