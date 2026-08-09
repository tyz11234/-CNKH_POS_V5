# CNKH Hardware POS V5.0

全新开发的 Windows 离线 POS + Inventory 系统。V5 使用 **Python 3.12、PySide6 / Qt 6 与 SQLite**，不会覆盖或修改 V4 源代码。

> 当前状态：正式开发与 Release Gate 验证中。未通过 Windows UI / EXE / Installer 全部验收前不会标记为正式发布。

## 安全原则

- 默认数据库：`%LOCALAPPDATA%\CNKH Hardware POS\Data\hardware_pos.db`
- 已存在数据库启动顺序：`integrity_check → SQLite online backup → 单一事务 migration → 正常开放写入`
- migration 失败会 rollback 并阻止应用进入可写状态，原数据库与启动前备份都会保留。
- 金额一律使用 integer cents/sen；数量使用十进制定点文字表示，避免二进制浮点误差。
- V5 不删除 `hardware_pos.db`，也不包含 MyInvois、云端同步或多电脑服务器功能。

## 开发启动

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-build.txt
python admin_launcher.py
python staff_launcher.py
```

仅运行当前数据库/服务测试（不要求 PySide6）：

```powershell
python -m unittest discover -s tests -v
python tools/source_self_test.py
```

## 目录

- `cnkh_pos/database`：连接、schema、事务 migration、安全 bootstrap
- `cnkh_pos/services`：备份、收据编号、搜索、错误日志等领域服务
- `cnkh_pos/ui`：Admin、Staff、dialogs、复用 widgets 与 Design System
- `resources`：QSS、SVG、Qt Resource Collection
- `tests`：fresh/legacy database 与关键服务测试
- `installer`：Inno Setup 脚本
- `.github/workflows`：Windows release gate
- `docs`：架构、迁移和 UI 规范

## 发布门禁

正式发布必须通过数据库迁移、交易原子性、付款、库存、备份恢复、Admin/Staff GUI、鼠标滚轮、三档 DPI、packaged EXE self-test 与 Installer 构建。任何关键测试失败时 workflow 会停止，不会产出正式 Installer。

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/MIGRATIONS.md](docs/MIGRATIONS.md) 与 [docs/UI_DESIGN_SYSTEM.md](docs/UI_DESIGN_SYSTEM.md)。
