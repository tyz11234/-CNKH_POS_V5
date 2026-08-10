# Run #8 GitHub-ready 追加验证说明

版本：5.0.0-alpha.4

本文件只记录在已通过本地 Source Candidate 基础上，为下一次真实 GitHub Actions / Windows runner 增加的门禁。

## 新增门禁

1. `python -m unittest discover -s tests -v` 作为 Windows workflow 独立步骤。
2. `python -m compileall -q cnkh_pos tools tests admin_launcher.py staff_launcher.py` 作为独立步骤。
3. Setup 静默安装并通过 installed Admin/Staff JSON self-test 后，增加 `Installed EXE normal launch smoke test`。
4. normal-launch smoke 在隔离 `LOCALAPPDATA` 建立测试数据库和 Admin/Staff 用户，然后直接运行安装目录里的 `CNKH_POS_Admin.exe` 与 `CNKH_POS_Staff.exe`，不传 `--self-test`。
5. Admin 必须出现 `CNKH POS Admin Login`，Staff 必须出现 `CNKH POS Staff Login`，并且 `MainWindowHandle` 非 0。
6. 结果写入 `self-test-artifacts/installed-normal-launch.json`；任何一项不是 PASS 都会阻断发布 Artifact。

## 当前状态

本地 pytest、unittest、Source Self-Test、compileall、workflow YAML 已重新通过。当前会话虽已获得用户 GitHub Full Access 授权，但执行器没有暴露 GitHub repo/Actions 调用函数，也没有可用 `gh` CLI/直连网络，所以**尚未实际触发 Windows Actions**。本候选不得称为 Windows Installation Candidate。
