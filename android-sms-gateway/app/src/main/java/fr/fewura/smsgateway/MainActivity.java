package fr.fewura.smsgateway;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.Collections;
import java.util.UUID;

public class MainActivity extends Activity {
    private static final int SMS_PERMISSION = 1001;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String token = getSharedPreferences("fewura_sms", MODE_PRIVATE).getString("token", "");
        if (token.isEmpty()) {
            token = UUID.randomUUID().toString().replace("-", "");
            getSharedPreferences("fewura_sms", MODE_PRIVATE).edit().putString("token", token).apply();
        }

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 32, 32, 32);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("FEWURA SMS Gateway");
        title.setTextSize(24f);
        root.addView(title);

        TextView info = new TextView(this);
        info.setText("Cette application permet à FEWURA CRM d'envoyer des SMS avec la SIM du téléphone.\n\nNuméro prévu : +33 7 73 54 78 57\nPort local : 8765\nAdresse : http://" + localIp() + ":8765\nJeton : " + token + "\n\nLe téléphone et le PC doivent être sur le même réseau local. Le numéro réellement utilisé est celui de la SIM active sélectionnée par Android.");
        info.setTextIsSelectable(true);
        info.setPadding(0, 24, 0, 24);
        root.addView(info);

        Button grant = new Button(this);
        grant.setText("Autoriser l'envoi de SMS");
        grant.setOnClickListener(v -> requestSmsPermission());
        root.addView(grant);

        Button start = new Button(this);
        start.setText("Démarrer la passerelle");
        start.setOnClickListener(v -> startGateway());
        root.addView(start);

        Button stop = new Button(this);
        stop.setText("Arrêter la passerelle");
        stop.setOnClickListener(v -> {
            stopService(new Intent(this, SmsGatewayService.class));
            refreshStatus("Passerelle arrêtée");
        });
        root.addView(stop);

        Button battery = new Button(this);
        battery.setText("Ouvrir les réglages batterie");
        battery.setOnClickListener(v -> {
            try { startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
            catch (Exception ignored) { }
        });
        root.addView(battery);

        status = new TextView(this);
        status.setPadding(0, 24, 0, 0);
        root.addView(status);
        setContentView(scroll);
        refreshStatus("Prêt");
    }

    private void requestSmsPermission() {
        if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.SEND_SMS}, SMS_PERMISSION);
        } else {
            refreshStatus("Permission SMS accordée");
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1002);
        }
    }

    private void startGateway() {
        if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            requestSmsPermission();
            refreshStatus("Autorisez d'abord l'envoi de SMS");
            return;
        }
        Intent i = new Intent(this, SmsGatewayService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i); else startService(i);
        refreshStatus("Passerelle démarrée sur http://" + localIp() + ":8765");
    }

    private void refreshStatus(String text) {
        if (status != null) status.setText(text);
    }

    public static String localIp() {
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) continue;
                for (java.net.InetAddress address : Collections.list(nif.getInetAddresses())) {
                    if (address instanceof Inet4Address && !address.isLoopbackAddress()) return address.getHostAddress();
                }
            }
        } catch (Exception ignored) { }
        return "IP_DU_TELEPHONE";
    }
}
