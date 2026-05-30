import os
import shutil
import subprocess


def _paste_cmd_wayland() -> list[str]:
    if shutil.which("ydotool"):
        return ["ydotool", "key", "ctrl+v"]
    if shutil.which("wtype"):
        return ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]
    raise RuntimeError("No tool available to send Ctrl+V on Wayland (install ydotool or wtype)")


class ClipboardInjector:
    def inject(self, text: str) -> None:
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
            subprocess.run(_paste_cmd_wayland(), check=True, timeout=5)
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                check=True,
                timeout=5,
            )
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                check=True,
                timeout=5,
            )

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            if shutil.which("ydotool"):
                subprocess.run(["ydotool", "key"] + ["KEY_BACKSPACE"] * count, check=True, timeout=10)
            elif shutil.which("wtype"):
                args: list[str] = []
                for _ in range(count):
                    args += ["-k", "BackSpace"]
                subprocess.run(["wtype"] + args, check=True, timeout=10)
            else:
                raise RuntimeError("No tool available to send BackSpace on Wayland (install ydotool or wtype)")
        else:
            subprocess.run(
                ["xdotool", "key", "--repeat", str(count), "BackSpace"],
                check=True,
                timeout=10,
            )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            if shutil.which("ydotool"):
                subprocess.run(["ydotool", "key"] + keys, check=True, timeout=10)
            elif shutil.which("wtype"):
                args: list[str] = []
                for key in keys:
                    parts = key.split("+")
                    modifiers = parts[:-1]
                    key_name = parts[-1]
                    for mod in modifiers:
                        args += ["-M", mod]
                    args += ["-k", key_name]
                    for mod in modifiers:
                        args += ["-m", mod]
                subprocess.run(["wtype"] + args, check=True, timeout=10)
            else:
                raise RuntimeError("No tool available to send key sequence on Wayland (install ydotool or wtype)")
        else:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers"] + keys,
                check=True,
                timeout=10,
            )
