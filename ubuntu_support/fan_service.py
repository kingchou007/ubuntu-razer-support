#!/usr/bin/python3 -I
"""Razer 1532:02b7 fan interface. Protocol reference: TimandXiyu/razerblade-cli (GPL-2.0).
Only fan telemetry and bounded manual RPM; no raw arbitrary hardware operations.
"""
import fcntl
import json
import os
from pathlib import Path
import time

LENGTH = 91
SET_FEATURE = 0xC0000000 | (LENGTH << 16) | (ord('H') << 8) | 0x06
GET_FEATURE = 0xC0000000 | (LENGTH << 16) | (ord('H') << 8) | 0x07


def report(cls, cmd, size, args):
    packet = bytearray(LENGTH)
    packet[2] = 0x1f
    packet[6], packet[7], packet[8] = size, cls, cmd
    packet[9:9 + len(args)] = bytes(args)
    for value in packet[3:89]:
        packet[89] ^= value
    return packet


class RazerFans:
    def __init__(self):
        self.fd = None
        self.path = None
        for device in sorted(Path('/sys/class/hidraw').glob('hidraw*')):
            try:
                info = (device / 'device/uevent').read_text().upper()
                if 'HID_ID=0003:00001532:000002B7' not in info:
                    continue
                fd = os.open('/dev/' + device.name, os.O_RDWR | os.O_CLOEXEC)
                self.fd = fd
                self.path = '/dev/' + device.name
                self.transfer(0x00, 0x81, 0x02, [])
                return
            except (OSError, RuntimeError):
                self.close()
        raise RuntimeError('未找到可访问的 Razer Blade 16 (1532:02b7) 控制接口')

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def transfer(self, cls, cmd, size, args):
        packet = report(cls, cmd, size, args)
        fcntl.ioctl(self.fd, SET_FEATURE, packet, True)
        time.sleep(.06)
        reply = bytearray(LENGTH)
        fcntl.ioctl(self.fd, GET_FEATURE, reply, True)
        if reply[1] != 2 or reply[7] != cls or reply[8] != cmd:
            raise RuntimeError(f'设备响应失败：状态 {reply[1]:02x}，命令 {reply[7]:02x}/{reply[8]:02x}')
        return reply

    def status(self):
        mode = self.transfer(0x0d, 0x82, 4, [0, 1])
        readings = [self.transfer(0x0d, 0x88, 4, [0, zone])[11] * 100 for zone in (1, 2)]
        if any(value > 10000 for value in readings):
            raise RuntimeError('风扇转速超出可信范围')
        return {'rpm': readings, 'mode': mode[11], 'manual': bool(mode[12]), 'device': self.path}

    def auto(self):
        mode = self.transfer(0x0d, 0x82, 4, [0, 1])[11]
        if mode > 3:
            raise RuntimeError('未知性能模式，拒绝修改')
        for zone in (1, 2):
            self.transfer(0x0d, 0x02, 4, [0, zone, mode, 0])

    def manual(self, rpm):
        if not isinstance(rpm, int) or not 3000 <= rpm <= 4800 or rpm % 100:
            raise ValueError('手动转速必须为 3000–4800 RPM，步长 100')
        mode = self.transfer(0x0d, 0x82, 4, [0, 1])[11]
        if mode > 3:
            raise RuntimeError('未知性能模式，拒绝修改')
        try:
            for zone in (1, 2):
                self.transfer(0x0d, 0x02, 4, [0, zone, mode, 1])
                self.transfer(0x0d, 0x01, 3, [1, zone, rpm // 100])
        except Exception:
            self.auto()
            raise



import signal
import socket
import struct
import subprocess
import sys

SOCKET = '/run/ubuntu-support/fan.sock'
STATUS = Path('/run/ubuntu-support/fans.json')


def ac_online():
    values = []
    for path in Path('/sys/class/power_supply').glob('*/online'):
        try:
            values.append(path.read_text().strip() == '1')
        except OSError:
            pass
    return any(values)


def thermal_safe():
    cpu = []
    for path in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            if (path / 'type').read_text().strip() in ('x86_pkg_temp', 'TCPU', 'TCPU_PCI'):
                cpu.append(int((path / 'temp').read_text()) / 1000)
        except (OSError, ValueError):
            pass
    if not cpu or max(cpu) >= 85:
        return False
    for path in Path('/sys/bus/pci/devices').glob('*'):
        try:
            if (path / 'vendor').read_text().strip() != '0x10de' or not (path / 'class').read_text().startswith('0x03'):
                continue
            if (path / 'power/runtime_status').read_text().strip() != 'active':
                continue
            proc = subprocess.run(['/usr/bin/nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3)
            if proc.returncode or any(float(x.strip()) >= 80 for x in proc.stdout.splitlines()):
                return False
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
    return True


class FanController:
    def __init__(self, fans):
        self.fans = fans
        self.owner = None
        self.expires = 0
        self.target = None
        self.reason = '固件自动控制'

    def automatic(self, reason):
        self.fans.auto()
        self.owner, self.target = None, None
        self.reason = reason

    def handle(self, request, uid, now):
        action = request.get('action')
        if action == 'manual':
            if uid != 0:
                raise PermissionError('调速需要系统认证')
            rpm = request.get('rpm')
            ceiling = request.get('limit', 4800)
            if not isinstance(ceiling, int) or not 3000 <= ceiling <= 4800 or not isinstance(rpm, int) or rpm > ceiling:
                raise ValueError('目标转速不得超过静音上限')
            owner = request.get('owner')
            if not isinstance(owner, int) or owner < 0:
                raise ValueError('无效用户')
            if not ac_online():
                raise RuntimeError('电池供电时使用固件自动风扇')
            if not thermal_safe():
                raise RuntimeError('当前温度较高或传感器不可用，保留自动散热')
            self.fans.manual(rpm)
            self.owner, self.target, self.expires = owner, rpm, now + 20
            self.reason = f'手动目标 {rpm} RPM'
        elif action == 'keepalive':
            if self.owner is None or uid != self.owner:
                raise PermissionError('没有属于此用户的手动控制会话')
            self.expires = now + 20
        elif action == 'auto':
            if uid != 0 and (self.owner is None or uid != self.owner):
                raise PermissionError('恢复自动需要控制会话或系统认证')
            self.automatic('已恢复固件自动控制')
        else:
            raise ValueError('不支持的风扇操作')

    def tick(self, now):
        if self.owner is None:
            return
        if not ac_online():
            self.automatic('已拔电，恢复自动控制')
        elif now >= self.expires:
            self.automatic('管理器连接已结束，恢复自动控制')
        elif not thermal_safe():
            self.automatic('温度保护：恢复固件自动控制')


def send_request(request):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(10)
        client.connect(SOCKET)
        client.sendall(json.dumps(request).encode() + b'\n')
        response = client.recv(4096)
    value = json.loads(response)
    if not value.get('ok'):
        raise RuntimeError(value.get('error', '风扇操作失败'))
    return value


def serve():
    STATUS.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        os.unlink(SOCKET)
    except FileNotFoundError:
        pass
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server = socket.socket(socket.AF_UNIX)
    server.bind(SOCKET)
    os.chmod(SOCKET, 0o666)
    server.listen(4)
    server.settimeout(1)
    controller = None
    next_tick = 0
    try:
        while running:
            if time.monotonic() >= next_tick:
                state = {'timestamp': time.time()}
                try:
                    if controller is None:
                        controller = FanController(RazerFans())
                        controller.automatic('固件自动控制')
                    controller.tick(time.monotonic())
                    state.update(controller.fans.status())
                    state.update(target=controller.target, owner=controller.owner, reason=controller.reason, available=True)
                except Exception as exc:
                    state.update(available=False, error=str(exc))
                    if controller:
                        try:
                            controller.automatic('设备重新连接')
                        except Exception:
                            pass
                        controller.fans.close()
                    controller = None
                temporary = STATUS.with_suffix('.tmp')
                temporary.write_text(json.dumps(state, ensure_ascii=False))
                os.chmod(temporary, 0o644)
                temporary.replace(STATUS)
                next_tick = time.monotonic() + 3
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            with client:
                client.settimeout(2)
                try:
                    _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    raw = client.recv(1024)
                    request = json.loads(raw)
                    if not isinstance(request, dict):
                        raise ValueError('无效请求')
                    if controller is None:
                        raise RuntimeError('风扇硬件尚未就绪')
                    controller.handle(request, uid, time.monotonic())
                    response = {'ok': True}
                    if request.get('action') != 'keepalive':
                        next_tick = 0
                except Exception as exc:
                    response = {'ok': False, 'error': str(exc)}
                try:
                    client.sendall(json.dumps(response).encode())
                except OSError:
                    pass
    finally:
        if controller:
            try:
                controller.automatic('服务停止，恢复自动控制')
            finally:
                controller.fans.close()
        server.close()
        Path(SOCKET).unlink(missing_ok=True)
        STATUS.unlink(missing_ok=True)


def main():
    args = sys.argv[1:]
    if args == ['--daemon']:
        if os.geteuid() != 0:
            raise PermissionError('服务需要管理员权限')
        serve()
    elif len(args) == 4 and args[0] == '--set' and args[2] == '--limit':
        if os.geteuid() != 0:
            raise PermissionError('调速需要管理员认证')
        uid = int(os.environ.get('PKEXEC_UID', '0'))
        send_request({'action': 'manual', 'rpm': int(args[1]), 'limit': int(args[3]), 'owner': uid})
        print('手动风扇目标已发送')
    elif args == ['--auto']:
        send_request({'action': 'auto'})
        print('已恢复固件自动控制')
    elif not args or args == ['--probe']:
        fans = RazerFans()
        try:
            print(json.dumps(fans.status()))
        finally:
            fans.close()
    else:
        raise ValueError('无效风扇操作')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
