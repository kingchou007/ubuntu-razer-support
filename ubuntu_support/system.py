"""Read-only system inspection helpers and narrowly scoped system actions."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Iterable


@dataclass(frozen=True)
class CpuSample:
    idle: int
    total: int


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    cpu: float
    memory: float


@dataclass(frozen=True)
class TemperatureInfo:
    label: str
    celsius: float


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def cpu_sample(proc_stat: Path = Path("/proc/stat")) -> CpuSample:
    fields = _read_text(proc_stat).splitlines()[0].split()
    if not fields or fields[0] != "cpu":
        raise ValueError("无法读取 CPU 统计信息")
    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return CpuSample(idle=idle, total=sum(values))


def cpu_percent(previous: CpuSample, current: CpuSample) -> float:
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def memory_percent(meminfo: Path = Path("/proc/meminfo")) -> tuple[float, float, float]:
    values: dict[str, int] = {}
    for line in _read_text(meminfo).splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0])
    total_kib = values["MemTotal"]
    available_kib = values.get("MemAvailable", values.get("MemFree", 0))
    used_kib = total_kib - available_kib
    percent = used_kib / total_kib * 100 if total_kib else 0.0
    gib = 1024 * 1024
    return percent, used_kib / gib, total_kib / gib


def uptime_seconds(path: Path = Path("/proc/uptime")) -> float:
    return float(_read_text(path).split()[0])


def format_uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分钟"
    return f"{minutes} 分钟"


def load_average(path: Path = Path("/proc/loadavg")) -> tuple[float, float, float]:
    first, second, third, *_ = _read_text(path).split()
    return float(first), float(second), float(third)


def temperatures(thermal_root: Path = Path("/sys/class/thermal")) -> list[TemperatureInfo]:
    readings: list[TemperatureInfo] = []
    preferred = {"x86_pkg_temp", "TCPU", "TCPU_PCI", "acpitz"}
    for zone in sorted(thermal_root.glob("thermal_zone*")):
        try:
            label = _read_text(zone / "type")
            raw = float(_read_text(zone / "temp"))
        except (OSError, ValueError):
            continue
        celsius = raw / 1000.0 if raw > 1000 else raw
        if label in preferred and 0 < celsius < 150:
            readings.append(TemperatureInfo(label, celsius))
    return readings


def cpu_temperature(readings: Iterable[TemperatureInfo] | None = None) -> float | None:
    values = list(readings if readings is not None else temperatures())
    direct = [item.celsius for item in values if item.label in {"x86_pkg_temp", "TCPU", "TCPU_PCI"}]
    fallback = [item.celsius for item in values]
    return max(direct or fallback) if (direct or fallback) else None


def fan_speeds(hwmon_root: Path = Path("/sys/class/hwmon")) -> list[int]:
    speeds: list[int] = []
    for path in sorted(hwmon_root.glob("hwmon*/fan*_input")):
        try:
            value = int(_read_text(path))
        except (OSError, ValueError):
            continue
        if value >= 0:
            speeds.append(value)
    return speeds


def process_list(limit: int = 20) -> list[ProcessInfo]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,comm=,%cpu=,%mem=", "--sort=-%cpu"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    processes: list[ProcessInfo] = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 3)
        if len(fields) != 4:
            continue
        try:
            info = ProcessInfo(int(fields[0]), fields[1], float(fields[2]), float(fields[3]))
        except ValueError:
            continue
        if info.pid != os.getpid():
            processes.append(info)
        if len(processes) >= limit:
            break
    return processes


def terminate_process(pid: int) -> None:
    if pid <= 1 or pid == os.getpid():
        raise ValueError("拒绝结束关键系统进程")
    os.kill(pid, signal.SIGTERM)


def active_power_profile() -> str | None:
    try:
        result = subprocess.run(
            ["powerprofilesctl", "get"], check=True, capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def available_power_profiles() -> list[str]:
    try:
        result = subprocess.run(
            ["powerprofilesctl", "list"], check=True, capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    profiles: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip().lstrip("*").strip()
        if stripped.endswith(":"):
            name = stripped[:-1]
            if name in {"power-saver", "balanced", "performance"}:
                profiles.append(name)
    return profiles


def set_power_profile(profile: str) -> None:
    if profile not in {"power-saver", "balanced", "performance"}:
        raise ValueError("无效的电源模式")
    subprocess.run(["powerprofilesctl", "set", profile], check=True, timeout=10)


def count_upgradable_packages() -> int:
    result = subprocess.run(
        ["apt", "list", "--upgradable"],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "LC_ALL": "C"},
    )
    return sum(1 for line in result.stdout.splitlines() if "/" in line and not line.startswith("Listing"))


def launch_update_manager() -> None:
    subprocess.Popen(
        ["update-manager"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def temperature_state(celsius: float | None) -> tuple[str, str]:
    if celsius is None:
        return "温度不可用", "neutral"
    if celsius >= 90:
        return f"{celsius:.0f}°C · 过热", "danger"
    if celsius >= 80:
        return f"{celsius:.0f}°C · 较热", "warning"
    if celsius >= 65:
        return f"{celsius:.0f}°C · 温暖", "warm"
    return f"{celsius:.0f}°C · 正常", "good"


def timestamp() -> str:
    return time.strftime("%H:%M:%S")



@dataclass(frozen=True)
class PowerSupply:
    on_ac: bool | None
    percent: int | None
    status: str


def power_supply(root: Path = Path('/sys/class/power_supply')) -> PowerSupply:
    online: list[bool] = []
    batteries = []
    for path in sorted(root.glob('*')):
        try:
            kind = _read_text(path / 'type')
            if kind in {'Mains', 'USB', 'USB_C', 'USB_PD'} and (path / 'online').exists():
                online.append(_read_text(path / 'online') == '1')
            elif kind == 'Battery':
                scope = _read_text(path / 'scope') if (path / 'scope').exists() else ''
                if scope != 'Device' and not path.name.startswith('hidpp'):
                    batteries.append(path)
        except OSError:
            continue
    percent, status = None, '未检测到内置电池'
    if batteries:
        try:
            percent = int(_read_text(batteries[0] / 'capacity'))
            status = _read_text(batteries[0] / 'status')
        except (OSError, ValueError):
            status = '无法读取电池'
    ac = any(online) if online else (False if status == 'Discharging' else None)
    return PowerSupply(ac, percent, status)


def display_summary(root: Path = Path('/sys/class/drm')) -> str:
    lines = []
    for path in sorted(root.glob('card*-*')):
        try:
            if _read_text(path / 'status') != 'connected':
                continue
            card = path.name.split('-')[0]
            vendor = _read_text(root / card / 'device/vendor')
            gpu = {'0x8086': 'Intel 核显', '0x10de': 'NVIDIA 独显', '0x1002': 'AMD'}.get(vendor, '显卡')
            lines.append(f'{path.name} · {gpu}')
        except OSError:
            continue
    return '\n'.join(lines) or '未读取到已连接显示器'


def gpu_summary() -> str:
    # Explicit user action only: polling nvidia-smi can wake a sleeping GPU.
    result = subprocess.run(['nvidia-smi', '--query-gpu=name,temperature.gpu,utilization.gpu,power.draw,memory.used',
                             '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'NVIDIA 驱动未就绪或设备不可用')
    rows = []
    for line in result.stdout.splitlines():
        fields = [value.strip() for value in line.split(',')]
        if len(fields) == 5:
            name, temp, utilization, power, memory = fields
            rows.append(f'{name}\n温度 {temp}°C · 使用率 {utilization}%\n功耗 {power} W · 显存 {memory} MiB')
    processes = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=10)
    if processes.returncode == 0 and 'Processes:' in processes.stdout:
        rows.append('当前占用进程（驱动提供的信息）：\n' + processes.stdout.split('Processes:', 1)[1].strip())
    return '\n\n'.join(rows) or '未检测到 NVIDIA 显卡'


class PowerPolicy:
    """Only change profiles on source transitions; never guess unknown AC state."""
    def __init__(self):
        self.enabled = True
        self.last_ac = None
        self.ac_profile = 'balanced'

    def target(self, ac: bool | None, current: str | None, available: list[str]) -> str | None:
        if not self.enabled or ac is None or current is None:
            return None
        if self.last_ac == ac:
            return None
        previous = self.last_ac
        self.last_ac = ac
        if ac:
            if previous is None:
                self.ac_profile = current
                return None
            target = self.ac_profile
        else:
            if previous is True or current != 'power-saver':
                self.ac_profile = current
            target = 'power-saver'
        return target if target in available and target != current else None

    def retry(self):
        self.last_ac = None


def gpu_snapshot():
    import xml.etree.ElementTree as ET
    result = subprocess.run(['nvidia-smi', '-q', '-x'], capture_output=True, text=True, timeout=15, check=True)
    return parse_gpu_xml(result.stdout)


def parse_gpu_xml(text):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    gpu = root.find('gpu')
    if gpu is None:
        raise ValueError('没有检测到 NVIDIA 显卡')
    def field(path):
        return gpu.findtext(path, 'N/A')
    power = field('gpu_power_readings/power_draw')
    if power == 'N/A':
        power = field('gpu_power_readings/instant_power_draw')
    if power == 'N/A':
        power = field('gpu_power_readings/average_power_draw')
    if power == 'N/A':
        power = field('power_readings/power_draw')
    return {'name': field('product_name'), 'driver': root.findtext('driver_version', '—'),
            'temperature': field('temperature/gpu_temp'), 'utilization': field('utilization/gpu_util'),
            'power': power, 'memory_used': field('fb_memory_usage/used'), 'memory_total': field('fb_memory_usage/total'),
            'state': field('performance_state'), 'processes': [
                {'pid': item.findtext('pid', '—'), 'name': item.findtext('process_name', '—'),
                 'memory': item.findtext('used_memory', 'N/A'), 'type': item.findtext('type', '—')}
                for item in gpu.findall('processes/process_info')]}


def gpu_awake():
    for path in Path('/sys/bus/pci/devices').glob('*'):
        try:
            if _read_text(path / 'vendor') == '0x10de' and _read_text(path / 'class').startswith('0x03'):
                return _read_text(path / 'power/runtime_status') == 'active'
        except OSError:
            continue
    return False


def display_details():
    import re
    result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True, timeout=5, check=True)
    displays = []
    current = None
    for line in result.stdout.splitlines():
        if not line.startswith(' '):
            current = None
            match = re.match(r'(\S+) connected\b(.*)', line)
            if match:
                current = {'name': match[1], 'primary': 'primary' in match[2], 'mode': '已连接，未启用', 'rate': '—'}
                displays.append(current)
        elif current and '*' in line:
            fields = line.split()
            current['mode'] = fields[0]
            current['rate'] = next((x.replace('*', '').replace('+', '') for x in fields[1:] if '*' in x), '—') + ' Hz'
    return displays
