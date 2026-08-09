# CNKH Hardware POS V5.0

[![Windows Release Gate](https://github.com/tyz11234/-CNKH_POS_V5/actions/workflows/windows-release.yml/badge.svg)](https://github.com/tyz11234/-CNKH_POS_V5/actions/workflows/windows-release.yml)

Windows 离线 POS + Inventory 系统。V5 使用 **Python 3.12、PySide6 / Qt 6 与 SQLite**，不会覆盖或修改 V4 源代码。

> 当前状态：Run #6 购物车数量控件修正候选版。已修正 Run #5 在 100% DPI 鼠标验收中的 `+/−` 控件重建定位问题，并让数量按钮直接修改购物车的权威数据。只有 Windows Release Gate 的自动测试、三档 DPI UI 验收、两个 EXE 自检和 Installer 构建全部通过，才可把对应 Artifact 当成可安装候选版。

## 店铺电脑下载安装（不需要 Python）

1. 在仓库打开 **Actions → Windows Release Gate**。
2. 选择最新一项全部绿色的运行记录。
3. 在页面底部下载 Artifact：`CNKH-Hardware-POS-V5-Windows`。
4. 解压后运行 `CNKH_Hardware_POS_V5_Setup.exe`。
5. 第一次必须启动 **CNKH POS Admin**，建立首个管理员；之后才可登录 Staff。

不要从失败或尚在运行的 Actions 记录下载安装包。详细步骤见 [GitHub 构建与下载说明](docs/GITHUB_BUILD_AND_DOWNLOAD_CN.md)。

## 安全原则

- 默认数据库：`%LOCALAPPDATA%\CNKH Hardware POS\Data\hardware_pos.db`
- 已存在数据库启动顺序：`integrity_check → SQLite online backup → 单一事务 migration → 正常开放写入`
- migration 失败会 rollback 并阻止应用进入可写状态，原数据库与启动前备份都会保留。
- 金额一律使用 integer cents/sen；数量使用十进制定点文字表示，避免二进制浮点误差。
- V5 不删除 `hardware_pos.db`，也不包含 MyInvois、云端同步或多电脑服务器功能。

## 开发人员启动

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-build.txt
python admin_launcher.py
python staff_launcher.py
```

运行测试与源码自检：

```powershell
pytest -q
python tools/source_self_test.py
```

## 目录

- `cnkh_pos/database`：连接、schema、事务 migration、安全 bootstrap
- `cnkh_pos/services`：备份、收据编号、搜索、错误日志等领域服务
- `cnkh_pos/ui`：Admin、Staff、dialogs、复用 widgets 与 Design System
- `resources`：QSS、SVG、Qt Resource Collection
- `tests`：fresh/legacy database 与关键服务测试
- `installer`：Inno Setup 脚本
- `build`：必须提交到 GitHub 的 Admin / Staff PyInstaller spec
- `.github/workflows`：Windows release gate
- `docs`：架构、迁移和 UI 规范

## 发布门禁

正式发布必须通过数据库迁移、交易原子性、付款、库存、备份恢复、Admin/Staff GUI、真实鼠标操作、鼠标滚轮、100%/125%/150% DPI、packaged EXE self-test 与 Installer 构建。任何关键测试失败时 workflow 会停止，不会上传安装 Artifact。

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/MIGRATIONS.md](docs/MIGRATIONS.md) 与 [docs/UI_DESIGN_SYSTEM.md](docs/UI_DESIGN_SYSTEM.md)。
