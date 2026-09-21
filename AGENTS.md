# ubuntu-support 维护约定

适用于整个仓库。项目定位：搭载 NVIDIA 独显的 Razer 笔记本（Razer laptop with NVIDIA GPU）的 Ubuntu 调试与支持，长期维护中文工具及本机修复记录；不能把结果泛化到未经验证的机型。

## 项目与沟通
- 本机所有系统相关内容统一归档到本仓库：脚本、配置模板、安装 / 回退步骤、故障修复与验证结果；完成后提交并同步 GitHub，不只留临时文件。
- 产品、命令、Debian 包统一命名 `ubuntu-support`；Python 包为 `ubuntu_support`。
- 当前基线：Ubuntu 22.04、Python 3.10、GTK4；用 `/usr/bin/python3` 运行 GUI。
- 用户要求：真实双风扇 RPM、插电控制 / 拔电自动、nvitop、显示器配置、普通 / realtime 一次性内核切换。
- 保持 README 功能介绍、截图、版本和实际行为一致。区分“检查通过”和“实际硬件验证通过”。

## 代码与权限
- GUI 不以 root 运行；慢查询放工作线程，UI 只在 GLib 主线程更新。
- 内核、风扇助手必须安装到 root 所有的固定路径，使用 Python `-I`，不导入用户目录代码。
- 不增加任意命令执行接口，不把 hidraw 全局写权限交给普通用户。
- 风扇当前只允许 USB `1532:02b7`；协议变化先核对来源和只读探测。
- 风扇默认仅监测；必须用户主动点击应用才接管，插电 / 启动 / 重启不自动恢复手动模式。
- 用户偏好安静：默认目标 / 上限 3000 RPM，不自动启用高转速；上限不能阻止热保护接管。
- 保留 20 秒控制租约、拔电回退、温度保护及服务停止时恢复自动。
- 目标转速不能当作实际 RPM；NVIDIA `N/A` 不能被解释为整个机器没有风扇。
- NVIDIA 默认按需读取；不在电池供电 / 页面隐藏时持续轮询独显。nvitop 用户主动打开。
- 本机同时用于机器人开发与 Realtime 实时控制，按具体任务选择内核；不要把内核切换成功等同于机器人控制环境已完成实时验证。
- 内核操作只接受已校验的 GRUB 项，不修改永久默认、不自动卸载内核。
- CI 不写硬件、不修改 GRUB、不重启；实体切换由用户确认目标和重启。

## 文档与维护
- 声音修复证据及适用硬件见 `docs/razer-speakers.md`；不得去掉 codec / subsystem 检查。
- `docs/maintenance/` 是现有音频修复快照，GUI 包不自动安装或执行它。
- 发布更新 `VERSION`、`CHANGELOG.md`、README 和 `docs/validation.md`。
- 截图在隔离 Xvfb 环境生成；不提交私人桌面、序列号、账户信息或完整系统日志。
- 协议与借鉴来源保留在 `THIRD_PARTY.md`，许可证 GPL-2.0-only。

## 完成前验证
- `python3 -m unittest discover -v`
- `python3 -m compileall -q ubuntu_support`
- `./scripts/build-deb.sh`，核对包元数据、root 所有权和特权助手权限。
- UI 改动运行 `tests/smoke_ui.py` 并查看受影响页面截图。
- 硬件能力改变时更新验证记录；无法实际测试的项目明确保留待测。
- 发布流程和回退见 `CONTRIBUTING.md`、`docs/architecture.md`。
