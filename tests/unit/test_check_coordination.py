import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_coordination as cc  # noqa: E402

BOARD_HEAD = ("| task_id | title | assignee | reviewer | dev_status | audit_status | owner_status | commit_ref | notes |\n"
              "|---|---|---|---|---|---|---|---|---|\n")


def row(tid="TASK-000", dev="PLANNED", audit="PENDING", owner="PENDING"):
    return f"| {tid} | t | a | r | {dev} | {audit} | {owner} | - | |\n"


HANDOFF_OK = ("## [HANDOFF] TASK-000 — 2026-01-01 10:00\n"
              "task_id: TASK-000\nrecord_type: HANDOFF\nauthor: x\ncommit_hash: abc1234\n")


class CheckCoordinationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, board, handoff="# log\n", agents=b"rules", sha=None):
        c = self.tmp / "docs" / "coordination"
        c.mkdir(parents=True, exist_ok=True)
        (self.tmp / "AGENTS.md").write_bytes(agents)
        sha = sha or hashlib.sha256(agents).hexdigest()
        (c / "workflow.md").write_text("w", encoding="utf-8")
        (c / "task-board.md").write_text(BOARD_HEAD + board, encoding="utf-8")
        (c / "review-handoff.md").write_text(handoff, encoding="utf-8")
        (c / "project-status.md").write_text(f"agents_md_sha256: {sha}\n", encoding="utf-8")

    def test_pass(self):
        self.build(row(dev="READY_FOR_REVIEW"), HANDOFF_OK)
        self.assertEqual(cc.check(self.tmp), [])

    def test_real_repo_passes(self):
        self.assertEqual(cc.check(ROOT), [])

    def test_duplicate_task_id(self):
        self.build(row() + row())
        self.assertTrue(any("дубликат" in e for e in cc.check(self.tmp)))

    def test_invalid_status(self):
        self.build(row(dev="DONE"))
        self.assertTrue(any("dev_status" in e for e in cc.check(self.tmp)))
        self.build(row(audit="OK"))
        self.assertTrue(any("audit_status" in e for e in cc.check(self.tmp)))
        self.build(row(owner="YES"))
        self.assertTrue(any("owner_status" in e for e in cc.check(self.tmp)))

    def test_missing_handoff(self):
        self.build(row(dev="READY_FOR_REVIEW"))
        self.assertTrue(any("HANDOFF" in e for e in cc.check(self.tmp)))

    def test_handoff_pending_hash(self):
        self.build(row(dev="READY_FOR_REVIEW"), HANDOFF_OK.replace("abc1234", "PENDING"))
        self.assertTrue(cc.check(self.tmp))

    def test_hash_mismatch(self):
        self.build(row(), sha="0" * 64)
        self.assertTrue(any("SHA-256" in e for e in cc.check(self.tmp)))

    def test_missing_file(self):
        self.build(row())
        (self.tmp / "docs" / "coordination" / "workflow.md").unlink()
        self.assertTrue(any("workflow.md" in e for e in cc.check(self.tmp)))


if __name__ == "__main__":
    unittest.main()
