"""Load shared document modules from apps/documents without changing server imports."""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[3] / "documents"))
