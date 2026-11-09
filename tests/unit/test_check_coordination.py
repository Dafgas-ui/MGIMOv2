import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_coordination as cc  # noqa: E402

BOARD_HEAD = (
    "| task_id | title | assignee | reviewer | dev_status | audit_status | owner_status | commit_ref | notes |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)


def row(tid="TASK-000", dev="PLANNED", audit="PENDING", owner="PENDING"):
    return f"| {tid} | t | a | r | {dev} | {audit} | {owner} | - | |\n"


def make_record(
    tid="TASK-000",
    record_type="HANDOFF",
    author="x",
    timestamp="2026-01-01 10:00",
    commit_hash="abc1234",
    sha="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    changed_files="file.txt",
    verified_checks="checks ok",
    limitations="none",
    predecessor_ref="NONE",
):
    return (
        f"## [{record_type}] {tid} — {timestamp}\n"
        f"task_id: {tid}\n"
        f"record_type: {record_type}\n"
        f"author: {author}\n"
        f"timestamp: {timestamp}\n"
        f"commit_hash: {commit_hash}\n"
        f"agents_md_sha256: {sha}\n"
        f"changed_files: {changed_files}\n"
        f"verified_checks: {verified_checks}\n"
        f"limitations: {limitations}\n"
        f"predecessor_ref: {predecessor_ref}\n"
    )


HANDOFF_OK = make_record("TASK-000", "HANDOFF")
AUDIT_OK = make_record("TASK-000", "AUDIT", predecessor_ref="HANDOFF TASK-000 (abc1234)")


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

    def test_pass_with_audit(self):
        self.build(row(dev="READY_FOR_REVIEW", audit="PASS"), HANDOFF_OK + "\n" + AUDIT_OK)
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

    def test_missing_required_field_in_handoff(self):
        bad_handoff = (
            "## [HANDOFF] TASK-000 — 2026-01-01 10:00\n"
            "task_id: TASK-000\n"
            "record_type: HANDOFF\n"
            "author: x\n"
            "commit_hash: abc1234\n"
        )
        self.build(row(dev="READY_FOR_REVIEW"), bad_handoff)
        errs = cc.check(self.tmp)
        self.assertTrue(any("отсутствует или пусто обязательное поле" in e for e in errs))

    def test_empty_required_field_in_handoff(self):
        bad_handoff = make_record("TASK-000", "HANDOFF", limitations="")
        self.build(row(dev="READY_FOR_REVIEW"), bad_handoff)
        errs = cc.check(self.tmp)
        self.assertTrue(any("limitations" in e for e in errs))

    def test_mismatched_task_id_in_body(self):
        bad = make_record("TASK-000", "HANDOFF").replace("task_id: TASK-000", "task_id: TASK-001")
        self.build(row(dev="READY_FOR_REVIEW"), bad)
        errs = cc.check(self.tmp)
        self.assertTrue(any("поле task_id" in e and "не совпадает с заголовком" in e for e in errs))

    def test_mismatched_record_type_in_body(self):
        bad = make_record("TASK-000", "HANDOFF").replace("record_type: HANDOFF", "record_type: AUDIT")
        self.build(row(dev="READY_FOR_REVIEW"), bad)
        errs = cc.check(self.tmp)
        self.assertTrue(any("поле record_type" in e and "не совпадает с типом заголовка" in e for e in errs))

    def test_audit_status_pass_without_audit_record(self):
        # dev_status = READY_FOR_REVIEW, audit_status = PASS, но в handoff только HANDOFF
        self.build(row(dev="READY_FOR_REVIEW", audit="PASS"), HANDOFF_OK)
        errs = cc.check(self.tmp)
        self.assertTrue(any("нет блока AUDIT с валидным commit_hash" in e for e in errs))

    def test_audit_status_pass_with_pending_hash(self):
        bad_audit = AUDIT_OK.replace("abc1234", "PENDING")
        self.build(row(dev="READY_FOR_REVIEW", audit="PASS"), HANDOFF_OK + "\n" + bad_audit)
        errs = cc.check(self.tmp)
        self.assertTrue(any("нет блока AUDIT с валидным commit_hash" in e for e in errs))

    def test_hash_mismatch(self):
        self.build(row(), sha="0" * 64)
        self.assertTrue(any("SHA-256" in e for e in cc.check(self.tmp)))

    def test_missing_file(self):
        self.build(row())
        (self.tmp / "docs" / "coordination" / "workflow.md").unlink()
        self.assertTrue(any("workflow.md" in e for e in cc.check(self.tmp)))


if __name__ == "__main__":
    unittest.main()
