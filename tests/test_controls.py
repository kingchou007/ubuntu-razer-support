from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
import tempfile

from ubuntu_support import system, kernel_helper, fan_service


class PowerTests(TestCase):
    def test_unplug_and_restore(self):
        p = system.PowerPolicy()
        modes = ['performance', 'balanced', 'power-saver']
        self.assertIsNone(p.target(True, 'performance', modes))
        self.assertEqual(p.target(False, 'performance', modes), 'power-saver')
        self.assertIsNone(p.target(False, 'power-saver', modes))
        self.assertEqual(p.target(True, 'power-saver', modes), 'performance')

    def test_unknown_disabled_and_missing_profile(self):
        p = system.PowerPolicy()
        self.assertIsNone(p.target(None, 'balanced', ['balanced']))
        self.assertIsNone(p.target(False, 'balanced', ['balanced']))
        p.enabled = False
        self.assertIsNone(p.target(True, 'power-saver', ['balanced']))

    def test_ignore_mouse_battery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, values in {'AC0': {'type': 'Mains', 'online': '0'}, 'BAT0': {'type': 'Battery', 'capacity': '73', 'status': 'Discharging'}, 'mouse': {'type': 'Battery', 'scope': 'Device', 'capacity': '5'}}.items():
                (root / name).mkdir()
                for key, value in values.items():
                    (root / name / key).write_text(value)
            power = system.power_supply(root)
            self.assertFalse(power.on_ac)
            self.assertEqual(power.percent, 73)


class KernelTests(TestCase):
    def test_only_installed_advanced_normal_entries(self):
        cfg = """submenu 'Advanced options for Ubuntu' $menuentry_id_option 'gnulinux-advanced-abc' {
 menuentry 'Ubuntu' $menuentry_id_option 'gnulinux-6.8.1-1058-realtime-advanced-abc' {
 }
 menuentry 'recovery' $menuentry_id_option 'gnulinux-6.8.1-1058-realtime-recovery-abc' {
 }
}
menuentry 'other' $menuentry_id_option 'gnulinux-6.8.0-1-generic-advanced-abc' {
}
"""
        entries = kernel_helper.parse_entries(cfg)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['version'], '6.8.1-1058-realtime')
        self.assertEqual(entries[0]['entry'], 'gnulinux-advanced-abc>gnulinux-6.8.1-1058-realtime-advanced-abc')

    @patch.object(kernel_helper.os, 'geteuid', return_value=0)
    @patch.object(kernel_helper, 'command')
    def test_arbitrary_arguments_rejected(self, command, _):
        for args in [['reboot', '../etc/passwd'], ['schedule', '$(touch x)'], ['execute', '6.8.0-generic']]:
            with self.assertRaises(ValueError):
                kernel_helper.main(args)
        command.assert_not_called()

    @patch.object(kernel_helper.os, 'geteuid', return_value=0)
    @patch.object(kernel_helper, 'validate_boot_environment')
    @patch.object(kernel_helper, 'inventory', return_value=[{'version': '6.8.0-1-generic', 'ready': False}])
    @patch.object(kernel_helper, 'command')
    def test_incomplete_kernel_cannot_schedule(self, command, *_):
        with self.assertRaises(RuntimeError):
            kernel_helper.main(['schedule', '6.8.0-1-generic'])
        command.assert_not_called()

    @patch.object(kernel_helper.os, 'geteuid', return_value=0)
    @patch.object(kernel_helper, 'validate_boot_environment')
    @patch.object(kernel_helper, 'inventory', return_value=[{'version': '6.8.0-1-generic', 'ready': True, 'entry': 'submenu>target'}])
    @patch.object(kernel_helper, 'pending', side_effect=['old', 'submenu>target'])
    def test_failed_reboot_restores_previous_pending(self, *_):
        calls = []
        def run(args):
            calls.append(args)
            if args == ['/usr/bin/systemctl', 'reboot']:
                raise RuntimeError('blocked')
            return ''
        with patch.object(kernel_helper, 'command', side_effect=run):
            with self.assertRaises(RuntimeError):
                kernel_helper.main(['reboot', '6.8.0-1-generic'])
        self.assertEqual(calls[-1], ['/usr/bin/grub-editenv', '/boot/grub/grubenv', 'set', 'next_entry=old'])


