# 屏幕黑屏与合盖状态异常（2026-09-22）

## 只读诊断

- 用户明确表示没有合盖；两次读取 `/proc/acpi/button/lid/*/state` 均为 `closed`，login1 的 `LidClosed` 也为 true。物理状态与系统状态不一致，是当前首要排查方向。
- 本地时间 21:48–21:57 多次发生整机 deep suspend；例如 21:50:32 完成唤醒，21:50:57 再次请求睡眠。此类黑屏伴随整机睡眠，并非只有显示输出关闭。
- 最近记录的合盖事件在前一天，之后未见开盖事件。尚不能区分传感器误报、磁性干扰、固件/ACPI 状态未更新，也不能证明每一次用户看到的黑屏均对应这些睡眠。
- 配置为普通合盖、插电合盖 suspend，docked ignore。当前插电；login1 Docked=false 不能单独证明没有外接显示器。
- 当前 X11 外接 DP-1-3 为 3840×2160 60 Hz，内屏连接但未启用。GNOME 当前持有 handle-lid-switch 抑制锁；不能据此反推此前睡眠时也持有该锁。
- 21:48 唤醒后 NVIDIA 输出日志显示全部断开；21:57:10 才有外接屏连接记录。显示连接恢复与睡眠循环可能有关，但尚未证实因果。
- 沙箱外 NVIDIA 查询正常：驱动 580.126.09，GPU 47°C。沙箱内查询失败是访问限制，不作为驱动损坏证据。
- 唤醒有 USB 控制器重初始化，另有一次 NVIDIA invalid head number；不足以认定为黑屏根因。

## 下一步

1. 保持盖子打开，移开手机、磁吸配件、磁性表带及叠放设备，复查盖子状态。磁性干扰仅为候选原因；其他厂商说明不能作为此 Razer 已确诊的依据：[MSI 合盖传感器说明](https://www.msi.com/support/technical_details/NB_Hall_Effect_Sensor)。
2. 保存工作后进行一次受控开合盖，观察是否重新收到 Lid opened，并回读 open。该测试可能触发睡眠，不能由诊断脚本自动执行。
3. 若仍误报，再排查 ACPI/固件和传感器；临时屏蔽合盖动作与永久修复应区分。未擅自更改用户已有合盖睡眠偏好。

复查命令：

```sh
cat /proc/acpi/button/lid/*/state
journalctl -b -u systemd-logind --no-pager
systemd-inhibit --list --no-pager
xrandr --current
nvidia-smi --query-gpu=name,driver_version,pstate,temperature.gpu --format=csv,noheader
```

本次只新增脱敏诊断文档，未修改运行配置，无需系统回退。硬件原因与修复效果待验证。
