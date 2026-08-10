# Run #8 GitHub-ready 追加验证说明

版本：5.0.0-alpha.4

本文件记录 Run #8 从 Source Candidate 进入真实 GitHub Actions / Windows runner 后追加的发布门禁与最终介质规格。

## Windows 发布门禁

1. `python -m ruff check`、pytest、unittest、compileall 与 Source Self-Test 必须全部通过。
2. Windows GUI 必须在 100%、125%、150% 三档缩放下通过验收。
3. Admin / Staff 两个 PyInstaller EXE 必须成功构建并通过 packaged JSON self-test。
4. Setup.exe 必须成功构建并完成静默安装。
5. 安装后的 Admin / Staff EXE 必须再次通过 JSON self-test。
6. 安装后的 Admin 必须正常出现 `CNKH POS Admin Login`，Staff 必须正常出现 `CNKH POS Staff Login`，并且 `MainWindowHandle` 非 0。
7. 完整业务生命周期验收覆盖：用户、客户、供应商、商品新增/编辑/删除、自动/手动 Barcode、进货与付款、库存、挂单/取单、结账、%/RM Discount、结账进位、退货、销售删除、盘点、报表、日结、Excel、条码标签、小票、备份恢复与 Admin/Staff 页面启动。
8. 最终 release manifest、release package 校验和 Windows Artifact 上传必须成功。

## 最终打印介质规格

- 商品条码标签默认规格：**50 × 30 mm**。
- 条码标签打印张数：用户可自定义 1–999 张；每张标签独立一页/一张。
- 销售小票规格：**80 mm 热敏纸**。
- 80mm 小票纸长必须跟随实际内容动态生成，不得强制使用 297 mm 固定页长；标准证据小票约为 120 mm 高。
- 80mm Qt/QPrinter 路径必须使用可读性与纸长回归，防止字体黑块、金额裁切、内容异常收缩或大量空白出纸。
- 实体打印机仍属于最终现场硬件兼容性验证；CI 负责验证 Windows 打印路径、PDF 输出、80mm 页面宽度、动态内容纸长与版面证据。

## 当前验证状态

GitHub Actions Run #92 曾完整通过代码、GUI、EXE、Setup、安装后 self-test、普通启动 smoke 与 Artifact 上传；人工检查证据时发现 Qt 80mm 小票存在黑块，因此未签为最终完成。随后已修复 Qt 80mm 打印路径，并通过 focused Windows 可读性回归。

之后用户将商品条码标签最终规格明确为 50 × 30 mm。50×30 的默认 UI、PDF、Windows 条码渲染与相关 focused 测试已经通过。

Run #105 对已合并 main 的产品源码快照再次完整通过 28/28 Windows Release Gate，但人工检查最终 Qt PDF 时确认页长仍固定为 297 mm，会造成热敏纸大量空白。随后已将 Qt/QPrinter 页长改为跟随已验证的 80mm 内容 PDF，并通过 focused Windows 测试，要求证据小票宽约 80 mm、高约 120 mm且内容可读。

最终干净 Windows Release Gate 必须在包含 50×30 标签 + 80mm 动态纸长修复的同一 commit 上重新完整通过后，才可称为最终 Windows Installation Candidate。
