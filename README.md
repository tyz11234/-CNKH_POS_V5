# CNKH Hardware POS V5.0

Windows 离线 POS + Inventory 系统。V5 使用 **Python 3.12、PySide6 / Qt 6 与 SQLite**，不会覆盖或修改 V4 源代码。

> 当前状态：`5.0.0-alpha.4 / Run #8 Completion Source Candidate`。本地服务测试、源码自检、Python 编译和关键静态检查已经完成；当前 Linux 环境缺少 `libEGL.so.1`，因此 100%/125%/150% Windows GUI、EXE、Setup 和安装后自检仍必须在真实 Windows runner 通过后，才能称为 Windows 可安装候选版。

## Run #8 主要完成内容

- Admin 员工账号新增、编辑权限、重设密码、启用/停用和最后管理员保护。
- 客户/供应商手机号、Email（供应商）、备注、编辑、安全删除和付款备注/方式。
- 供应商商品多对多目录；新建进货只显示并只允许保存该供应商商品。
- 重复进货行合并、删除进货负库存保护、付款历史 void 保留。
- Staff 商品真实分页、折扣/快捷金额/重印权限、挂单按收银员隔离。
- 折扣后净额退货、Credit 欠款调整、日期报表与精确毛利、完整现金日结。
- 明确打印机选择、离线错误、80mm 测试 PDF、收据内容与自定义单号前缀。
- Audit Log 管理员密码保护清除、清除前备份、独立系统检查记录。
- 关闭 Admin/Staff 自动备份，同一次关闭流程只建立一份并保留最近 30 份。

## 店铺电脑下载安装（Windows 门禁通过后，不需要 Python）

1. 在仓库打开 **Actions → Windows Release Gate**。
2. 选择最新一项全部绿色的运行记录。
3. 在页面底部下载 Artifact：`CNKH-Hardware-POS-V5-Windows`。
4. 解压后运行 `CNKH_Hardware_POS_V5_Setup.exe`。
5. 第一次必须启动 **CNKH POS Admin**，建立首个管理员；之后才可登录 Staff。

不要从失败或尚在运行的 Actions 记录下载安装包。详细步骤见 [GitHub 构建与下载说明](docs/GITHUB_BUILD_AND_DOWNLOAD_CN.md)。

## 安全原则

- 默认数据库：`%LOCALAPPDATA%\CNKH Hardware POS\Data\hardware_pos.db`
- 备份：`%LOCALAPPDATA%\CNKH Hardware POS\Backups`
- 日志：`%LOCALAPPDATA%\CNKH Hardware POS\Logs`
- 导出：`%LOCALAPPDATA%\CNKH Hardware POS\Exports`
- 收据：`%LOCALAPPDATA%\CNKH Hardware POS\Receipts`
- 已存在且需要升级的数据库启动顺序：`integrity_check → SQLite online backup → 单一事务 migration → 正常开放写入`
- 已经是最新 schema 的数据库不会在每次启动重复建立 pre-migration 备份。
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
- `cnkh_pos/services`：销售、进货、客户/供应商、备份、打印、报表与维护服务
- `cnkh_pos/ui`：Admin、Staff、dialogs、复用 widgets 与 Design System
- `resources`：QSS、SVG、Qt Resource Collection
- `tests`：fresh/legacy database 与关键服务测试
- `installer`：Inno Setup 脚本
- `build`：必须提交到 GitHub 的 Admin / Staff PyInstaller spec
- `.github/workflows`：Windows release gate
- `docs`：架构、迁移和 UI 规范

## 发布门禁

Windows 可安装候选版必须通过数据库迁移、交易原子性、付款、库存、备份恢复、Admin/Staff GUI、真实鼠标操作、鼠标滚轮、100%/125%/150% DPI、两个 packaged EXE self-test、Setup 静默安装及安装后两个 self-test。任何关键步骤失败时 workflow 会停止，不会上传安装 Artifact。

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/MIGRATIONS.md](docs/MIGRATIONS.md) 与 [docs/UI_DESIGN_SYSTEM.md](docs/UI_DESIGN_SYSTEM.md)。
