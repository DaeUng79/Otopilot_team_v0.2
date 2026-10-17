"""Backward-compatible entry point; use start_service.py for new setups."""

from start_service import main


if __name__ == "__main__":
    raise SystemExit(main())
