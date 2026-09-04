# 黄金发宝号 · CNKH Hardware POS V5

Windows **离线收银 + 库存**（Python 3.12 / PySide6 / SQLite）。可与手机端 [CNKH_POS_Mobile_APK](https://github.com/tyz11234/CNKH_POS_Mobile_APK) 在同一局域网配对同步，**不走云**。

店铺对外店名：**黄金发宝号**（软件内部工程名仍为 CNKH POS）。

---

## 30 秒看懂

| 你是谁 | 用什么 | 去哪拿 |
|--------|--------|--------|
| 店里收银 / 管货 | **PC 安装包** | Actions 绿色 run → Artifact `CNKH-Hardware-POS-V5-Windows` |
| 手机收银 / 扫码 | **Android APK** | [手机端 Releases](https://github.com/tyz11234/CNKH_POS_Mobile_APK/releases) |
| 两边一起用 | PC 开「同步/配对」+ 手机扫配对码 | 见下方「局域网配对」 |

---

## 店铺电脑怎么装（不需要 Python）

1. 打开本仓库 **Actions → Windows Release Gate**
2. 选**最新全部绿色**的运行记录（不要下失败/进行中的）
3. 下载 Artifact：`CNKH-Hardware-POS-V5-Windows`
4. 解压后运行 `CNKH_Hardware_POS_V5_Setup.exe`
5. **第一次**先开 **CNKH POS Admin**，建管理员；之后再开 Staff

详细图文：[docs/GITHUB_BUILD_AND_DOWNLOAD_CN.md](docs/GITHUB_BUILD_AND_DOWNLOAD_CN.md)

### 数据落在哪

| 用途 | 路径 |
|------|------|
| 数据库 | `%LOCALAPPDATA%\CNKH Hardware POS\Data\hardware_pos.db` |
| 备份 | `...\Backups` |
| 日志 | `...\Logs` |
| 导出 | `...\Exports` |
| 收据 PDF | `...\Receipts` |
| 收款码等资源 | `...\Assets` |
| 商品图 | 数据库旁 `product_images\`（与 SQLite 分离） |

金额用整数分（sen）；升级库：`integrity_check → 备份 → migration`，失败会回滚并拦写入。

---

## PC 主要能力

- **收银**：搜商品 / 扫码、挂单取单、现金 / 卡 / DuitNow QR / 赊账、找零、整单折扣（可审计）
- **库存**：商品、分类、进货、盘点、低库存提醒
- **客户 / 供应商**、报表、日结、审计日志
- **打印**：Windows / USB 小票；条码标签硬件打印（手机端只做队列 / PNG 导出）
- **备份恢复**（Windows 本机）
- **局域网同步**：顶栏 **同步/配对** → 开服务出二维码，手机扫码即可

---

## 局域网配对（PC ↔ 手机，无云）

1. PC 与手机连**同一 Wi‑Fi**（访客网隔离常连不上）
2. PC 顶栏点 **同步/配对**，启动服务（默认端口 **8787**）
3. 手机 AppBar 点 **扫码配对**，扫 PC 上的码  
   - 码内容形如：`cnkh-sync:v1|{"baseUrl":"http://192.168.x.x:8787","token":"...","name":"CNKH-PC"}`
4. 连接成功后：销售近实时互推；商品 / 客户等以 PC 拉取为主（持续增强双向）

手动填 IP：手机 **设置 → LAN Sync → 高级**。  
技术细节：[LAN_SYNC.md](https://github.com/tyz11234/CNKH_POS_Mobile_APK/blob/main/LAN_SYNC.md)（手机仓也可放副本）

---

## 和手机端分工

| | PC | 手机 APK |
|--|----|----------|
| 主库 / 权威数据 | ✅ | 本地 SQLite 缓存 + 同步 |
| 标签机硬件打印 | ✅ | ❌（导出 PNG / 打印队列） |
| Windows 备份还原 | ✅ | ❌ |
| 摄像头连续扫码 | USB 扫枪 | ✅ |
| 蓝牙小票（可选） | — | 可选开启 |
| 店名显示 | 设置 | 登录页 / 顶栏：**黄金发宝号** |

功能对照表见手机仓 [MOBILE_PC_PARITY](https://github.com/tyz11234/CNKH_POS_Mobile_APK) 说明或仓库内 `MOBILE_PC_PARITY.md`。

---

## 开发者本地跑

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-build.txt
python admin_launcher.py
python staff_launcher.py
```

```powershell
pytest -q
python tools/source_self_test.py
```

### 目录速览

- `cnkh_pos/database` — 连接、schema、migration  
- `cnkh_pos/services` — 销售、进货、打印、LAN sync、备份…  
- `cnkh_pos/ui` — Admin / Staff / 对话框  
- `resources` — QSS、图标  
- `tests` / `installer` / `build` / `.github/workflows`

更多：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/MIGRATIONS.md](docs/MIGRATIONS.md) · [docs/UI_DESIGN_SYSTEM.md](docs/UI_DESIGN_SYSTEM.md)

---

## 相关链接

- 手机 APK 下载：[tyz11234/CNKH_POS_Mobile_APK](https://github.com/tyz11234/CNKH_POS_Mobile_APK/releases)
- 当前移动配套开发分支常在 PR（如 `feat/mobile-sync-ereceipt-scan`）合入后进主线

**安全提示：** 局域网 Token 勿发到公网；配对码有时效时请在期限内扫完。
