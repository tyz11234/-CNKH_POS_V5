# Version History

## 5.0.0-alpha.4 — 2026-08-10

### Continued (2026-09-04)

- Admin Receipt Settings：付款 QR 图片上传 / 替换 / 清除，并在 80mm PDF 收据页脚居中打印。
- 结账选择 DUITNOW_QR（及 Credit 定金 DUITNOW_QR）时，桌面结账对话框大图展示店内 DuitNow 收款码（有图则显示，无图则提示；上传仍仅限 Admin 收据设置）。
- Credit 结账定金可选择 CASH / CARD / DUITNOW_QR；日结仅把 CASH（及旧 NULL）定金计入系统现金。
- 备份 / 还原失败提示改为中英双语，明确文件保留与数据库未被替换。
- Schema 8：`sales.deposit_method`。

### New

- Admin 可视化账号管理与 Staff 三项权限门禁。
- 客户/供应商完整资料、安全删除和带付款方式/备注的收付款。
- `supplier_products` 多对多供应商商品目录，进货 UI 与服务层双重过滤。
- 商品真实分页、编辑、Excel 导入入口、分类管理和库存编辑 movement。
- 销售退货页面、退款方式、Credit 欠款调整、挂单选择与收银员隔离。
- 指定打印机/Windows 默认打印机选择、离线错误、80mm 测试输出。
- 日期范围报表、精确折扣后毛利、开档现金与完整现金流日结。
- Audit Log 密码保护清除、清除前备份与独立 `system_checks` 记录。
- 收据、进货、退货和盘点单号前缀设置。
- Admin/Staff 正常关闭自动备份及 30 份保留门禁。

### Fixed

- Staff 购物车行金额、折扣上限与 Admin 金额输入统一使用整数 sen + `ROUND_HALF_UP`，数量下降后折扣会重新夹紧到当前行金额。
- 新建进货行的 Product ID/Name 保持只读，数量/成本可编辑，并保留逐行删除入口与保存校验。
- 数据库启动校验会拒绝“user_version 正确但必需表/列缺失”以及外键损坏的数据库。
- 新备份完成后必须通过 SQLite `PRAGMA integrity_check`，失败的目标备份会被删除。
- Windows windowed EXE self-test gate 除真实进程退出码外，现在还强制要求 JSON 报告存在且 `status=PASS`、mode 匹配。
- 供应商目录不再只靠 UI 过滤，服务层会拒绝不属于该供应商的商品。
- 重复进货商品会合并数量，删除进货不会令库存变成负数。
- 折扣销售退货按原行净额退款，最后一次退货消除四舍五入差额。
- 报表不再因 sale items join 重复累计销售总额，毛利不再使用浮点数量。
- 最新 schema 重启不会不断产生 `pre_migration` 备份。
- 未选择打印机、默认打印机不存在、指定打印机被移除时会明确阻止打印。
- 恢复挂单只保留非零折扣，并在验证 payload 后才标记为已恢复。

### Migration

- Database schema version: 8
- 新增 `supplier_products`、`daily_cash_closings.opening_cash_cents`、`sale_returns.refund_method`、`sales.deposit_method`。

## 5.0.0-alpha.3 — 2026-08-09

### Fixed

- 挂单恢复时不再为无折扣商品加入 `0` 值折扣记录。
- 挂单恢复现在通过经测试的标准化函数同时还原数量与折扣资料。
- 新增多商品挂单测试，验证恢复前后的稀疏折扣资料完全一致。

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
