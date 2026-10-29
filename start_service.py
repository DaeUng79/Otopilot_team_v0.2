"""Start the local service with the Python interpreter used for this command."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def main() -> int:
    root = Path(__file__).resolve().parent
    env = os.environ.copy()
    # The local service uses this project's .env even when the launching shell
    # still has an older OPENAI_API_KEY exported.
    local_key = dotenv_values(root / ".env", interpolate=False).get("OPENAI_API_KEY")
    if local_key and local_key.strip():
        env["OPENAI_API_KEY"] = local_key.strip()
    command = [
        sys.executable,
        str(root / "apps" / "server" / "run.py"),
        *sys.argv[1:],
    ]
    if not {"--port", "--help", "-h"}.intersection(sys.argv[1:]):
        print("Open http://127.0.0.1:5190/ (local service)", flush=True)
    try:
        return subprocess.run(command, cwd=root, env=env, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
