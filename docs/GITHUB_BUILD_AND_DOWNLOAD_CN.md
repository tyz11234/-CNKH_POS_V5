# GitHub 构建与下载安装说明

## 你只需要下载 Windows 安装包

店铺电脑不需要安装 Python，也不需要运行源码。

1. 打开 GitHub 仓库 `tyz11234/-CNKH_POS_V5`。
2. 点击 **Actions**。
3. 点击 **Windows Release Gate**。
4. 只选择状态为绿色勾号的最新运行记录。
5. 滚到该记录底部的 **Artifacts**。
6. 下载 `CNKH-Hardware-POS-V5-Windows`。
7. 解压下载文件，运行 `CNKH_Hardware_POS_V5_Setup.exe`。
8. 第一次先打开 **CNKH POS Admin** 建立管理员；之后才打开 Staff。

Artifact 内应包含：

- `CNKH_POS_Admin.exe`
- `CNKH_POS_Staff.exe`
- `CNKH_Hardware_POS_V5_Setup.exe`
- `release-manifest.json`
- `build-info.json`
- `ui-acceptance-artifacts` UI 验收证据

## 手动启动一次 GitHub 构建

1. 进入 **Actions → Windows Release Gate**。
2. 点击 **Run workflow**。
3. Branch 选择 `main`。
4. 再点击绿色的 **Run workflow**。
5. 等待所有步骤完成并显示绿色勾号。

如果任何步骤失败，不要下载或使用该次运行。工作流在测试、UI 验收、EXE 自检或 Installer 构建失败时会阻止 Artifact 上传。

## 数据位置与卸载

正式数据保存在：

```text
%LOCALAPPDATA%\CNKH Hardware POS\Data\hardware_pos.db
```

安装器不会把数据库放进程序安装目录；卸载软件也不会自动删除该数据库。进行升级或迁移前仍应先在 Admin 执行 Backup。
