# Run #8 最终 Windows 验证说明

版本：5.0.0-alpha.4

本文件用于记录最终候选进入真实 Windows GitHub Actions 总验收时的固定范围，不是测试通过声明。

最终候选包含本轮全部稳定性修正与新增功能，包括：商品条码标签打印、标签打印张数可自定义、50×30 mm 作为默认商品标签规格（40×30 等规格仍可选）、新增商品 Barcode 自动生成/手动输入、Admin 销售记录安全删除、结账进位规则、% / RM 两种 Discount、完整业务生命周期回归，以及修复后的 80mm Qt 热敏小票打印路径。

最终 Windows Release Gate 必须在同一个 commit 上完整通过 Ruff、pytest/完整业务生命周期、unittest、compileall、Source Self-Test、100%/125%/150% GUI、Admin/Staff EXE 构建、packaged self-test、Setup.exe、静默安装、installed self-test、安装后正常启动登录窗口、release manifest/package 校验和 Artifact 上传。

80mm Qt 打印证据除文件存在外，还必须经过实际 QPrinter PDF 输出后的可读性回归，避免历史上出现的黑块/乱码；商品标签最终证据使用 50×30 mm、多张输出。

实体热敏打印机属于硬件验收，GitHub Windows runner 无法替代真实 USB/驱动/纸张测试；软件打印路径、PDF、页面尺寸与 Windows QPrinter 路径必须在 CI 中验证。
