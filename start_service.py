"""Start the local service with the Python interpreter used for this command."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    command = [
        sys.executable,
        str(root / "apps" / "server" / "run.py"),
        "--local-test-login",
        *sys.argv[1:],
    ]
    if not {"--port", "--help", "-h"}.intersection(sys.argv[1:]):
        print("Open http://127.0.0.1:5190/ (local service)", flush=True)
    try:
        return subprocess.run(command, cwd=root, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
