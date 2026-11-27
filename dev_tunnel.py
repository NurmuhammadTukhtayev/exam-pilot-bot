"""Local testing helper: open an HTTPS tunnel to the Mini App and put its URL into .env.

    python dev_tunnel.py            # tunnel to http://localhost:8000, updates WEBAPP_URL in .env

Keep it running while you test (Ctrl+C stops the tunnel). After it says "ready", restart the bot
(python -m bot) so it picks up the new URL. Requires cloudflared:  winget install Cloudflare.cloudflared
"""

import argparse
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def set_env_value(env_file: Path, key: str, value: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    for i, line in enumerate(lines):
        if re.match(rf"\s*{re.escape(key)}\s*=", line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def wait_until_reachable(url: str, timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    if not shutil.which("cloudflared"):
        print("cloudflared not found. Install it:  winget install --id Cloudflare.cloudflared"
              "  (then open a new terminal)")
        return 1
    try:
        urllib.request.urlopen(f"http://localhost:{args.port}/healthz", timeout=3)
    except (urllib.error.URLError, OSError):
        print(f"Nothing answers on http://localhost:{args.port}. Start the Mini App first:\n"
              f"    uvicorn webapp.main:app --port {args.port} --reload")
        return 1

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{args.port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    print("Starting tunnel...")
    url = None
    for line in proc.stdout:
        if " ERR " in line:
            print(line.rstrip())
        match = URL_RE.search(line)
        if match:
            url = match.group(0)
            break
    if url is None:
        print("cloudflared exited without giving a URL (see errors above).")
        return 1

    # Keep draining cloudflared's output so it never blocks; show only errors.
    def drain():
        for line in proc.stdout:
            if " ERR " in line:
                print(line.rstrip())
    threading.Thread(target=drain, daemon=True).start()

    set_env_value(Path(args.env_file), "WEBAPP_URL", url + "/")
    print(f"Tunnel URL: {url}  (written to {args.env_file} as WEBAPP_URL)")
    print("Waiting until it's reachable...")
    if wait_until_reachable(url):
        print("\n✅ Ready. Now restart the bot (Ctrl+C, then: python -m bot) and reopen the Mini App in Telegram.")
    else:
        print("\n⚠️  The tunnel isn't reachable yet. Give it a minute, then restart the bot anyway.")
    print("Keep this window open. Ctrl+C stops the tunnel.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
