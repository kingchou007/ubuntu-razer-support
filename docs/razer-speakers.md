# Razer Blade 16 内置扬声器修复记录

本记录依据本机安装脚本、历史备份、ALSA codec 信息及 systemd 日志整理。范围是 RZ09-0510 / Realtek ALC298；不是所有 Razer 机型的通用修复。

## 设备与问题边界

| 项目 | 实际核对值 |
|---|---|
| 型号 | Razer Blade 16（2024）RZ09-0510 |
| 系统 | Ubuntu 22.04.5 LTS |
| 检查时内核 | 6.8.0-136-generic |
| Codec | Realtek ALC298 |
| Vendor ID | 0x10ec0298 |
| Subsystem ID | 0x1a58300a |
| 本次启动 codec 节点 | /proc/asound/card1/codec#0 |
| 对应控制设备 | /dev/snd/hwC1D0 |

此修复针对“声卡存在但内置扬声器没有正常发声”的功放初始化问题。桌面静音、输出端口选错、HDMI / 蓝牙作为默认输出、音频服务异常应先单独排查；麦克风路由不属于本 HDA 初始化序列的范围。

## 实际采用的方案

1. 安装 `alsa-tools`，使用其中的 `hda-verb`。
2. 使用 [yadu-tv/rb14-2023-audio-fix](https://github.com/yadu-tv/rb14-2023-audio-fix) 的 `rb_audio.sh` 初始化序列。该上游以 Blade 14 命名；本机封装增加了明确的 ALC298 + 子系统 ID 检查。上游 README 将原研究归功于 jamir。
3. 外层包装脚本动态查找 ALSA card / codec 编号，替换上游固定的 `/dev/snd/hwC2D0`。本机当前实际设备是 `/dev/snd/hwC1D0`，因此不能照搬固定编号。
4. 使用两个 oneshot systemd 服务分别在开机和系统睡眠结束后重新初始化。
5. 2026-09-21 将包装脚本改为最多等待声卡 30 次、每次 1 秒，解决开机时 codec 还没出现便过早失败的时序问题。此变化由 2026-08-31 的本地备份与当前已安装脚本对比确认。

上游序列在本机安装文件的 SHA-256：

```text
3f7ab6f9819beb0bd2e04cd40582f1720bbb34fa6b3ce504550fe64c303745db
```

本仓库保存当前包装脚本与服务定义，见 [maintenance/](maintenance/)。硬件寄存器序列不随 GUI 包分发，也不在安装 GUI 时自动执行。

## 已安装文件

```text
/usr/local/lib/razer-audio-fix/rb_audio.sh
/usr/local/sbin/run-razer-alc298-fix
/etc/systemd/system/razer-audio-fix.service
/etc/systemd/system/razer-audio-fix-resume.service
```

`razer-audio-fix.service` 在 `sound.target` 之后运行；`razer-audio-fix-resume.service` 挂到 suspend / hibernate / hybrid-sleep / suspend-then-hibernate targets 之后。

## 本次取证结果（2026-09-21）

- 开机服务已启用，状态 `active (exited)`，退出码 `0/SUCCESS`。
- 10:13:33 日志：`Razer ALC298 amplifier initialized on /dev/snd/hwC1D0.`
- 唤醒服务已启用，目前 `inactive (dead)`；对于未触发的 oneshot 服务，这不表示失败。
- 本轮只核对服务与脚本，没有重新播放扬声器测试音，也没有实际合盖 / 唤醒。因此听感、左右声道及本次内核的唤醒后发声仍须人工验证。

## 在同一硬件上复现

先检查设备匹配和默认输出：

```bash
cat /sys/class/dmi/id/product_name
grep -E 'Codec:|Vendor Id:|Subsystem Id:' /proc/asound/card*/codec#*
pactl info
pactl list sinks short
pactl get-sink-mute @DEFAULT_SINK@
pactl get-sink-volume @DEFAULT_SINK@
```

从上游下载序列到本地文件，校验 SHA-256 后再安装，不直接管道运行远程脚本：

```bash
sudo apt install alsa-tools
curl -fL https://raw.githubusercontent.com/yadu-tv/rb14-2023-audio-fix/main/rb_audio.sh -o /tmp/rb_audio.sh
printf '%s  %s\n' '3f7ab6f9819beb0bd2e04cd40582f1720bbb34fa6b3ce504550fe64c303745db' '/tmp/rb_audio.sh' | sha256sum -c -
```

若校验不符，停止使用新文件，先审阅上游变化。确认同型号及子系统 ID 后，在仓库根目录执行：

```bash
sudo install -d -m 755 /usr/local/lib/razer-audio-fix
sudo install -m 644 /tmp/rb_audio.sh /usr/local/lib/razer-audio-fix/rb_audio.sh
sudo install -m 755 docs/maintenance/run-razer-alc298-fix /usr/local/sbin/run-razer-alc298-fix
sudo install -m 644 docs/maintenance/razer-audio-fix.service docs/maintenance/razer-audio-fix-resume.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now razer-audio-fix.service
sudo systemctl enable razer-audio-fix-resume.service
```

包装脚本先核对 codec 和子系统 ID；找不到设备、节点不是字符设备或缺少初始化脚本时，拒绝继续。

## 验证与故障定位

```bash
systemctl status razer-audio-fix.service razer-audio-fix-resume.service
journalctl -b -u razer-audio-fix.service -u razer-audio-fix-resume.service
```

从系统声音设置选中内置扬声器，以较低音量测试左右声道；保存工作后再测试重启和合盖唤醒。切换到新内核后重复上述验证，不把普通内核上的结果直接当作 realtime 内核的验证结果。

若服务正常但仍无声，先核对默认 sink、mute、音量和输出端口。若提示 codec 未找到，检查该内核是否识别 ALC298，以及等待是否耗尽。不要删除子系统 ID 检查来“兼容”其他型号。

## 回退

```bash
sudo systemctl disable --now razer-audio-fix.service
sudo systemctl disable razer-audio-fix-resume.service
```

禁用服务可阻止后续开机 / 唤醒再次写入；已经写入硬件的状态不会因停止 oneshot 服务立刻撤销。需要时关机后冷启动，让固件重新初始化。确认不再需要后再删除上述专用文件并执行 `sudo systemctl daemon-reload`。
