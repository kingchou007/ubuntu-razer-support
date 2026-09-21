# 维护与发布

## 开发环境

Ubuntu 22.04 / Python 3.10 / GTK 4 是当前最低验证基线。普通监控可移植；风扇协议严格限定 USB 1532:02b7。使用系统 `/usr/bin/python3`，避免 Conda 环境缺少 PyGObject。

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-pil xvfb x11-utils
./run.sh
python3 -m unittest discover -v
```

## 变更原则

- UI、普通系统读取与 root 操作分开维护。
- 特权助手保持固定参数与固定路径，不接受任意 shell 命令。
- 调整风扇协议必须给出设备 ID、协议来源、只读探测结果及恢复自动测试；不能直接扩大设备白名单。
- 普通 CI 不重启、不写 HID、不修改引导配置。内核切换单元测试使用 mock。
- 风扇必须具备独立于 GUI 的失联、拔电与温度回退。日志和 UI 区分实际 RPM 与目标 RPM。
- 不提交令牌、账户信息、系统全量日志、GRUB UUID、私人桌面截图或设备序列号。
- README 截图与当前版本保持一致；截图在 Xvfb 中生成。

## 目录

- `ubuntu_support/app.py`：GTK 界面。
- `ubuntu_support/system.py`：普通读取、电源策略。
- `ubuntu_support/fan_service.py`：型号限定的 HID、风扇服务、认证客户端。
- `ubuntu_support/kernel_helper.py`：GRUB 一次性启动助手。
- `packaging/`：desktop、Polkit、systemd 和 Debian 维护脚本。
- `scripts/build-deb.sh`：不需要 root 的构建。
- `docs/maintenance/`：实际使用的扬声器包装脚本与服务；不自动安装。

## 发布检查

1. 更新 `VERSION`、`CHANGELOG.md`、README 版本与安装示例。
2. 运行单元测试、语法检查、虚拟桌面 smoke test。
3. 构建 `.deb`，检查内容与权限；特权助手必须 root 所有、755，不能从用户目录导入模块。
4. 在支持的机器验证双风扇 RPM、手动目标、自动恢复和服务停止；核对内核列表但不在 CI 重启。
5. 把未完成的实体硬件测试如实写入 `docs/validation.md`。
6. 提交、打 `vX.Y.Z` 标签，将 `.deb` 与 SHA256 上传 Release。

自动构建模板位于 `docs/ci.github-actions.yml`。具有 GitHub workflow 写入权限的维护者可把它移到 `.github/workflows/ci.yml`，启用测试、构建与 artifact 上传；当前未启用远程 CI。设置长期维护流程不代表有人自动监控机器；硬件或内核更新后仍需按验证清单复测。
