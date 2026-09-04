# CNKH — Scan, E-receipt PDF, LAN Sync

## 1) Mobile camera barcode / QR scan

- **收银 / POS** → **扫码加购 / Scan barcode** (full-screen `mobile_scanner`).
- Lookup by barcode/sku → +1 qty, continuous scan, 「未找到商品」 on miss.
- Linux/Windows desktop: 「此设备无摄像头 / 请用手机」 (no crash).

## 2) E-receipt = **print-layout PDF** via WhatsApp

### Layout

Uses the **same receipt body as PC thermal/print**:
- PC: `PrintingService.render_text` / `render_pdf` (80mm ReportLab).
- Mobile: 40-col text mirrored in `buildPrintReceiptText` → `pdf` package.

### Send flow

1. Resolve customer phone (sale / dialog).
2. Write PDF under **system temp only** (never Documents/Downloads/Pictures).
3. Share:
   - **Mobile:** `share_plus` `Share.shareXFiles` + short `wa.me` caption.
   - **PC:** open temp PDF + `wa.me` caption (attach PDF in WhatsApp Desktop/Web; `wa.me` cannot attach files).
4. **`finally` deletes** the temp PDF (and temp dir on PC).

Optional short caption: store name + receipt no + “see attached PDF”.

### UI

- Mobile: checkout success sheet + sales list WhatsApp/PDF action; AppBar **扫码配对** separate.
- PC: Sale completed **电子收据 / WhatsApp** + Admin sales toolbar.

## 3) LAN sync + QR pairing

See **[LAN_SYNC.md](./LAN_SYNC.md)**.

- **PC top bar / Admin sidebar:** **同步/配对** → pairing QR dialog.
- **Mobile AppBar:** **扫码配对** (next to Admin|Staff badge) → scan QR → WebSocket + poll.
- Pairing payload: `cnkh-sync:v1|{"baseUrl":"http://IP:PORT","token":"...","name":"CNKH-PC"}`

## Known limits

- WhatsApp cannot auto-attach via `wa.me`; mobile uses share sheet; PC opens PDF for manual attach.
- Linux demo: no camera; share may open browser; contacts skip.
- No APK packaging in this sprint.

## Tests

- `flutter test` (e_receipt + money/credit)
- `pytest tests/test_e_receipt.py tests/test_lan_sync_server.py`


## Mobile v1.3 ops
- Scan feedback: beep / vibrate / mute (Settings)
- Cash change big dialog after CASH
- Credit customer outstanding red banner
- Training page: 配对 → 扫码 → 发收据
