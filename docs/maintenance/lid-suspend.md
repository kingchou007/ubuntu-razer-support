# 合盖睡眠检查（2026-09-21）

环境：本机 Razer + NVIDIA，内核 `6.8.0-136-generic`。

## 本次证据与结论

- 14:47:46 logind 收到合盖事件；14:47:54 发起 suspend。
- 14:47:58–14:48:00 NVIDIA suspend 服务正常完成。
- 14:48:00 内核记录 `PM: suspend entry (s2idle)`。
- 14:48:14 内核退出睡眠，同秒 logind 收到开盖事件；14:48:15 suspend/resume 服务正常完成。
- 从合盖到内核进入睡眠约 14 秒。该次并非完全未睡眠；日志不足以确定前 8 秒延迟的具体来源，也未测量睡眠功耗。
- 当前 `/sys/power/mem_sleep` 为 `[s2idle] deep`，实际选中 s2idle，未验证 deep。
- 检查时没有 block 模式的 sleep 或 handle-lid-switch inhibitor；有正常的 sleep delay inhibitor。检查时状态不能代表事件发生时的全部状态。

## 当前配置

`/etc/systemd/logind.conf.d/60-lid-switch.conf`：

```ini
[Login]
HandleLidSwitch=suspend
HandleLidSwitchExternalPower=suspend
HandleLidSwitchDocked=ignore
LidSwitchIgnoreInhibited=yes
```

普通合盖及插电合盖配置为 suspend；系统判断为 docked（例如外接显示器）时配置为 ignore。本次日志已证实实际触发 suspend，不能把 docked 例外认定为本次原因。

## 复查

```sh
systemd-inhibit --list --no-pager
journalctl -b -u systemd-logind -u systemd-suspend -u nvidia-suspend -u nvidia-resume --no-pager
journalctl -b -k --no-pager | rg 'PM: suspend|wakeup|Wakeup'
cat /sys/power/mem_sleep
```

保存工作后，分别在外接屏连接与断开时合盖至少 30 秒，再开盖检查日志。功耗、风扇是否停转、长时间睡眠和 deep 模式仍待实体验证。本次只做只读诊断，没有改变运行配置，无需回退。
