"""A newly registered administrator must replace the initial password."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin import admin_service, auth_service
from app.committee.committee_app.v2_web_demo import local_runtime
from app.shared.db import Actor, Store
from app.shared.demo_data import seed


class AdminFirstPasswordChangeTest(unittest.TestCase):
    def test_new_admin_changes_initial_password_before_normal_use(self):
        with tempfile.TemporaryDirectory(prefix="simsa-first-password-") as directory:
            root = Path(directory)
            runtime, _ = local_runtime(root)
            store = Store(runtime, root / "evaluation.sqlite3")
            asyncio.run(store.initialize())
            asyncio.run(seed(store))
            super_admin = Actor("super-demo", "SUPER_ADMIN")
            account = store.transact(
                super_admin,
                "ADM-02",
                {
                    "department_id": "web-demo-dept",
                    "username": "firstlogin01",
                    "display_name": "첫 로그인 담당자",
                    "password": "Initial1234!",
                },
                str(uuid4()),
                admin_service.create_admin,
                database="admin",
            )

            _, actor = auth_service.login_admin(
                store, {"username": "firstlogin01", "password": "Initial1234!"}
            )
            self.assertTrue(auth_service.must_change(store, actor))
            store.transact(
                actor,
                "AUTH-04",
                {"current_password": "Initial1234!", "new_password": "Personal5678!"},
                str(uuid4()),
                auth_service.change_password,
                database="admin",
            )
            self.assertFalse(auth_service.must_change(store, actor))
            _, relogged_actor = auth_service.login_admin(
                store, {"username": account["username"], "password": "Personal5678!"}
            )
            self.assertEqual(relogged_actor.id, actor.id)


if __name__ == "__main__":
    unittest.main()
