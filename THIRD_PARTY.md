# Third-party references

The project is distributed under GPL-2.0-only.

Razer fan HID report format and device protocol were derived from:
- TimandXiyu/razerblade-cli, GPL-2.0: https://github.com/TimandXiyu/razerblade-cli
- Original protocol research credited upstream to Ashcon Mohseninia / rnd-ash and OpenRazer.

This project implements a separate restricted Python service. It does not ship or install the upstream daemon, GPU undervolting, keyboard effects, or battery firmware commands.

GRUB once-only boot semantics:
https://www.gnu.org/software/grub/manual/grub/html_node/next_005fentry.html

The speaker amplifier sequence is referenced, not redistributed. Its upstream source and the exact locally verified SHA-256 are documented in docs/razer-speakers.md.
