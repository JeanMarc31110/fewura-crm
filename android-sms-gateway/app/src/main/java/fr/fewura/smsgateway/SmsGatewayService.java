package fr.fewura.smsgateway;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.IBinder;
import android.telephony.SmsManager;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class SmsGatewayService extends Service {
    private static final int PORT = 8765;
    private static final int NOTIFICATION_ID = 73354857;
    private static final String CHANNEL = "fewura_sms_gateway";
    private volatile boolean running = false;
    private ServerSocket serverSocket;
    private ExecutorService workers;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        startForeground(NOTIFICATION_ID, notification());
        running = true;
        workers = Executors.newFixedThreadPool(4);
        new Thread(this::serverLoop, "fewura-sms-server").start();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    private void serverLoop() {
        try {
            serverSocket = new ServerSocket(PORT);
            while (running) {
                Socket socket = serverSocket.accept();
                workers.submit(() -> handle(socket));
            }
        } catch (Exception ignored) {
        } finally {
            stopSelf();
        }
    }

    private void handle(Socket socket) {
        try (Socket s = socket; InputStream in = s.getInputStream(); OutputStream out = s.getOutputStream()) {
            s.setSoTimeout(15000);
            String requestLine = readLine(in);
            if (requestLine == null || requestLine.isEmpty()) return;
            String[] parts = requestLine.split(" ");
            if (parts.length < 2) { sendJson(out, 400, json(false, "Requête invalide")); return; }
            String method = parts[0].toUpperCase(Locale.ROOT);
            String path = parts[1];
            Map<String,String> headers = new HashMap<>();
            while (true) {
                String line = readLine(in);
                if (line == null || line.isEmpty()) break;
                int p = line.indexOf(':');
                if (p > 0) headers.put(line.substring(0,p).trim().toLowerCase(Locale.ROOT), line.substring(p+1).trim());
            }
            String expected = getSharedPreferences("fewura_sms", MODE_PRIVATE).getString("token", "");
            String auth = headers.getOrDefault("authorization", "");
            if (expected.isEmpty() || !auth.equals("Bearer " + expected)) {
                sendJson(out, 401, json(false, "Jeton invalide"));
                return;
            }
            if ("GET".equals(method) && "/health".equals(path)) {
                JSONObject data = new JSONObject();
                data.put("ok", true);
                data.put("app", "FEWURA SMS Gateway");
                data.put("sender", "+33773547857");
                data.put("ip", MainActivity.localIp());
                sendJson(out, 200, data);
                return;
            }
            if ("POST".equals(method) && "/sms".equals(path)) {
                if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
                    sendJson(out, 403, json(false, "Permission SEND_SMS non accordée"));
                    return;
                }
                int len = 0;
                try { len = Integer.parseInt(headers.getOrDefault("content-length", "0")); } catch (Exception ignored) { }
                if (len <= 0 || len > 20000) { sendJson(out, 400, json(false, "Corps JSON invalide")); return; }
                byte[] body = readBytes(in, len);
                JSONObject req = new JSONObject(new String(body, StandardCharsets.UTF_8));
                String to = req.optString("to", "").trim();
                String message = req.optString("message", "").trim();
                if (!to.matches("^\\+[1-9][0-9]{7,14}$")) { sendJson(out, 400, json(false, "Numéro destinataire invalide")); return; }
                if (message.isEmpty()) { sendJson(out, 400, json(false, "Message vide")); return; }
                if (message.length() > 2000) { sendJson(out, 400, json(false, "Message trop long")); return; }
                SmsManager sms = SmsManager.getDefault();
                ArrayList<String> partsSms = sms.divideMessage(message);
                sms.sendMultipartTextMessage(to, null, partsSms, null, null);
                JSONObject ok = new JSONObject();
                ok.put("ok", true);
                ok.put("to", to);
                ok.put("parts", partsSms.size());
                sendJson(out, 200, ok);
                return;
            }
            sendJson(out, 404, json(false, "Route inconnue"));
        } catch (Exception ignored) {
        }
    }

    private static String readLine(InputStream in) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        int prev = -1;
        while (true) {
            int c = in.read();
            if (c == -1) break;
            if (prev == '\r' && c == '\n') break;
            if (prev != -1) b.write(prev);
            prev = c;
            if (b.size() > 8192) throw new IllegalArgumentException("En-tête trop long");
        }
        return b.toString(StandardCharsets.UTF_8.name());
    }

    private static byte[] readBytes(InputStream in, int len) throws Exception {
        byte[] data = new byte[len];
        int off = 0;
        while (off < len) {
            int n = in.read(data, off, len - off);
            if (n < 0) throw new IllegalArgumentException("Corps incomplet");
            off += n;
        }
        return data;
    }

    private static JSONObject json(boolean ok, String error) throws Exception {
        JSONObject o = new JSONObject();
        o.put("ok", ok);
        if (!ok) o.put("error", error);
        return o;
    }

    private static void sendJson(OutputStream out, int code, JSONObject data) throws Exception {
        byte[] body = data.toString().getBytes(StandardCharsets.UTF_8);
        String status = code == 200 ? "OK" : code == 400 ? "Bad Request" : code == 401 ? "Unauthorized" : code == 403 ? "Forbidden" : "Not Found";
        String head = "HTTP/1.1 " + code + " " + status + "\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: " + body.length + "\r\nConnection: close\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.UTF_8));
        out.write(body);
        out.flush();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "FEWURA SMS Gateway", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
    }

    private Notification notification() {
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        return b.setContentTitle("FEWURA SMS Gateway")
                .setContentText("Passerelle active sur le port 8765")
                .setSmallIcon(android.R.drawable.sym_action_email)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    @Override
    public void onDestroy() {
        running = false;
        try { if (serverSocket != null) serverSocket.close(); } catch (Exception ignored) { }
        if (workers != null) workers.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
