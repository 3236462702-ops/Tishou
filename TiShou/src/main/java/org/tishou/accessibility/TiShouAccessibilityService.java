package org.tishou.accessibility;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.ArrayList;
import java.util.List;

/**
 * TiShou 无障碍服务 —— 主力订单识别引擎
 * ==========================================
 * 通过 Android 系统级 AccessibilityService 直接获取屏幕文本信息，
 * 无需截图 → OCR 流程，速度更快、准确率更高。
 *
 * 使用方式：
 *   1. APK 安装后，用户在「设置 → 无障碍 → TiShou」中手动开启
 *   2. Python 侧通过 pyjnius 调用静态方法：
 *        TiShouAccessibilityService.isAvailable()    → 检查服务是否运行
 *        TiShouAccessibilityService.getInstance()    → 获取单例
 *        instance.extractAllTexts()                  → 提取全部文本
 *        instance.getRootNode()                      → 获取根节点
 */
public class TiShouAccessibilityService extends AccessibilityService {

    private static volatile TiShouAccessibilityService sInstance;

    // ================================================================
    // 生命周期
    // ================================================================

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        sInstance = this;

        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPES_ALL_MASK;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.flags = AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
                   | AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
                   | AccessibilityServiceInfo.FLAG_REQUEST_ENHANCED_WEB_ACCESSIBILITY
                   | AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                   | AccessibilityServiceInfo.FLAG_REQUEST_2_PASS_PAINT;
        info.notificationTimeout = 100;
        setServiceInfo(info);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Python 侧通过轮询 extractAllTexts() 主动拉取数据，不需要处理事件
    }

    @Override
    public void onInterrupt() {
        sInstance = null;
    }

    @Override
    public void onDestroy() {
        sInstance = null;
        super.onDestroy();
    }

    // ================================================================
    // Python 调用接口（通过 pyjnius）
    // ================================================================

    public static TiShouAccessibilityService getInstance() {
        return sInstance;
    }

    public static boolean isAvailable() {
        return sInstance != null;
    }

    public AccessibilityNodeInfo getRootNode() {
        return getRootInActiveWindow();
    }

    public List<String> extractAllTexts() {
        List<String> texts = new ArrayList<>();
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root != null) {
            try {
                extractTextsRecursive(root, texts);
            } finally {
                root.recycle();
            }
        }
        return texts;
    }

    // ================================================================
    // 内部递归提取
    // ================================================================

    private void extractTextsRecursive(AccessibilityNodeInfo node, List<String> texts) {
        if (node == null) return;

        CharSequence text = node.getText();
        if (text != null && text.length() > 0) {
            texts.add(text.toString());
        }

        CharSequence desc = node.getContentDescription();
        if (desc != null && desc.length() > 0) {
            texts.add(desc.toString());
        }

        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                extractTextsRecursive(child, texts);
                child.recycle();
            }
        }
    }
}