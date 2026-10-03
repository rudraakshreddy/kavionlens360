"""Print the web report (docs/index.html) to docs/downloads/KavionLens360_Report.pdf with a headless browser."""
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import SITE_DIR

OUT = SITE_DIR / "downloads" / "KavionLens360_Report.pdf"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
]


def find_browser():
    for b in BROWSERS:
        if Path(b).exists():
            return b
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def run(port: int = 8799) -> Path:
    browser = find_browser()
    if not browser:
        raise RuntimeError("No Chromium-based browser found for PDF printing")
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(_Quiet, directory=str(SITE_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--blink-settings=preferredColorScheme=1", "--virtual-time-budget=8000",
                        f"--print-to-pdf={OUT}", f"http://127.0.0.1:{port}/index.html"],
                       check=True, timeout=180, capture_output=True)
    finally:
        server.shutdown()
    return OUT


if __name__ == "__main__":
    print(run())
