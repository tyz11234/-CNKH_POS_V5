import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../models/product.dart';
import '../services/lan_sync.dart';
import '../services/pos_repository.dart';
import '../services/scan_feedback.dart';
import '../theme/cnkh_theme.dart';

/// Full-screen scanner.
/// - Product barcode/sku → [onProduct]
/// - Pairing QR (`cnkh-sync:…`) → [onPairing] if provided, else pop with config via [onPairingRaw]
class BarcodeScanScreen extends StatefulWidget {
  final PosRepository repo;
  final void Function(Product product)? onProduct;
  final void Function(LanSyncConfig config)? onPairing;
  final bool pairingOnly;

  const BarcodeScanScreen({
    super.key,
    required this.repo,
    this.onProduct,
    this.onPairing,
    this.pairingOnly = false,
  });

  @override
  State<BarcodeScanScreen> createState() => _BarcodeScanScreenState();
}

class _BarcodeScanScreenState extends State<BarcodeScanScreen> {
  MobileScannerController? _controller;
  bool _unsupported = false;
  bool _handling = false;
  String? _lastCode;
  DateTime _lastAt = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  void initState() {
    super.initState();
    if (_isUnsupportedPlatform) {
      _unsupported = true;
      return;
    }
    try {
      _controller = MobileScannerController(
        detectionSpeed: DetectionSpeed.normal,
        facing: CameraFacing.back,
        formats: const [
          BarcodeFormat.ean13,
          BarcodeFormat.ean8,
          BarcodeFormat.code128,
          BarcodeFormat.code39,
          BarcodeFormat.qrCode,
          BarcodeFormat.upcA,
          BarcodeFormat.upcE,
        ],
      );
    } catch (_) {
      _unsupported = true;
    }
  }

  bool get _isUnsupportedPlatform {
    if (kIsWeb) return true;
    try {
      return Platform.isLinux || Platform.isWindows;
    } catch (_) {
      return true;
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_handling || !mounted) return;
    final raw = capture.barcodes
        .map((b) => b.rawValue?.trim() ?? '')
        .firstWhere((s) => s.isNotEmpty, orElse: () => '');
    if (raw.isEmpty) return;
    final now = DateTime.now();
    if (raw == _lastCode && now.difference(_lastAt) < const Duration(seconds: 2)) {
      return;
    }
    _handling = true;
    _lastCode = raw;
    _lastAt = now;
    try {
      // Dual-mode: pairing QR takes priority
      if (looksLikePairingPayload(raw)) {
        LanSyncConfig? cfg;
        try {
          cfg = parsePairingQr(raw);
        } on PairingExpiredException catch (e) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('$e'), backgroundColor: CnkhColors.danger),
            );
          }
          return;
        }
        if (cfg != null) {
          if (widget.onPairing != null) {
            widget.onPairing!(cfg);
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('配对码已识别 ${cfg.name}'),
                  backgroundColor: CnkhColors.success,
                ),
              );
            }
          } else {
            if (mounted) Navigator.of(context).pop(cfg);
          }
          return;
        }
      }

      if (widget.pairingOnly) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('请扫描电脑配对二维码 / Scan PC pairing QR'),
              backgroundColor: CnkhColors.danger,
            ),
          );
        }
        return;
      }

      if (widget.onProduct == null) return;
      final product = await widget.repo.findByBarcodeOrSku(raw);
      if (!mounted) return;
      if (product == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('未找到商品 / Product not found'),
            backgroundColor: CnkhColors.danger,
            duration: Duration(milliseconds: 1200),
          ),
        );
      } else {
        widget.onProduct!(product);
        await playScanFeedback(widget.repo);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('已加入 ${product.nameZh}'),
            backgroundColor: CnkhColors.success,
            duration: const Duration(milliseconds: 900),
          ),
        );
      }
    } finally {
      _handling = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.pairingOnly ? '扫码配对 / Pair' : '扫码 / Scan';
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: Text(title),
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
      ),
      body: _unsupported || _controller == null
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  '此设备无摄像头 / 请用手机\n\nNo camera on this device — use a phone.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white, fontSize: 18, height: 1.4),
                ),
              ),
            )
          : Stack(
              fit: StackFit.expand,
              children: [
                MobileScanner(
                  controller: _controller!,
                  onDetect: _onDetect,
                  errorBuilder: (context, error) {
                    return Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(
                          '此设备无摄像头 / 请用手机\n($error)',
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Colors.white, fontSize: 16),
                        ),
                      ),
                    );
                  },
                ),
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Container(
                    width: double.infinity,
                    color: Colors.black54,
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                    child: Text(
                      widget.pairingOnly
                          ? '对准电脑「同步/配对」二维码'
                          : '商品条码加购 · 或扫描 cnkh-sync 配对码',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white70, fontSize: 13),
                    ),
                  ),
                ),
              ],
            ),
    );
  }
}
