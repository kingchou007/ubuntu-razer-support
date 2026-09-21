#!/usr/bin/python3 -I
"""Restricted privileged helper. Installed root-owned, with no user-code imports."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SAFE_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}
VERSION = re.compile(r'[0-9][0-9A-Za-z.+~-]*-(?:generic|realtime)\Z')


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, env=SAFE_ENV)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or '系统命令失败')
    return result.stdout.strip()


def parse_entries(text):
    """Accept only generated Ubuntu advanced Linux entries, using stable GRUB IDs."""
    submenu = None
    entries = []
    for line in text.splitlines():
        if line.startswith('submenu '):
            match = re.search(r"\$menuentry_id_option '(gnulinux-advanced-[A-Za-z0-9-]+)'", line)
            submenu = match[1] if match else None
        elif line.startswith('}'):
            submenu = None
        if submenu and line.lstrip().startswith('menuentry '):
            match = re.search(r"\$menuentry_id_option '(gnulinux-(.+)-advanced-[A-Za-z0-9-]+)'", line)
            if match and VERSION.fullmatch(match[2]):
                entries.append({'version': match[2], 'entry': submenu + '>' + match[1]})
    return entries


def inventory(boot=Path('/boot'), modules=Path('/lib/modules')):
    cfg = (boot / 'grub/grub.cfg').read_text()
    entries = parse_entries(cfg)
    nvidia = any(p.read_text().strip() == '0x10de' for p in Path('/sys/bus/pci/devices').glob('*/vendor'))
    for entry in entries:
        version = entry['version']
        problems = []
        for name in ('vmlinuz-', 'initrd.img-'):
            if not (boot / (name + version)).is_file():
                problems.append('缺少 ' + name.rstrip('-'))
        if not (modules / version).is_dir():
            problems.append('缺少内核模块目录')
        if nvidia:
            try:
                command(['/usr/sbin/modinfo', '-k', version, '-F', 'filename', 'nvidia'])
            except (RuntimeError, OSError, subprocess.SubprocessError):
                problems.append('未检测到对应 NVIDIA 模块')
        entry['problems'] = problems
        entry['ready'] = not problems
    return entries


def pending():
    text = command(['/usr/bin/grub-editenv', '/boot/grub/grubenv', 'list'])
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line).get('next_entry', '')


def validate_boot_environment():
    cfg = Path('/boot/grub/grub.cfg').read_text()
    if 'save_env next_entry' not in cfg or 'set default="${next_entry}"' not in cfg:
        raise RuntimeError('当前 GRUB 配置未提供一次性启动支持')
    fstype = command(['/usr/bin/findmnt', '-n', '-o', 'FSTYPE', '-T', '/boot/grub/grubenv'])
    source = command(['/usr/bin/findmnt', '-n', '-o', 'SOURCE', '-T', '/boot/grub/grubenv'])
    if fstype not in ('ext2', 'ext3', 'ext4', 'vfat') or source.startswith(('/dev/mapper/', '/dev/md', '/dev/dm-')):
        raise RuntimeError('当前启动分区尚未验证一次性启动后的自动恢复能力')


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if args == ['list']:
        print(json.dumps(inventory(), ensure_ascii=False))
        return
    if os.geteuid() != 0:
        raise RuntimeError('此操作需要系统管理员认证')
    if args == ['cancel']:
        command(['/usr/bin/grub-editenv', '/boot/grub/grubenv', 'unset', 'next_entry'])
        if pending():
            raise RuntimeError('取消失败，启动项仍存在')
        print('已取消下次启动切换，恢复原有默认项')
        return
    if len(args) != 2 or args[0] not in ('schedule', 'reboot') or not VERSION.fullmatch(args[1]):
        raise ValueError('无效操作或内核版本')
    validate_boot_environment()
    selected = next((entry for entry in inventory() if entry['version'] == args[1]), None)
    if not selected or not selected['ready']:
        raise RuntimeError('目标内核不在可用启动列表中，或缺少启动文件 / NVIDIA 模块')
    # Revalidate against root-owned config at execution; no arbitrary menu IDs accepted.
    old = pending()
    try:
        command(['/usr/sbin/grub-reboot', selected['entry']])
        if pending() != selected['entry']:
            raise RuntimeError('启动项回读验证失败')
        if args[0] == 'reboot':
            command(['/usr/bin/systemctl', 'reboot'])
    except Exception:
        if old:
            command(['/usr/bin/grub-editenv', '/boot/grub/grubenv', 'set', 'next_entry=' + old])
        else:
            command(['/usr/bin/grub-editenv', '/boot/grub/grubenv', 'unset', 'next_entry'])
        raise
    print('下次启动已设为 ' + args[1] + '；原有默认内核保持不变')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
