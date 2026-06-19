package org.tishou.service;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * TiShou 后台保活服务（前台服务）
 * ==============================
 * Android 14+ 要求前台服务必须声明 foregroundServiceType。
 * 本服务通过 startForeground() 将应用提升为前台进程，防止被系统回收。
 *
 * 使用方式：
 *   1. Python 侧通过 pyjnius 启动：
 *        Intent intent = new Intent(context, KeepAliveService.class)
 *        context.startForegroundService(intent)
 *   2. 停止：context.stopService(intent)
 */
public class KeepAliveService extends Service {

    private static final String CHANNEL_ID = "tishou_keepalive";
    private static final String CHANNEL_NAME = "后台保活";
    private static final int NOTIFICATION_ID = 1002;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification notification = buildNotification();
        if (notification != null) {
            startForeground(NOTIFICATION_ID, notification);
        }
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        stopForeground(true);
        super.onDestroy();
    }

    // ================================================================
    // 通知渠道
    // ================================================================

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager == null) return;

            NotificationChannel channel = manager.getNotificationChannel(CHANNEL_ID);
            if (channel == null) {
                channel = new NotificationChannel(
                    CHANNEL_ID,
                    CHANNEL_NAME,
                    NotificationManager.IMPORTANCE_LOW
                );
                channel.setDescription("TiShou 后台运行中");
                channel.setShowBadge(false);
                manager.createNotificationChannel(channel);
            }
        }
    }

    // ================================================================
    // 常驻通知
    // ================================================================

    private Notification buildNotification() {
        try {
            Intent launchIntent = getPackageManager()
                .getLaunchIntentForPackage(getPackageName());
            PendingIntent pendingIntent = null;
            if (launchIntent != null) {
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    flags |= PendingIntent.FLAG_IMMUTABLE;
                }
                pendingIntent = PendingIntent.getActivity(
                    this, 0, launchIntent, flags
                );
            }

            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                builder = new Notification.Builder(this, CHANNEL_ID);
            } else {
                builder = new Notification.Builder(this);
            }

            builder.setContentTitle("TiShou")
                   .setContentText("后台运行中，自动抢单已就绪")
                   .setSmallIcon(android.R.drawable.ic_menu_manage)
                   .setOngoing(true)
                   .setPriority(Notification.PRIORITY_LOW);

            if (pendingIntent != null) {
                builder.setContentIntent(pendingIntent);
            }

            return builder.build();
        } catch (Exception e) {
            return null;
        }
    }
}