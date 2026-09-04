# 黄金发宝号 · 手机收银（Android APK）

Flutter 手机端，与桌面 **[CNKH_POS_Desktop](https://github.com/tyz11234/CNKH_POS_Desktop)** 功能对齐。

| | |
|--|--|
| 店名 | **黄金发宝号** |
| 包名 | `cnkh_pos_mobile` |
| 版本 | **1.7.2** |
| APK 发布 | https://github.com/tyz11234/CNKH_POS_Mobile_APK/releases |
| PC 桌面 | https://github.com/tyz11234/CNKH_POS_Desktop |

> 旧 PySide 仓库 `-CNKH_POS_V5` 已停用，请改用上面的新桌面版。

---

## 下载安装

1. 打开 [Releases](https://github.com/tyz11234/CNKH_POS_Mobile_APK/releases)
2. 下载最新 `CNKH_POS_Mobile.apk`（或 `CNKH_POS_Mobile_v1.7.2.apk`）
3. 允许未知来源 → 安装 → 打开

种子账号（首次自动写入）：`admin` / `staff` / `staff2`，演示 **PIN 任意**。

---

## 电子收据 / WhatsApp

- PDF 使用 **Noto Sans SC** 字体，中文不乱码
- 点发送电子收据 → **直接打开 WhatsApp 并附加 PDF**（需已安装 WhatsApp）
- PDF 缓存约 7 天，可在设置清理

---

## 主要功能

- 收银、扫码、挂单、结账（现金/卡/DuitNow/赊账）
- 今日 / 销售记录 → 点进**小票详情**
- 设置 → **小票格式**编辑 + 实时预览
- 商品：**进货价** + **售价**
- 进货：供货商、扫码进货、扫/拍进货单识别（已有商品入库 / 新建商品）
- 报表：销售额、成本、毛利、毛利率
- 局域网配对（`cnkh-sync`，与桌面客户端协议兼容）

---

## 本地打 APK

```bash
cd mobile   # 或本仓库路径
flutter pub get
flutter build apk --release
# build/app/outputs/flutter-apk/app-release.apk
```

---

## 版本

| 版本 | 说明 |
|------|------|
| **1.7.2** | 中文 PDF 字体；直开 WhatsApp 发 PDF |
| 1.7.0 | 扫码/单据进货、进货价售价、报表毛利 |
| 1.6.0 | 小票模板 + 销售小票详情 |
