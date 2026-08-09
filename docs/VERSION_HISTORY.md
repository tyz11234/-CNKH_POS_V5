# Version History

## 5.0.0-alpha.2 — 2026-08-09

### Fixed

- 购物车 `+/−` 按钮现在直接以购物车数据中的当前数量加减，不再依赖会在列表重建时失效的旧 SpinBox。
- Windows GUI Acceptance 现在依商品 ID 重新定位购物车数量控件，并同时核对 UI 数值与购物车数据。
- `+/−` 验收不再依赖 Qt `findChildren()` 的按钮返回顺序。

## 5.0.0-alpha.1 — 2026-08-09

### New

- 全新 V5 模块化项目骨架（PySide6 / Qt 6）。
- 数据库 integrity、启动备份、事务 migration gate。
- 四种 legacy `supplier_payments` 金额列兼容。
- Admin Dashboard 与 Staff POS 视觉骨架。
- Qt QSS Design System、SVG icons、resource collection。

### Migration

- Database schema version: 6

### Run #5 candidate fixes

- Staff 商品搜索、加入购物车和 Credit Sale 客户选择已接入真实操作。
- Dashboard、Receipt Test Print 与 Reports Excel Export 已接入真实数据/输出。
- Windows GUI Acceptance 扩展为真实鼠标流程和 100%/125%/150% DPI 验收。
- GitHub Artifact 同时包含 Admin EXE、Staff EXE、Setup.exe、SHA-256 manifest 与 UI 截图证据。
