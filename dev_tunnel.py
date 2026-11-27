"""Open a temporary HTTPS tunnel to the Mini App (Cloudflare quick tunnel) and put its URL into .env.

Local testing:
    python dev_tunnel.py                       # tunnel to http://localhost:8000, updates WEBAPP_URL in .env
    (then restart the bot so it picks up the new URL)

Temporary production use, before the real domain works (runs as a Windows service, see
deploy\\windows\\temp-tunnel.ps1):
    python dev_tunnel.py --env-file C:\\inetpub\\exam-pilot-bot\\.env --restart-service ExamPilot-Bot \\
        --cloudflared C:\\tools\\cloudflared\\cloudflared.exe

The quick-tunnel URL changes every time the tunnel starts. With --restart-service the bot service is
restarted after each new URL, so its Mini App button always points at the live tunnel.
Requires cloudflared:  winget install --id Cloudflare.cloudflared  (or download cloudflared.exe).
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
SERVICE_NAME_RE = re.compile(r"^[\w.-]+$")


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


def restart_windows_service(name: str) -> bool:
    print(f"Restarting service {name} so the bot uses the new URL...", flush=True)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"Restart-Service -Name '{name}'"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Could not restart {name}: {result.stderr.strip() or result.stdout.strip()}")
        return False
    print(f"{name} restarted.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--cloudflared", default="cloudflared", help="path to cloudflared(.exe)")
    parser.add_argument("--restart-service", metavar="NAME",
                        help="Windows service to restart after the URL changes (the bot)")
    args = parser.parse_args()

    if args.restart_service and not SERVICE_NAME_RE.match(args.restart_service):
        print(f"Invalid service name: {args.restart_service!r}")
        return 2
    cloudflared = shutil.which(args.cloudflared) or (args.cloudflared if Path(args.cloudflared).is_file() else None)
    if not cloudflared:
        print(f"cloudflared not found ({args.cloudflared}). Install it:  winget install --id Cloudflare.cloudflared"
              "  (then open a new terminal), or pass --cloudflared <path to cloudflared.exe>")
        return 1
    try:
        urllib.request.urlopen(f"http://localhost:{args.port}/healthz", timeout=3)
    except (urllib.error.URLError, OSError):
        print(f"Nothing answers on http://localhost:{args.port}. Start the Mini App first:\n"
              f"    uvicorn webapp.main:app --port {args.port} --reload")
        return 1

    proc = subprocess.Popen(
        [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{args.port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    print("Starting tunnel...", flush=True)
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
                print(line.rstrip(), flush=True)
    threading.Thread(target=drain, daemon=True).start()

    set_env_value(Path(args.env_file), "WEBAPP_URL", url + "/")
    print(f"Tunnel URL: {url}  (written to {args.env_file} as WEBAPP_URL)", flush=True)
    print("Waiting until it's reachable...", flush=True)
    reachable = wait_until_reachable(url)
    if not reachable:
        print("The tunnel isn't reachable yet (new tunnels can take a minute).", flush=True)

    if args.restart_service:
        restart_windows_service(args.restart_service)
        print("Tunnel running. If it stops, it is restarted with a new URL and the bot is restarted again.",
              flush=True)
    elif reachable:
        print("\n✅ Ready. Now restart the bot (Ctrl+C, then: python -m bot) and reopen the Mini App in Telegram.")
        print("Keep this window open. Ctrl+C stops the tunnel.")
    else:
        print("Give it a minute, then restart the bot anyway. Keep this window open.")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0
    print(f"cloudflared stopped (exit code {proc.returncode}).", flush=True)
    return 1  # as a service: NSSM restarts us -> new tunnel, new URL, bot restarted


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