class FanTests(TestCase):
    def test_packet_layout_and_checksum(self):
        packet = fan_service.report(0x0d, 0x88, 4, [0, 1])
        self.assertEqual(len(packet), 91)
        self.assertEqual(list(packet[6:11]), [4, 13, 136, 0, 1])
        self.assertEqual(packet[89], 4 ^ 13 ^ 136 ^ 1)

    @patch.object(fan_service, 'ac_online', return_value=True)
    @patch.object(fan_service, 'thermal_safe', return_value=True)
    def test_lease_owner_and_expiry(self, *_):
        fans = Mock()
        control = fan_service.FanController(fans)
        request = {'action': 'manual', 'rpm': 4000, 'owner': 1000}
        with self.assertRaises(PermissionError):
            control.handle(request, 1000, 0)
        control.handle(request, 0, 0)
        with self.assertRaises(PermissionError):
            control.handle({'action': 'keepalive'}, 1001, 10)
        control.handle({'action': 'keepalive'}, 1000, 10)
        control.tick(29)
        fans.auto.assert_not_called()
        control.tick(31)
        fans.auto.assert_called_once()
        self.assertIsNone(control.owner)

    @patch.object(fan_service, 'ac_online', return_value=False)
    def test_battery_refuses_manual_and_resets_owned_session(self, _):
        fans = Mock()
        control = fan_service.FanController(fans)
        with self.assertRaises(RuntimeError):
            control.handle({'action': 'manual', 'rpm': 4000, 'owner': 1000}, 0, 0)
        fans.manual.assert_not_called()
        control.owner = 1000
        control.tick(1)
        fans.auto.assert_called_once()

    @patch.object(fan_service, 'ac_online', return_value=True)
    @patch.object(fan_service, 'thermal_safe', return_value=False)
    def test_heat_returns_control_to_firmware(self, *_):
        fans = Mock()
        control = fan_service.FanController(fans)
        control.owner, control.expires = 1000, 30
        control.tick(1)
        fans.auto.assert_called_once()

    @patch.object(fan_service, 'ac_online', return_value=True)
    @patch.object(fan_service, 'thermal_safe', return_value=True)
    def test_noise_ceiling_cannot_be_exceeded(self, *_):
        fans = Mock()
        control = fan_service.FanController(fans)
        with self.assertRaises(ValueError):
            control.handle({'action': 'manual', 'rpm': 4000, 'limit': 3000, 'owner': 1000}, 0, 0)
        fans.manual.assert_not_called()

    def test_rpm_range_rejected_before_hardware_write(self):
        fans = object.__new__(fan_service.RazerFans)
        fans.transfer = Mock()
        for rpm in [0, -100, 2500, 4900, 3501, '4000']:
            with self.assertRaises(ValueError):
                fans.manual(rpm)
        fans.transfer.assert_not_called()


class NvidiaTests(TestCase):
    def test_graphics_and_compute_processes(self):
        result = system.parse_gpu_xml('''<nvidia_smi_log><driver_version>580</driver_version><gpu><product_name>RTX</product_name><temperature><gpu_temp>50 C</gpu_temp></temperature><utilization><gpu_util>12 %</gpu_util></utilization><gpu_power_readings><power_draw>16 W</power_draw></gpu_power_readings><processes><process_info><pid>42</pid><process_name>Xorg</process_name><type>G</type><used_memory>165 MiB</used_memory></process_info></processes></gpu></nvidia_smi_log>''')
        self.assertEqual(result['power'], '16 W')
        self.assertEqual(result['processes'][0]['type'], 'G')
        self.assertEqual(result['memory_total'], 'N/A')
