import subprocess


class XdotoolInjector:
    def inject(self, text: str) -> None:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text],
            check=True,
            timeout=10,
        )

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        subprocess.run(
            ["xdotool", "key", "--repeat", str(count), "BackSpace"],
            check=True,
            timeout=10,
        )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers"] + keys,
            check=True,
            timeout=10,
        )
