from pathlib import Path
import tempfile
import unittest

from ubuntu_support import system


class SystemHelpersTest(unittest.TestCase):
    def test_cpu_percent(self):
        previous = system.CpuSample(idle=100, total=200)
        current = system.CpuSample(idle=125, total=300)
        self.assertEqual(system.cpu_percent(previous, current), 75.0)

    def test_memory_percent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meminfo"
            path.write_text("MemTotal: 1048576 kB\nMemAvailable: 262144 kB\n", encoding="utf-8")
            percent, used, total = system.memory_percent(path)
        self.assertEqual(percent, 75.0)
        self.assertEqual(used, 0.75)
        self.assertEqual(total, 1.0)

    def test_temperature_state(self):
        self.assertEqual(system.temperature_state(55), ("55°C · 正常", "good"))
        self.assertEqual(system.temperature_state(85), ("85°C · 较热", "warning"))
        self.assertEqual(system.temperature_state(None), ("温度不可用", "neutral"))

    def test_uptime_format(self):
        self.assertEqual(system.format_uptime(120), "2 分钟")
        self.assertEqual(system.format_uptime(3 * 3600 + 60), "3 小时 1 分钟")


if __name__ == "__main__":
    unittest.main()
