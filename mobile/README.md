# CNKH POS Mobile / CNKH 手机收银助手

Phone-first Flutter companion for **CNKH Hardware POS V5** (offline desktop SQLite).

手机端 Flutter 配套应用，配合 **CNKH Hardware POS V5** 离线桌面收银使用。

## Version

**1.2.0** — local-first full PC feature port (SQLite). See `/workspace/cnkh-v5/MOBILE_FULL_PORT_NOTES.md`.

## Features / 功能

| Screen | 中文 | Notes |
|--------|------|-------|
| Login | 员工登录 | Demo stub — any PIN |
| POS Cart | 收银台 | Sample hardware SKUs, large taps |
| Checkout | 结账 | Cash / Card / **DuitNow QR** (full-screen QR) |
| Settings | 设置 | Import DuitNow QR (Admin) / view (Staff); store name |
| Today | 今日销售 | Local SQLite sales list |
| Admin | 管理 | Dashboard, products, entities, purchases, stocktake, reports, closing, maintenance |

- Branding matches desktop navy / `#102E64` / `#1769E0`
- QR is **device-local** for demo; Admin sync from desktop is TBD
- Does **not** talk to desktop SQLite (no API server yet)

## Install APK (Android) / 安装安卓包

1. Copy `CNKH_POS_Mobile.apk` to the phone (USB, Drive, chat, etc.).
2. On phone: allow **Install unknown apps** for that source.
3. Open the APK → Install → Open **CNKH POS Mobile**.
4. Sign in with any username + PIN (demo).
5. Open **设置 Settings** → import your DuitNow QR image from gallery.
6. Add items → **结账 Checkout** → choose **DuitNow QR** → show full-screen QR to customer.

正式 APK 产物路径（构建后）：

- `mobile/build/app/outputs/flutter-apk/app-release.apk`
- 复制件：`/workspace/cnkh-v5/artifacts/CNKH_POS_Mobile.apk`

### Build locally / 本地构建

```bash
export JAVA_HOME=... ANDROID_HOME=...
cd mobile
flutter pub get
flutter build apk --release
flutter build appbundle --release   # optional Play Store AAB
```

## IPA (iOS) / 苹果安装包

**Linux cannot produce a signed IPA.** Options:

1. **macOS + Xcode** (Apple Developer account required for device install / TestFlight):

```bash
cd mobile
flutter build ipa   # requires signing team in Xcode
# or unsigned compile check:
flutter build ios --no-codesign
```

2. **GitHub Actions** — see `.github/workflows/mobile-ios.yml` (needs Apple certs/secrets).

Without Apple Developer signing, IPA cannot be installed on a physical iPhone.

没有 Apple 开发者签名时，无法在真机安装 IPA。

## Project layout / 目录

```
mobile/
  lib/
    main.dart
    theme/cnkh_theme.dart
    screens/   # login, cart, checkout, settings
    widgets/   # money, DuitNow QR
    services/  # device-local QR storage
  android/ ios/
```

## License / 说明

Companion demo for CNKH Hardware store use. Desktop POS remains system of record.
