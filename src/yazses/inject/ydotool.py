import subprocess


class YdotoolInjector:
    def inject(self, text: str) -> None:
        subprocess.run(["ydotool", "type", "--", text], check=True, timeout=10)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        subprocess.run(
            ["ydotool", "key"] + ["KEY_BACKSPACE"] * count,
            check=True,
            timeout=10,
        )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        subprocess.run(["ydotool", "key"] + keys, check=True, timeout=10)
