"""Real GTK render smoke test, no privileged writes or reboot actions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib, Gio
from ubuntu_support.app import UbuntuManagerApplication, UbuntuManagerWindow

import os, json
from ubuntu_support import system
# Optional actual-host captures when rendering under virtual X11 (never fabricated).
if os.environ.get('SUPPORT_HARDWARE_SNAPSHOT'):
    hardware = json.loads(Path(os.environ['SUPPORT_HARDWARE_SNAPSHOT']).read_text())
    system.display_details = lambda: hardware['displays']
    system.gpu_snapshot = lambda: hardware['gpu']
app = UbuntuManagerApplication()
app.set_application_id('io.github.kingchou007.UbuntuSupport.Smoke')
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
window = UbuntuManagerWindow(app)
window.policy.enabled = False
window.auto_switch.set_active(False)
window._read_sleep()
window._display_refresh()
window._kernel_refresh()
if os.environ.get('SUPPORT_HARDWARE_SNAPSHOT'):
    window._gpu_check()
window.present()
loop = GLib.MainLoop()
page_names = ['overview', 'power', 'gpu', 'kernel', 'display', 'devices', 'processes']
errors = []
def screenshot():
    try:
        from PIL import ImageGrab
        import gi
        gi.require_version('GdkX11', '4.0')
        from gi.repository import GdkX11
        import subprocess, re
        xid = window.get_surface().get_xid()
        geometry = subprocess.check_output(['xwininfo', '-id', str(xid)], text=True)
        x = int(re.search(r'Absolute upper-left X:\s+(-?\d+)', geometry)[1])
        y = int(re.search(r'Absolute upper-left Y:\s+(-?\d+)', geometry)[1])
        width = int(re.search(r'Width:\s+(\d+)', geometry)[1])
        height = int(re.search(r'Height:\s+(\d+)', geometry)[1])
        name = window.stack.get_visible_child_name()
        ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(str(Path(__file__).parent / 'screenshots' / (name + '.png')))
        print('RENDERED', name, window.get_width(), window.get_height(), flush=True)
    except Exception as exc:
        print('RENDER_ERROR', repr(exc), flush=True)
        errors.append(str(exc))
    GLib.timeout_add(100, advance)
    return GLib.SOURCE_REMOVE

def advance():
    if not page_names:
        window.close()
        loop.quit()
        return GLib.SOURCE_REMOVE
    window.present()
    name = page_names.pop(0)
    window.set_default_size(1080, 1160 if name == 'power' else 1040 if name == 'gpu' else 900)
    window.stack.set_visible_child_name(name)
    GLib.timeout_add(700, screenshot)
    return GLib.SOURCE_REMOVE
GLib.timeout_add(2500, advance)
loop.run()
if errors:
    raise SystemExit(1)
