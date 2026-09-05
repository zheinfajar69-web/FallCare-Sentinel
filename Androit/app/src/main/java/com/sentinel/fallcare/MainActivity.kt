package com.sentinel.fallcare

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var etServerIp: EditText
    private lateinit var btnSaveIp: Button
    private lateinit var tvStatus: TextView
    private lateinit var viewDot: View

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val isConnected = intent?.getBooleanExtra("is_connected", false) ?: false
            updateStatusUi(isConnected)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        etServerIp = findViewById(R.id.etServerIp)
        btnSaveIp = findViewById(R.id.btnSaveIp)
        tvStatus = findViewById(R.id.tvConnectionStatus)
        viewDot = findViewById(R.id.viewStatusDot)

        val prefs = getSharedPreferences("SentinelPrefs", Context.MODE_PRIVATE)
        val savedIp = prefs.getString("server_ip", "192.168.1.50") ?: "192.168.1.50"
        etServerIp.setText(savedIp)

        btnSaveIp.setOnClickListener {
            val inputIp = etServerIp.text.toString().trim()
            if (inputIp.isEmpty()) {
                Toast.makeText(this, "IP tidak boleh kosong!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            prefs.edit().putString("server_ip", inputIp).apply()
            restartAlertService()
            Toast.makeText(this, "Menyambungkan ke: $inputIp", Toast.LENGTH_SHORT).show()
        }

        checkAndStartService()
    }

    override fun onResume() {
        super.onResume()
        val filter = IntentFilter("com.sentinel.fallcare.CONNECTION_STATUS")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(statusReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(statusReceiver, filter)
        }
    }

    override fun onPause() {
        super.onPause()
        unregisterReceiver(statusReceiver)
    }

    private fun updateStatusUi(isConnected: Boolean) {
        if (isConnected) {
            tvStatus.text = "Siaga (Terhubung)"
            tvStatus.setTextColor(Color.parseColor("#5C7052")) // Moss Bright
            viewDot.setBackgroundColor(Color.parseColor("#5C7052"))
        } else {
            tvStatus.text = "Terputus dari Server"
            tvStatus.setTextColor(Color.parseColor("#9C4A2E")) // Rust
            viewDot.setBackgroundColor(Color.parseColor("#9C4A2E"))
        }
    }

    private fun restartAlertService() {
        val serviceIntent = Intent(this, AlertService::class.java)
        stopService(serviceIntent)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }
    }

    private fun checkAndStartService() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                    101
                )
                return
            }
        }
        restartAlertService()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 101 && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            restartAlertService()
        }
    }
}
