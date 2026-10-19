"""The integrated document database follows the selected service data folder."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.project_documents import resolve_database


class DocumentDatabasePathTest(unittest.TestCase):
    def test_default_tracks_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"EVAL_DOCUMENTS_DB_PATH": ""}):
                self.assertEqual(
                    resolve_database(None, Path(folder)),
                    Path(folder) / "documents_parse.sqlite3",
                )

    def test_explicit_path_precedes_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            chosen = Path(folder) / "selected.sqlite3"
            with patch.dict(os.environ, {"EVAL_DOCUMENTS_DB_PATH": "ignored.sqlite3"}):
                self.assertEqual(resolve_database(chosen), chosen)


if __name__ == "__main__":
    unittest.main()
