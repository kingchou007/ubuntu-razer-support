# Terminator 灰色背景

2026-09-21：按用户要求，将默认 profile 背景改为深灰色 `#303030`，使用纯色、不透明背景，关闭主题颜色覆盖。保留已有文字调色板、快捷键和布局。

## 应用

配置位置为 `~/.config/terminator/config`。先备份原文件，将 `configs/terminator/gray-background.conf` 的三个配置项合并到 `[profiles]` 下的 `[[default]]`，不要覆盖整个文件。新启动的 Terminator 进程读取该配置；已有窗口可能需要退出所有 Terminator 窗口后重新打开。退出前先结束或保存终端内的工作。

## 回退

本机修改前已在同目录保存 `config.before-gray-background-时间戳`。将对应备份复制回 `config`，重新启动 Terminator 即可恢复。

## 验证

使用系统 Python 的 ConfigObj 回读配置，确认默认 profile 的背景为 `#303030`。未关闭现有终端会话，未进行桌面视觉验证。仓库 18 项单元测试、compileall 和 Debian 包构建通过。
