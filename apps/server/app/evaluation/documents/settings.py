"""Document integration configuration; authentication belongs to the main service."""
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
PM01_DIR = REPO_ROOT / "apps/documents"
API_PREFIX = "/api/v2/evaluator"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    documents_db_path: Path | None
    session_absolute_seconds: int = 12 * 3600
    session_idle_seconds: int = 2 * 3600
    max_json_bytes: int = 64 * 1024
