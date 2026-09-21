# 架构与权限

GTK GUI 以登录用户运行。CPU、内存、电池、磁盘、显示连接来自 procfs / sysfs；慢命令在线程中执行，完成后通过 GLib 回到 UI。NVIDIA 默认只在用户请求时查询。

## 风扇

`ubuntu-support-fans.service` 以 root 运行，只访问型号匹配的 Razer HID。测速 JSON 位于 `/run/ubuntu-support/fans.json`，普通用户可读。Unix socket 接收固定的 manual / keepalive / auto 请求。

manual 必须来自 root；GUI 通过 Polkit 调用 root 所有的 `/usr/libexec/ubuntu-support-fans --set RPM`。服务使用 `SO_PEERCRED` 校验请求者，记录经 pkexec 传入的原始 UID。续租和主动释放只允许该 UID；手动控制不是永久设备权限，不给用户全局 hidraw 写权限。

服务每 3 秒读取实际转速。手动会话最多 20 秒无续租即恢复自动；拔电、温度过高或温度传感器失败同样恢复。只在手动模式且独显已活动时读取 GPU 温度。CPU ≥85°C / GPU ≥80°C 是本项目的保守退出阈值，不是厂商规定的最高温度。

硬件断连会丢弃句柄并重试；服务正常停止时恢复自动。服务使用 systemd restart 策略；进程被 SIGKILL 后只能依赖重启恢复与固件自身保护，不能把用户态控制视作独立的硬件安全机制。

## 内核

`/usr/libexec/ubuntu-support-kernel` 仅接受 list / schedule / reboot / cancel。它重新读取 root 所有的 GRUB 配置，匹配允许的已安装内核版本与稳定 menuentry ID，不信任 GUI 提供的任意入口。使用 `/usr/bin/python3 -I` 禁止用户 Python 环境注入。

本版本只在简单、可验证的 ext2/3/4 或 vfat 启动分区上允许一次性切换，排除明显的 LVM / MDRAID。`grub-reboot` 后回读 `next_entry`；重启命令失败则恢复之前的 pending entry。不调用 update-grub、不改变永久默认、不卸载内核。

实际 reboot 和显示驱动兼容性需要人工测试。只读检查通过不等于已通过启动验证。

## 回退

关闭自动电源切换后使用系统电源设置。风扇点击“恢复自动风扇”；退出后服务也会通过租约自动恢复。取消下次内核切换只清除 `next_entry`。卸载包会停止风扇服务，不改变音频修复或已安装内核。

默认静音目标 / 上限均为 3000 RPM，用户偏好保存到 `~/.config/ubuntu-support/preferences.json`。服务同时验证目标与上限；上限只约束手动指令，不改变固件热保护。
