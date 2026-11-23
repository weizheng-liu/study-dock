"""Open a dedicated browser profile, keeping school logins in that browser."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8840"


def ready():
    try:
        with urlopen(URL + "/api/health", timeout=2) as response:
            value = json.load(response)
            return isinstance(value, dict) and value.get("app") == "study-dock" and value.get("browser_collector") is True
    except (OSError, ValueError, URLError):
        return False


def ensure_portal():
    if ready():
        return None
    (ROOT / "data").mkdir(exist_ok=True)
    with (ROOT / "data" / "launcher.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(50):
        if ready():
            return process
        time.sleep(0.2)
    raise RuntimeError("学习空间启动失败，请检查 8840 端口。详情见 data/launcher.log。")


def main():
    parser = argparse.ArgumentParser(description="打开学习空间和浏览器采集助手")
    parser.add_argument("--browser", choices=("edge", "chrome"), default="edge")
    parser.add_argument("--portal-only", action="store_true", help="后台启动学习空间并打开网页")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("此便捷启动器用于 Windows。其他系统请手动加载 extension 文件夹。")
    if args.portal_only:
        ensure_portal()
        webbrowser.open(URL + "/#assistant")
        return
    if args.browser == "chrome":
        executable = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"
    else:
        executable = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
    if not executable.exists():
        raise SystemExit("没有找到所选浏览器，请按 README 手动加载插件。")
    process = None
    try:
        process = ensure_portal()
        manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
        identifier = "".join(chr(97 + int(char, 16)) for char in digest)
        profile = ROOT / "data" / ("collector-chrome" if args.browser == "chrome" else "collector-browser")
        command = [str(executable), "--user-data-dir=" + str(profile), "--no-first-run", "--no-default-browser-check"]
        if args.browser == "edge":
            command.extend(["--disable-extensions-except=" + str(ROOT / "extension"), "--load-extension=" + str(ROOT / "extension")])
        command.extend(["chrome-extension://" + identifier + "/popup.html", URL + "/#connections"])
        subprocess.Popen(command,
            creationflags=subprocess.CREATE_NO_WINDOW)
        print("Opened Study Dock and collector in a separate " + args.browser + " profile.")
        print("Sign in to Study Dock, generate a pairing code, and paste it into the collector tab.")
        print("If the collector is not installed in this profile, follow the manual installation steps in README.")
        if process:
            print("Keep this window open. Press Ctrl+C here to stop the local server.")
            while process.poll() is None:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
