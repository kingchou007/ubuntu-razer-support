"""Chinese GTK4 desktop utilities, with explicit actions and low-cost monitoring."""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from . import system, kernel_helper, fan_service
import json
import time
import os

PROFILE_LABELS = {'power-saver': '省电', 'balanced': '平衡', 'performance': '性能'}
CSS = b'''
window { background: #f3f5f9; color: #243047; }
headerbar { background: #ffffff; }
.title { font-size: 25px; font-weight: 800; }
.subtitle, .muted { color: #64748b; }
.card { background: #ffffff; border-radius: 16px; padding: 20px; border: 1px solid #e3e8ef; }
.metric-title { color: #64748b; font-size: 13px; }
.metric-value { font-size: 26px; font-weight: 800; color: #18253b; }
.section-title { font-size: 18px; font-weight: 700; }
.good { color: #12805c; } .warning, .warm { color: #b65e00; } .danger { color: #b42318; }
.status { padding: 10px 20px; background: #e8edf5; color: #43536b; }
button { border-radius: 9px; padding: 9px 14px; }
button.suggested-action, button:checked { background: #e95420; color: white; }
list row { padding: 5px 10px; border-radius: 6px; }
.banner { background: #eaf4ef; border-radius: 12px; padding: 14px; color: #206649; }
'''


def label(text='', style=None):
    item = Gtk.Label(label=text, xalign=0, wrap=True)
    if style:
        item.add_css_class(style)
    return item


def box(spacing=12):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def card(title):
    item = box()
    item.add_css_class('card')
    item.append(label(title, 'section-title'))
    return item


class MetricCard(Gtk.Box):
    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.add_css_class('card')
        self.set_hexpand(True)
        self.append(label(title, 'metric-title'))
        self.value = label('—', 'metric-value')
        self.detail = label('', 'muted')
        self.append(self.value)
        self.append(self.detail)


class UbuntuManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='ubuntu-support')
        self.set_default_size(1080, 800)
        self.set_size_request(720, 540)
        self._cpu_previous = system.cpu_sample()
        self.policy = system.PowerPolicy()
        self._busy = set()
        self._closed = False
        self._timers = []
        self._selected_pid = None
        self._profile_buttons = {}
        self._profiles = []
        self._on_ac = None
        self._gpu_history = []
        self._fan_lease = False
        self._fan_cap = 3000
        self._fan_target = 3000
        self._preferences = Path.home() / '.config/ubuntu-support/preferences.json'
        try:
            preferences = json.loads(self._preferences.read_text())
            self._fan_cap = int(preferences.get('fan_cap', 3000))
            if self._fan_cap not in (3000, 3500, 4000, 4500, 4800):
                self._fan_cap = 3000
            self._fan_target = max(3000, min(self._fan_cap, int(preferences.get('fan_target', 3000))))
        except (OSError, ValueError, TypeError):
            pass
        self.connect('close-request', self._on_close)
        self.set_child(self._build_ui())
        self._refresh_fast()
        self._refresh_processes()
        self._refresh_power_profile()
        self._timers = [GLib.timeout_add_seconds(3, self._refresh_fast),
                        GLib.timeout_add_seconds(6, self._refresh_processes),
                        GLib.timeout_add_seconds(5, self._refresh_power_profile)]

    def _on_close(self, *_):
        if self._fan_lease:
            threading.Thread(target=lambda: self._release_fans(), daemon=True).start()
        self._closed = True
        for source in self._timers:
            GLib.source_remove(source)
        return False

    def _job(self, key, work, done):
        if key in self._busy or self._closed:
            return
        self._busy.add(key)
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, str(exc)
            def finish():
                self._busy.discard(key)
                if not self._closed:
                    done(result, error)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

    def _button(self, text, callback):
        button = Gtk.Button(label=text)
        button.connect('clicked', callback)
        return button

    def _shortcut(self, text, command):
        button = self._button(text, lambda *_: self._launch(command))
        button.set_sensitive(shutil.which(command[0]) is not None)
        if not button.get_sensitive():
            button.set_tooltip_text('尚未安装对应系统工具')
        return button

    def _launch(self, command):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self._set_status('已打开系统工具')
        except OSError as error:
            self._show_error('无法打开', str(error))

    def _page(self, stack, name, title):
        content = box(18)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + side)(24)
        content.append(label(title, 'title'))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(content)
        stack.add_titled(scroll, name, title)
        return content

    def _build_ui(self):
        root = box(0)
        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label='ubuntu-support', wrap=False))
        refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        refresh.set_tooltip_text('刷新系统状态（不唤醒独显）')
        refresh.connect('clicked', self._refresh_all)
        header.pack_end(refresh)
        self.set_titlebar(header)
        stack = Gtk.Stack()
        stack.set_vexpand(True)
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(14)
        root.append(switcher)
        root.append(stack)
        self.stack = stack

        overview = self._page(stack, 'overview', '系统概览')
        self.banner = label('正在读取电源状态…', 'banner')
        overview.append(self.banner)
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        self.cards = {}
        for index, (name, title) in enumerate([('cpu', 'CPU 使用率'), ('temp', 'CPU 温度'), ('memory', '内存'), ('battery', '电池'), ('disk', '系统磁盘'), ('fan', '风扇')]):
            item = MetricCard(title)
            self.cards[name] = item
            grid.attach(item, index % 3, index // 3, 1, 1)
        overview.append(grid)
        quick = card('常用操作')
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2, row_spacing=8, column_spacing=8)
        for title, command in [('显示器', ['gnome-control-center', 'display']), ('声音 / 麦克风', ['gnome-control-center', 'sound']), ('Wi-Fi', ['gnome-control-center', 'wifi']), ('蓝牙', ['gnome-control-center', 'bluetooth']), ('文件管理', ['nautilus']), ('系统监视器', ['gnome-system-monitor']), ('软件更新', ['update-manager']), ('锁屏', ['loginctl', 'lock-session'])]:
            flow.insert(self._shortcut(title, command), -1)
        quick.append(flow)
        overview.append(quick)
        self.uptime_label = label('', 'muted')
        overview.append(self.uptime_label)

        power = self._page(stack, 'power', '电源与散热')
        control = card('随供电方式自动切换')
        row = Gtk.Box(spacing=12)
        text = label('拔电省电 · 插电恢复此前模式')
        text.set_hexpand(True)
        row.append(text)
        self.auto_switch = Gtk.Switch(active=True)
        self.auto_switch.set_valign(Gtk.Align.CENTER)
        self.auto_switch.connect('notify::active', self._on_auto)
        row.append(self.auto_switch)
        control.append(row)
        control.append(label('仅在管理器运行期间生效。电池供电时暂停手动性能控制；关闭开关后可自行选择模式。关闭程序不会自动恢复当前模式。', 'muted'))
        modes = Gtk.Box(spacing=10, homogeneous=True)
        previous = None
        for profile, title in PROFILE_LABELS.items():
            button = Gtk.ToggleButton(label=title)
            if previous:
                button.set_group(previous)
            button.connect('toggled', self._on_profile, profile)
            self._profile_buttons[profile] = button
            modes.append(button)
            previous = button
        control.append(modes)
        self.profile_hint = label('正在读取电源模式…', 'muted')
        control.append(self.profile_hint)
        power.append(control)
        fans = card('风扇与散热')
        self.fan_hint = label('')
        fans.append(label('默认由固件自由调节。只有点击应用才启用手动控制；打开软件、插电和重启不会自动应用。', 'muted'))
        fans.append(self.fan_hint)
        fan_grid = Gtk.Grid(column_spacing=14, column_homogeneous=True)
        self.fan_one = MetricCard('风扇 1 · 实际转速')
        self.fan_two = MetricCard('风扇 2 · 实际转速')
        fan_grid.attach(self.fan_one, 0, 0, 1, 1)
        fan_grid.attach(self.fan_two, 1, 0, 1, 1)
        fans.append(fan_grid)
        self.fan_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 3000, 4800, 100)
        self.fan_scale.set_range(3000, max(3100, self._fan_cap))
        self.fan_scale.set_value(self._fan_target)
        self.fan_scale.connect('value-changed', self._fan_target_changed)
        self.fan_scale.set_digits(0)
        self.fan_scale.set_hexpand(True)
        self.fan_target_label = label(f'待应用目标：{self._fan_target} RPM · 静音上限：{self._fan_cap} RPM', 'section-title')
        fans.append(self.fan_target_label)
        cap_row = Gtk.Box(spacing=12)
        cap_row.append(Gtk.Label(label='静音转速上限', wrap=False))
        self.fan_cap_selector = Gtk.DropDown.new_from_strings(['3000 RPM · 安静', '3500 RPM', '4000 RPM', '4500 RPM', '4800 RPM'])
        self.fan_cap_selector.set_selected((3000, 3500, 4000, 4500, 4800).index(self._fan_cap))
        self.fan_cap_selector.connect('notify::selected', self._fan_cap_changed)
        cap_row.append(self.fan_cap_selector)
        fans.append(cap_row)
        fans.append(self.fan_scale)
        fan_buttons = Gtk.Box(spacing=10)
        self.fan_apply = self._button('应用静音目标…', self._apply_fans)
        fan_buttons.append(self.fan_apply)
        fan_buttons.append(self._button('恢复自动风扇', self._auto_fans))
        fans.append(fan_buttons)
        fans.append(label('静音上限在点击应用后约束手动目标，实际 RPM 会有波动。过热时固件接管，可能超过静音上限。仅插电可用；拔电、退出、失联或温度读取失败时恢复自动。', 'muted'))
        power.append(fans)
        sleep = card('合盖与睡眠')
        self.sleep_hint = label('正在读取…')
        sleep.append(self.sleep_hint)
        sleep.append(self._shortcut('打开电源与自动睡眠设置', ['gnome-control-center', 'power']))
        power.append(sleep)
        self._build_gpu_page(stack)
        self._build_kernel_page(stack)
        self._build_display_page(stack)

        devices = self._page(stack, 'devices', '设备与设置')
        displays = card('已连接显示器')
        self.display_label = label('')
        displays.append(self.display_label)
        displays.append(label('拔插后自动刷新连接状态；分辨率、缩放和排列在系统显示设置中调整。', 'muted'))
        displays.append(self._shortcut('调整显示器', ['gnome-control-center', 'display']))
        devices.append(displays)
        settings = card('常用设置')
        shortcuts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, min_children_per_line=2, row_spacing=8, column_spacing=8)
        for title, command in [('网络 / VPN', ['gnome-control-center', 'network']), ('鼠标 / 触控板', ['gnome-control-center', 'mouse']), ('键盘快捷键', ['gnome-control-center', 'keyboard']), ('远程桌面 / 共享', ['gnome-control-center', 'sharing']), ('通知', ['gnome-control-center', 'notifications']), ('磁盘管理', ['gnome-disks']), ('启动应用', ['gnome-session-properties']), ('驱动管理', ['software-properties-gtk', '--open-tab=4']), ('所有系统设置', ['gnome-control-center'])]:
            shortcuts.insert(self._shortcut(title, command), -1)
        settings.append(shortcuts)
        devices.append(settings)
        updates = card('软件更新')
        self.update_label = label('读取本地软件源缓存；在线刷新和安装请使用更新管理器。', 'muted')
        updates.append(self.update_label)
        updates.append(self._button('查看缓存中的可升级软件包', self._check_updates))
        updates.append(self._shortcut('打开软件更新', ['update-manager']))
        devices.append(updates)

        processes = self._page(stack, 'processes', '进程管理')
        processes.append(label('按进程生命周期平均 CPU 占用排序；100% 约为一个逻辑核心。每 6 秒刷新。', 'muted'))
        search = Gtk.SearchEntry(placeholder_text='按进程名称或 PID 筛选')
        search.connect('search-changed', lambda *_: self._refresh_processes())
        self.search = search
        processes.append(search)
        processes.append(label('进程名称                                  PID          CPU          内存', 'muted'))
        self.process_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.process_listbox.connect('row-selected', self._selected)
        processes.append(self.process_listbox)
        self.end_button = self._button('结束选中进程…', self._end_process)
        self.end_button.set_sensitive(False)
        processes.append(self.end_button)
        self.status_label = label('准备就绪', 'status')
        root.append(self.status_label)
        return root

    def _set_status(self, text):
        self.status_label.set_text(f'{system.timestamp()}  {text}')

    def _refresh_fast(self):
        try:
            current = system.cpu_sample()
            self.cards['cpu'].value.set_text(f'{system.cpu_percent(self._cpu_previous, current):.0f}%')
            self._cpu_previous = current
            self.cards['cpu'].detail.set_text(f'1 分钟负载 {system.load_average()[0]:.2f}')
            memory, used, total = system.memory_percent()
            self.cards['memory'].value.set_text(f'{memory:.0f}%')
            self.cards['memory'].detail.set_text(f'{used:.1f} / {total:.1f} GiB')
            temp, state = system.temperature_state(system.cpu_temperature())
            self.cards['temp'].value.set_text(temp)
            for style in ('good', 'warm', 'warning', 'danger', 'neutral'):
                self.cards['temp'].value.remove_css_class(style)
            self.cards['temp'].value.add_css_class(state)
            self.cards['temp'].detail.set_text('处理器温度')
            supply = system.power_supply()
            self._on_ac = supply.on_ac
            source = '已连接电源' if supply.on_ac is True else '电池供电' if supply.on_ac is False else '供电状态未知'
            self.banner.set_text(source + (' · 自动电源切换已开启' if self.policy.enabled else ' · 手动管理电源模式'))
            self.cards['battery'].value.set_text(f'{supply.percent}%' if supply.percent is not None else '—')
            self.cards['battery'].detail.set_text(source + ' · ' + {'Charging': '充电中', 'Discharging': '放电中', 'Full': '已充满', 'Not charging': '未充电'}.get(supply.status, supply.status))
            disk = shutil.disk_usage('/')
            self.cards['disk'].value.set_text(f'{disk.used / disk.total * 100:.0f}%')
            self.cards['disk'].detail.set_text(f'可用 {disk.free / 2**30:.0f} / 总计 {disk.total / 2**30:.0f} GiB')
            self._refresh_fans()
            self.display_label.set_text(system.display_summary())
            self.uptime_label.set_text('已运行 ' + system.format_uptime(system.uptime_seconds()) + ' · 系统状态每 3 秒更新')
        except Exception as exc:
            self._set_status('读取状态失败：' + str(exc))
        if self.stack.get_visible_child_name() == 'gpu' and self.gpu_live.get_active() and self._on_ac is True and system.gpu_awake() and 'gpu' not in self._busy:
            self._gpu_check()
        return GLib.SOURCE_CONTINUE

    def _refresh_fans(self):
        try:
            state = json.loads(Path('/run/ubuntu-support/fans.json').read_text())
            if time.time() - state['timestamp'] > 15 or not state.get('available'):
                raise RuntimeError(state.get('error', '风扇服务读数已过期'))
            rpm = state['rpm']
            self.cards['fan'].value.set_text(f'{rpm[0]} / {rpm[1]}')
            self.cards['fan'].detail.set_text('双风扇实际转速 · RPM')
            self.fan_one.value.set_text(f'{rpm[0]} RPM')
            self.fan_two.value.set_text(f'{rpm[1]} RPM')
            self.fan_hint.set_text(state.get('reason', '固件自动控制'))
            mode_text = '手动静音' if state.get('target') else '固件自动'
            self.banner.set_text(self.banner.get_text().split(' · 风扇：')[0] + ' · 风扇：' + mode_text)
            self.fan_apply.set_sensitive(self._on_ac is True)
            self.fan_scale.set_sensitive(self._on_ac is True and self._fan_cap > 3000)
            self.fan_one.detail.set_text('实际测量，非设定值')
            self.fan_two.detail.set_text('实际测量，非设定值')
            if state.get('owner') == os.getuid() and state.get('target'):
                self._fan_lease = True
                self._job('fan-heartbeat', lambda: fan_service.send_request({'action': 'keepalive'}), lambda _, error: self._set_status('风扇会话已中断：' + error) if error else None)
            elif 'fan-action' not in self._busy:
                self._fan_lease = False
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            self.fan_apply.set_sensitive(False)
            self.fan_scale.set_sensitive(False)
            self.cards['fan'].value.set_text('等待服务')
            self.cards['fan'].detail.set_text('安装 .deb 后读取双风扇 RPM')
            self.fan_one.value.set_text('—')
            self.fan_two.value.set_text('—')
            self.fan_hint.set_text('风扇服务不可用：' + str(error))

    def _release_fans(self):
        try:
            fan_service.send_request({'action': 'auto'})
        except Exception:
            pass  # Daemon lease expires independently within 20 seconds.

    def _fan_action(self, args):
        def work():
            result = subprocess.run(['pkexec', '/usr/libexec/ubuntu-support-fans'] + args, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or '认证取消或控制失败')
            return result.stdout.strip()
        def done(value, error):
            if error:
                self._show_error('风扇操作未完成', error)
            else:
                self._fan_lease = args[0] == '--set'
                if self._closed and self._fan_lease:
                    self._release_fans()
                self._set_status(value)
            self._refresh_fans()
        self._job('fan-action', work, done)

    def _apply_fans(self, *_):
        target = min(self._fan_cap, round(self.fan_scale.get_value() / 100) * 100)
        self._save_fan_preferences()
        self._fan_action(['--set', str(target), '--limit', str(self._fan_cap)])

    def _save_fan_preferences(self):
        try:
            self._preferences.parent.mkdir(parents=True, exist_ok=True)
            self._preferences.write_text(json.dumps({'fan_cap': self._fan_cap, 'fan_target': self._fan_target}))
        except OSError as exc:
            self._set_status('未能保存风扇偏好：' + str(exc))

    def _fan_target_changed(self, scale):
        target = min(self._fan_cap, round(scale.get_value() / 100) * 100)
        if scale.get_value() > self._fan_cap:
            scale.set_value(self._fan_cap)
        self._fan_target = target
        self.fan_target_label.set_text(f'待应用目标：{target} RPM · 静音上限：{self._fan_cap} RPM')

    def _fan_cap_changed(self, selector, _):
        self._fan_cap = (3000, 3500, 4000, 4500, 4800)[selector.get_selected()]
        self.fan_scale.set_range(3000, max(3100, self._fan_cap))
        self.fan_scale.set_value(min(self._fan_target, self._fan_cap))
        self._fan_target_changed(self.fan_scale)
        self.fan_scale.set_sensitive(self._on_ac is True and self._fan_cap > 3000)
        self._save_fan_preferences()
        self._set_status('静音上限已保存；点击“应用静音目标”生效')

    def _auto_fans(self, *_):
        if self._fan_lease:
            def done(_, error):
                if error:
                    self._show_error('恢复自动失败', error)
                else:
                    self._fan_lease = False
                    self._set_status('已恢复自动风扇')
            self._job('fan-action', lambda: fan_service.send_request({'action': 'auto'}), done)
        else:
            self._fan_action(['--auto'])

    def _refresh_power_profile(self):
        def read():
            current = system.active_power_profile()
            available = system.available_power_profiles()
            return current, available
        def done(result, error):
            if error:
                self.profile_hint.set_text(error)
                return
            current, self._profiles = result
            for name, button in self._profile_buttons.items():
                button.handler_block_by_func(self._on_profile)
                button.set_active(name == current)
                button.set_sensitive(name in self._profiles and not (self.policy.enabled and self._on_ac is False))
                button.handler_unblock_by_func(self._on_profile)
            self.profile_hint.set_text('当前：' + PROFILE_LABELS.get(current, '电源模式服务不可用'))
            if 'profile-set' not in self._busy:
                target = self.policy.target(self._on_ac, current, self._profiles)
                if target:
                    self._set_profile(target)
        self._job('power-read', read, done)
        return GLib.SOURCE_CONTINUE

    def _set_profile(self, profile):
        def done(_, error):
            if error:
                self.policy.enabled = False
                self.auto_switch.set_active(False)
                self._show_error('电源模式切换失败，自动切换已暂停', error)
            else:
                self._set_status('电源模式已切换为' + PROFILE_LABELS[profile])
            self._refresh_power_profile()
        self._job('profile-set', lambda: system.set_power_profile(profile), done)

    def _on_profile(self, button, profile):
        if button.get_active():
            if self._on_ac is True:
                self.policy.ac_profile = profile
            self._set_profile(profile)

    def _on_auto(self, *_):
        self.policy.enabled = self.auto_switch.get_active()
        self.policy.last_ac = None
        self._refresh_fast()
        self._refresh_power_profile()

    def _refresh_all(self, *_):
        self._refresh_fast()
        self._refresh_power_profile()
        self._refresh_processes()
        self._read_sleep()
        self._display_refresh()
        self._kernel_refresh()
        self._set_status('系统状态已刷新')

    def _read_sleep(self):
        def read():
            def setting(key):
                return subprocess.run(['gsettings', 'get', 'org.gnome.settings-daemon.plugins.power', key], capture_output=True, text=True, check=True, timeout=5).stdout.strip().strip("'")
            external = setting('lid-close-suspend-with-external-monitor') == 'true'
            ac = setting('sleep-inactive-ac-type')
            battery = setting('sleep-inactive-battery-type')
            return f'桌面设置：外接屏合盖睡眠{"开启" if external else "关闭"}；插电空闲{"睡眠" if ac == "suspend" else "不自动睡眠"}；电池空闲{"睡眠" if battery == "suspend" else "不自动睡眠"}。实际行为还受系统合盖策略与阻止睡眠的程序影响。'
        self._job('sleep-read', read, lambda value, error: self.sleep_hint.set_text(value if not error else '无法读取睡眠设置：' + error))

    def _build_gpu_page(self, stack):
        page = self._page(stack, 'gpu', 'NVIDIA 显卡')
        self.gpu_label = label('点击检查以读取显卡信息', 'subtitle')
        page.append(self.gpu_label)
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        self.gpu_cards = {}
        for index, (name, title) in enumerate([('temperature', 'GPU 温度'), ('utilization', 'GPU 使用率'), ('power', '实时功耗'), ('memory_used', '显存占用')]):
            item = MetricCard(title)
            self.gpu_cards[name] = item
            grid.attach(item, index % 2, index // 2, 1, 1)
        page.append(grid)
        buttons = Gtk.Box(spacing=12)
        self.gpu_button = self._button('刷新显卡状态', self._gpu_check)
        buttons.append(self.gpu_button)
        self.gpu_live = Gtk.CheckButton(label='插电时实时监控')
        buttons.append(self.gpu_live)
        buttons.append(self._button('打开 nvitop 详细监控', self._open_nvitop))
        buttons.append(self._shortcut('NVIDIA 设置', ['nvidia-settings']))
        page.append(buttons)
        page.append(label('默认按需读取。实时监控仅在本页可见、已插电且独显已活动时采样；监控期间可能延迟独显休眠。', 'muted'))
        history = card('GPU 使用率趋势 · 最近 60 次采样')
        self.gpu_chart = Gtk.DrawingArea()
        self.gpu_chart.set_content_height(130)
        self.gpu_chart.set_draw_func(self._draw_gpu)
        history.append(self.gpu_chart)
        page.append(history)
        processes = card('正在占用独显的程序')
        self.gpu_processes = box(8)
        processes.append(self.gpu_processes)
        page.append(processes)

    def _open_nvitop(self, *_):
        binary = shutil.which('nvitop')
        if not binary:
            local = Path.home() / '.local/bin/nvitop'
            if local.is_file() and os.access(local, os.X_OK):
                binary = str(local)
        if not binary:
            self._show_error('尚未安装 nvitop', '请先通过 pipx install nvitop 安装，再重新打开此页面。')
            return
        if shutil.which('gnome-terminal'):
            self._launch(['gnome-terminal', '--title=ubuntu-support · nvitop', '--', binary, '-m', 'full'])
        elif shutil.which('x-terminal-emulator'):
            self._launch(['x-terminal-emulator', '-e', binary, '-m', 'full'])
        else:
            self._show_error('未找到终端', '请安装 GNOME Terminal，或在终端中运行 nvitop。')

    def _draw_gpu(self, area, cr, width, height):
        cr.set_source_rgb(.9, .93, .96)
        cr.set_line_width(1)
        for frac in (0, .5, 1):
            y = 10 + (height - 20) * frac
            cr.move_to(0, y)
            cr.line_to(width, y)
        cr.stroke()
        if not self._gpu_history:
            return
        cr.set_source_rgb(.25, .60, .20)
        cr.set_line_width(3)
        for i, value in enumerate(self._gpu_history):
            x = 6 + i * (width - 12) / 59
            y = height - 10 - (height - 20) * min(100, max(0, value)) / 100
            (cr.move_to if i == 0 else cr.line_to)(x, y)
        cr.stroke()
        cr.arc(x, y, 3, 0, 6.283185)
        cr.fill()

    def _gpu_check(self, *_):
        self.gpu_button.set_sensitive(False)
        def done(value, error):
            self.gpu_button.set_sensitive(True)
            if error:
                self.gpu_label.set_text('读取失败：' + error)
                return
            self.gpu_label.set_text(value['name'] + ' · 驱动 ' + value['driver'] + ' · ' + value['state'] + ' · ' + system.timestamp())
            for key, item in self.gpu_cards.items():
                item.value.set_text(value[key])
            self.gpu_cards['memory_used'].detail.set_text('总显存 ' + value['memory_total'])
            self.gpu_cards['power'].detail.set_text('设备报告的瞬时功耗')
            try:
                self._gpu_history.append(float(value['utilization'].split()[0]))
                self._gpu_history = self._gpu_history[-60:]
                self.gpu_chart.queue_draw()
            except ValueError:
                pass
            while child := self.gpu_processes.get_first_child():
                self.gpu_processes.remove(child)
            for item in value['processes']:
                self.gpu_processes.append(label(f"{Path(item['name']).name}  ·  PID {item['pid']}  ·  {item['memory']}  ·  {item['type']}"))
            if not value['processes']:
                self.gpu_processes.append(label('驱动未报告占用进程', 'muted'))
        self._job('gpu', system.gpu_snapshot, done)

    def _build_display_page(self, stack):
        page = self._page(stack, 'display', '显示器配置')
        page.append(label('分辨率、刷新率、缩放、主屏与多屏排列', 'subtitle'))
        self.display_cards = box(14)
        page.append(self.display_cards)
        controls = card('配置显示器')
        controls.append(self._shortcut('打开显示器配置', ['gnome-control-center', 'display']))
        controls.append(label('使用 Ubuntu 原生显示设置保存配置；支持扩展 / 镜像、排列、旋转、刷新率和缩放，并提供应用后的确认与回退。', 'muted'))
        controls.append(self._button('刷新连接与当前模式', lambda *_: self._display_refresh()))
        page.append(controls)

    def _display_refresh(self):
        def done(value, error):
            while child := self.display_cards.get_first_child():
                self.display_cards.remove(child)
            if error:
                self.display_cards.append(label(system.display_summary() + '\n详细模式请在系统显示设置中查看。'))
                return
            for item in value:
                panel = card(item['name'] + (' · 主显示器' if item['primary'] else ''))
                panel.append(label(item['mode'] + '  ·  ' + item['rate'], 'metric-value'))
                self.display_cards.append(panel)
        self._job('displays', system.display_details, done)

    def _build_kernel_page(self, stack):
        page = self._page(stack, 'kernel', '内核切换')
        self.kernel_current = label('当前内核：' + os.uname().release, 'banner')
        page.append(self.kernel_current)
        page.append(label('选择普通或 Realtime 内核，只切换下一次启动；随后重启恢复原有默认内核。重启前请保存工作。', 'muted'))
        self.kernel_list = box(12)
        page.append(self.kernel_list)
        self.kernel_status = label('正在检查已安装内核…', 'muted')
        page.append(self.kernel_status)
        row = Gtk.Box(spacing=10)
        row.append(self._button('刷新内核列表', lambda *_: self._kernel_refresh()))
        row.append(self._button('取消下次切换', lambda *_: self._kernel_confirm('cancel', None)))
        page.append(row)

    def _kernel_refresh(self):
        def read():
            entries = kernel_helper.inventory()
            try:
                pending = kernel_helper.pending()
            except Exception:
                pending = '无法读取（需管理员权限）'
            return entries, pending
        def done(value, error):
            while child := self.kernel_list.get_first_child():
                self.kernel_list.remove(child)
            if error:
                self.kernel_status.set_text('无法读取 GRUB：' + error)
                return
            entries, pending = value
            entries.sort(key=lambda entry: not entry['ready'])
            pending = next((entry['version'] for entry in entries if entry['entry'] == pending), '其他已安排的启动项' if pending and not pending.startswith('无法读取') else pending)
            helper = Path('/usr/libexec/ubuntu-support-kernel').is_file()
            self.kernel_status.set_text('下次启动：' + (pending or '原有默认内核') + ('' if helper else '\n安装 .deb 后可使用管理员切换功能。'))
            for entry in entries:
                version = entry['version']
                panel = card(version + (' · 实时内核' if 'realtime' in version else ' · 普通内核'))
                panel.append(label('启动文件与显卡模块检查通过；未验证实际启动' if entry['ready'] else '暂不可切换：' + '；'.join(entry['problems']), 'muted'))
                row = Gtk.Box(spacing=10)
                for action, title in [('schedule', '设为下次启动'), ('reboot', '切换并重启…')]:
                    button = self._button(title, lambda _, a=action, v=version: self._kernel_confirm(a, v))
                    button.set_sensitive(entry['ready'] and helper)
                    row.append(button)
                panel.append(row)
                self.kernel_list.append(panel)
        self._job('kernels', read, done)

    def _kernel_confirm(self, action, version):
        text = '取消下次内核切换？' if action == 'cancel' else ('切换并立即重启？' if action == 'reboot' else '设置下一次启动内核？')
        detail = '恢复原有默认启动项。' if action == 'cancel' else f'目标：{version}\n只影响下一次启动。' + ('所有应用将关闭，请先保存工作。' if action == 'reboot' else '本次不重启。')
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, buttons=Gtk.ButtonsType.NONE, text=text, secondary_text=detail)
        dialog.add_button('返回', Gtk.ResponseType.CANCEL)
        dialog.add_button('确认并认证', Gtk.ResponseType.ACCEPT)
        def response(item, result):
            item.destroy()
            if result != Gtk.ResponseType.ACCEPT:
                return
            def work():
                args = ['pkexec', '/usr/libexec/ubuntu-support-kernel', action] + ([version] if version else [])
                result = subprocess.run(args, text=True, capture_output=True, timeout=180)
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or '认证取消或操作失败')
                return result.stdout.strip()
            def done(value, error):
                if error:
                    self._show_error('内核切换未完成', error)
                else:
                    self._set_status(value)
                self._kernel_refresh()
            self._job('kernel-action', work, done)
        dialog.connect('response', response)
        dialog.present()

    def _check_updates(self, button):
        button.set_sensitive(False)
        self.update_label.set_text('正在读取本地缓存…')
        def done(value, error):
            button.set_sensitive(True)
            self.update_label.set_text('读取失败：' + error if error else f'本地缓存中有 {value} 个可升级软件包；未进行在线刷新。')
        self._job('updates', system.count_upgradable_packages, done)

    def _refresh_processes(self):
        def done(items, error):
            if error:
                self._set_status('无法读取进程：' + error)
                return
            selected = self._selected_pid
            while child := self.process_listbox.get_first_child():
                self.process_listbox.remove(child)
            query = self.search.get_text().lower().strip()
            count = 0
            for item in items:
                if query and query not in item.name.lower() and query not in str(item.pid):
                    continue
                row = Gtk.ListBoxRow()
                row.pid = item.pid
                row.process_name = item.name
                grid = Gtk.Box(spacing=12)
                for index, text in enumerate((item.name, str(item.pid), f'{item.cpu:.1f}%', f'{item.memory:.1f}%')):
                    entry = Gtk.Label(label=text, xalign=0 if index == 0 else 1, ellipsize=3)
                    entry.set_size_request(220 if index == 0 else 80, 28)
                    entry.set_hexpand(index == 0)
                    grid.append(entry)
                row.set_child(grid)
                self.process_listbox.append(row)
                if item.pid == selected:
                    self.process_listbox.select_row(row)
                count += 1
                if count >= 30:
                    break
        self._job('processes', lambda: system.process_list(10000), done)
        return GLib.SOURCE_CONTINUE

    def _selected(self, _, row):
        self._selected_pid = row.pid if row else None
        self.end_button.set_sensitive(row is not None)

    def _end_process(self, *_):
        row = self.process_listbox.get_selected_row()
        if row is None:
            return
        pid, name = row.pid, row.process_name
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, buttons=Gtk.ButtonsType.NONE,
                                   message_type=Gtk.MessageType.WARNING, text=f'结束 {name}（{pid}）？',
                                   secondary_text='未保存的内容可能丢失。将发送正常结束信号。')
        dialog.add_button('取消', Gtk.ResponseType.CANCEL)
        dialog.add_button('结束进程', Gtk.ResponseType.ACCEPT)
        def response(item, choice):
            item.destroy()
            if choice == Gtk.ResponseType.ACCEPT:
                try:
                    if Path(f'/proc/{pid}/comm').read_text().strip() != name:
                        raise ValueError('进程已变化，请刷新后重试')
                    system.terminate_process(pid)
                    self._set_status(f'已请求结束 {name}')
                except Exception as exc:
                    self._show_error('无法结束进程', str(exc))
        dialog.connect('response', response)
        dialog.present()

    def _show_error(self, title, detail):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, buttons=Gtk.ButtonsType.CLOSE,
                                   message_type=Gtk.MessageType.ERROR, text=title, secondary_text=detail)
        dialog.connect('response', lambda item, _: item.destroy())
        dialog.present()


class UbuntuManagerApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='io.github.kingchou007.UbuntuSupport')

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = UbuntuManagerWindow(self)
            window._read_sleep()
            window._display_refresh()
            window._kernel_refresh()
        window.present()


def run():
    return UbuntuManagerApplication().run(None)
