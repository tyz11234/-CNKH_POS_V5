# CNKH POS — NEXT batch notes (1.4.0+14)

**Date:** 2026-09-04 (Asia/Kuala_Lumpur)  
**Mobile path:** `/workspace/cnkh-v5/mobile`  
**PC path:** `/workspace/cnkh-v5/repo` (branch `feat/mobile-sync-ereceipt-scan`)

## Shipped

### A) Continuous barcode scan (mobile)
- POS「扫码加购」stays open; each hit adds qty+1 with debounce (~1.6s).
- Leave only via **完成 Done / Close**, or camera/permission failure → **手动搜索加购**.
- Pairing QR (`cnkh-sync:…`) still distinguished from product barcodes.

### B) Optional Bluetooth thermal printer
- Settings toggle `bt_printer_enabled` (default **off**).
- Checkout success: auto-try if enabled + manual「蓝牙打印」; **never blocks** checkout (snackbar only).
- Package: `print_bluetooth_thermal` (Android). Linux/desktop: graceful degrade.
- PC Receipt Settings notes that mobile BT is separate from Windows/USB printers.

### C) Low-stock push over LAN
- PC publishes `low_stock` via EventHub after sales (and after phone sale import).
- Threshold: product `low_stock_decimal` / mobile `reorder_level`, else setting `low_stock_threshold` (default 10).
- Mobile WS handler → snackbar/banner; Admin action jumps to Admin tab.
- Exposed in mobile + PC settings.

### D) Product images (Admin opt-in)
- Setting `product_images_enabled` (default off). When on: Admin pick/upload; POS thumbnails.
- LAN: `GET/POST /api/v1/product_images/:id` (base64). Prefer pull when catalog flags `has_image`.

### E) Categories = PC parity
- Mobile `categories` table (DB v5+); Admin **分类管理** CRUD.
- Product add/edit: **picker only** (no free typing).
- POS filter chips: **全部** + each category; search respects filter.
- Sync: `GET/POST /api/v1/categories`.

### Barcode generate / export / print queue
- Product add: **自动生成** EAN-13 **或** **手动输入**.
- Single + **batch multi-select**:
  1. **加入打印队列** → sync to PC `barcode_print_queue.json` via `/api/v1/barcode_queue`
  2. **批量导出条码图片** → PNG with bars + code + **full product name underneath**; share sheet / `barcode_exports/`
- PC Barcode Labels: **加载手机打印队列**; hardware print remains PC-only.

### F) Version
- Mobile `1.4.0+14`

## Limits
- BT printer: Android bonded ESC/POS only; no Linux desktop BT.
- Product image sync sends base64 over LAN — keep images modest (&lt; ~2.5MB server cap).
- Barcode PNG uses Flutter canvas (CJK OK); share-to-gallery depends on OS share targets.
- Phone queue on PC is a JSON merge helper — operator still selects rows and prints on label hardware.
- True PC-only: Windows barcode label **hardware** dialog, Windows backup/restore binary.

## Tests / release
- `flutter test` / `flutter analyze`
- `ruff` on touched PC files
- APK → `tyz11234/CNKH_POS_Mobile_APK`
- PC push → `tyz11234/-CNKH_POS_V5` PR #19 branch
