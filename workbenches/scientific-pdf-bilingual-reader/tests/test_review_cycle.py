import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import fitz


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qa_contract import build_contract, verify_contract  # noqa: E402
from review_cycle import (  # noqa: E402
    active_agent_review_jobs, agent_job_path, append_comment_decision,
    append_agent_review,
    claim_next_agent_job, create_comment, enqueue_agent_review, list_agent_reviews,
    load_comment,
    list_comments, permanently_delete_task, read_json, restore_trashed_task,
    review_cycle_projection, run_agent_review_job, trash_task, write_page_manifest,
)


def write_pdf(path: Path, texts: list[str]) -> None:
    document = fitz.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


class ReviewCycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.folder = self.data / "sample"
        self.folder.mkdir()
        self.task = {
            "id": "sample",
            "name": "sample.pdf",
            "original_file": "original.pdf",
            "translated_file": "translated-zh.pdf",
            "page_plan_file": "page-plan.json",
            "qa_alpha_file": "qa-alpha.json",
        }
        write_pdf(self.folder / "original.pdf", ["source one", "source two"])
        write_pdf(self.folder / "translated-zh.pdf", ["translated one", "translated two"])
        (self.folder / "page-plan.json").write_text(json.dumps({"pages": [{"pdf_page": 1}, {"pdf_page": 2}]}))
        self.contract = build_contract(
            original_path=self.folder / "original.pdf",
            output_path=self.folder / "translated-zh.pdf",
            plan_path=self.folder / "page-plan.json",
            task=self.task,
        )
        (self.folder / "qa-alpha.json").write_text(json.dumps({
            "status": "passed",
            "summary": {},
            "page_count": 2,
            "pages": [],
            "contract": self.contract,
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_page_manifest_persists_page_fingerprints_without_staling_qa_contract(self):
        ref = write_page_manifest(self.folder, self.task, self.folder / "translated-zh.pdf", self.contract)
        manifest = read_json(self.folder / ref["current_path"], {})
        self.assertEqual(manifest["schema"], "page-manifest/v1")
        self.assertEqual(manifest["page_count"], 2)
        self.assertIn("render_sha256", manifest["pages"][0])
        self.assertIn("text_sha256", manifest["pages"][0])
        self.assertEqual(manifest["pages"][0]["rotation"], 0)
        qa = json.loads((self.folder / "qa-alpha.json").read_text())
        qa["page_manifest"] = ref
        self.assertEqual(
            verify_contract(
                qa,
                original_path=self.folder / "original.pdf",
                output_path=self.folder / "translated-zh.pdf",
                plan_path=self.folder / "page-plan.json",
                task=self.task,
            )["status"],
            "fresh",
        )

    def test_comment_save_is_local_and_versioned(self):
        write_page_manifest(self.folder, self.task, self.folder / "translated-zh.pdf", self.contract)
        comment = create_comment(self.folder, self.task, 2, "这一页术语译法不一致")
        self.assertEqual(comment["status"], "saved")
        self.assertEqual(comment["object_version"], 1)
        self.assertEqual(comment["pdf_page"], 2)
        self.assertEqual(len(list_comments(self.folder)), 1)

    def test_agent_review_queue_serializes_active_job_and_recovers_interrupted_active(self):
        comments = [create_comment(self.folder, self.task, 1, f"comment {index}") for index in range(2)]
        first = enqueue_agent_review(self.folder, self.task, [comments[0]["comment_id"]])
        second = enqueue_agent_review(self.folder, self.task, [comments[1]["comment_id"]])
        active = claim_next_agent_job(self.folder, self.task["id"])
        self.assertEqual(active["job_id"], first["job_id"])
        self.assertIsNone(claim_next_agent_job(self.folder, self.task["id"]))
        recovered = active_agent_review_jobs(self.folder, self.task["id"])
        self.assertEqual(recovered, [])
        failed = read_json(agent_job_path(self.folder, first["job_id"]), {})
        self.assertEqual(failed["status"], "failed")
        next_job = claim_next_agent_job(self.folder, self.task["id"])
        self.assertEqual(next_job["job_id"], second["job_id"])
        self.assertEqual(next_job["status"], "active")

    def test_same_page_batch_calls_model_once_and_appends_each_review(self):
        comments = [create_comment(self.folder, self.task, 1, f"同页意见 {index}") for index in range(3)]
        job = enqueue_agent_review(self.folder, self.task, [item["comment_id"] for item in comments], "claude")
        active = claim_next_agent_job(self.folder, self.task["id"])
        calls = []

        def review_provider(job_record, pdf_page, grouped_comments):
            calls.append((pdf_page, [item["comment_id"] for item in grouped_comments]))
            return {"reviews": [
                {
                    "comment_id": item["comment_id"],
                    "explanation": f"逐条关注 {index}",
                    "recommended_action": "人工确认",
                }
                for index, item in enumerate(grouped_comments)
            ]}

        finished = run_agent_review_job(self.folder, self.task, active, review_provider=review_provider)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 1)
        reviews = list_agent_reviews(self.folder)
        self.assertEqual(len(reviews), 3)
        self.assertEqual(
            {item["comment_id"]: item["result"]["page_review"]["explanation"] for item in reviews},
            {item["comment_id"]: f"逐条关注 {index}" for index, item in enumerate(comments)},
        )

    def test_same_page_batch_fails_closed_when_agent_omits_a_comment(self):
        comments = [create_comment(self.folder, self.task, 1, f"同页意见 {index}") for index in range(2)]
        enqueue_agent_review(self.folder, self.task, [item["comment_id"] for item in comments], "claude")
        active = claim_next_agent_job(self.folder, self.task["id"])

        def incomplete_provider(job_record, pdf_page, grouped_comments):
            return {"reviews": [{
                "comment_id": grouped_comments[0]["comment_id"],
                "explanation": "只返回第一条",
            }]}

        finished = run_agent_review_job(self.folder, self.task, active, review_provider=incomplete_provider)
        self.assertEqual(finished["status"], "failed")
        self.assertIn("漏掉 Comment", finished["error"])
        self.assertEqual(len(list_agent_reviews(self.folder)), 0)

    def test_review_failed_comment_reenqueue_sets_queued_and_rejects_duplicate_queued(self):
        comment = create_comment(self.folder, self.task, 1, "需要重审")
        failed = dict(comment)
        failed["status"] = "review_failed"
        failed["last_error"] = "previous failure"
        from review_cycle import write_comment_object  # local import keeps test focused on object state setup
        write_comment_object(self.folder, failed["comment_id"], failed)

        enqueue_agent_review(self.folder, self.task, [failed["comment_id"]])
        refreshed = list_comments(self.folder)[0]
        self.assertEqual(refreshed["status"], "queued")
        with self.assertRaises(RuntimeError):
            enqueue_agent_review(self.folder, self.task, [failed["comment_id"]])

    def test_comment_lock_preserves_decision_and_agent_review_writes(self):
        comment = create_comment(self.folder, self.task, 1, "并发写入 smoke")
        job = {
            "job_id": "job-lock",
            "task_id": self.task["id"],
            "provider": "claude",
        }

        def decide():
            current = load_comment(self.folder, comment["comment_id"])
            append_comment_decision(
                self.folder,
                comment["comment_id"],
                "deferred",
                "later",
                expected_version=current["object_version"],
            )

        def review():
            append_agent_review(self.folder, job, comment, {"page_review": {"explanation": "ok"}})

        threads = [threading.Thread(target=decide), threading.Thread(target=review)]
        for item in threads:
            item.start()
        for item in threads:
            item.join()
        refreshed = list_comments(self.folder)[0]
        self.assertEqual(refreshed["decision_events"][0]["decision"], "deferred")
        self.assertEqual(len(refreshed["agent_review_ids"]), 1)

    def test_decision_events_are_append_only_and_optimistic(self):
        comment = create_comment(self.folder, self.task, 1, "需要确认图题译法")
        updated = append_comment_decision(
            self.folder, comment["comment_id"], "needs_more_info", "请补充原文引用", expected_version=1,
        )
        self.assertEqual(updated["object_version"], 2)
        updated = append_comment_decision(
            self.folder, comment["comment_id"], "agree_no_change", "", expected_version=2,
        )
        self.assertEqual(updated["latest_decision"], "agree_no_change")
        self.assertEqual([event["decision"] for event in updated["decision_events"]], [
            "needs_more_info", "agree_no_change",
        ])
        with self.assertRaises(RuntimeError):
            append_comment_decision(self.folder, comment["comment_id"], "deferred", "", expected_version=1)

    def test_same_comment_decision_is_idempotent_and_missing_version_cannot_change(self):
        comment = create_comment(self.folder, self.task, 1, "重复点击同一个裁定")
        first = append_comment_decision(
            self.folder, comment["comment_id"], "agree_no_change", "", expected_version=1,
        )
        again = append_comment_decision(self.folder, comment["comment_id"], "agree_no_change", "")
        self.assertEqual(again["object_version"], first["object_version"])
        self.assertEqual(len(again["decision_events"]), 1)
        self.assertEqual(again["decision_events"][0]["decision"], "agree_no_change")
        with self.assertRaises(RuntimeError):
            append_comment_decision(self.folder, comment["comment_id"], "deferred", "")

    def test_task_delete_moves_to_trash_restore_and_permanent_requires_confirm(self):
        create_comment(self.folder, self.task, 1, "保留对象计数")
        trashed = trash_task(self.data, "sample")
        self.assertTrue(trashed["trashed"])
        self.assertFalse(self.folder.exists())
        self.assertEqual(trashed["summary"]["object_counts"]["comments"], 1)
        restored = restore_trashed_task(self.data, trashed["trash_id"])
        self.assertTrue(restored["restored"])
        with self.assertRaises(ValueError):
            permanently_delete_task(self.data, "sample", "wrong")
        deleted = permanently_delete_task(self.data, "sample", "sample")
        self.assertTrue(deleted["permanent"])
        self.assertFalse(self.folder.exists())

    def test_projection_marks_interrupted_active_failed_and_keeps_queued_recoverable(self):
        comments = [create_comment(self.folder, self.task, 1, f"comment {index}") for index in range(2)]
        enqueue_agent_review(self.folder, self.task, [comments[0]["comment_id"]])
        enqueue_agent_review(self.folder, self.task, [comments[1]["comment_id"]])
        claim_next_agent_job(self.folder, self.task["id"])
        projection = review_cycle_projection(self.folder, self.task)
        statuses = [item["status"] for item in projection["agent_review_jobs"]]
        self.assertIn("failed", statuses)
        self.assertIn("queued", statuses)

    def test_approved_comment_can_be_withdrawn_without_deleting_audit_or_peers(self):
        write_page_manifest(self.folder, self.task, self.folder / "translated-zh.pdf", self.contract)
        comments = [create_comment(self.folder, self.task, 1, f"已批准意见 {index}") for index in range(2)]
        job = {"job_id": "job-decision", "task_id": self.task["id"], "provider": "claude"}
        for comment in comments:
            append_agent_review(
                self.folder,
                job,
                comment,
                {"page_review": {"is_real_problem": True, "repair_family": "untranslated_region"}},
            )
            current = load_comment(self.folder, comment["comment_id"])
            append_comment_decision(
                self.folder,
                comment["comment_id"],
                "agree_needs_change",
                "",
                expected_version=current["object_version"],
            )

        projection = review_cycle_projection(self.folder, self.task)
        self.assertEqual(projection["approved_comment_count"], 2)
        first = load_comment(self.folder, comments[0]["comment_id"])
        append_comment_decision(
            self.folder,
            first["comment_id"],
            "not_adopted",
            "",
            expected_version=first["object_version"],
        )

        withdrawn = load_comment(self.folder, first["comment_id"])
        peer = load_comment(self.folder, comments[1]["comment_id"])
        self.assertEqual(withdrawn["latest_decision"], "not_adopted")
        self.assertEqual([event["decision"] for event in withdrawn["decision_events"]], [
            "agree_needs_change", "not_adopted",
        ])
        self.assertEqual(peer["latest_decision"], "agree_needs_change")
        self.assertEqual(review_cycle_projection(self.folder, self.task)["approved_comment_count"], 1)


if __name__ == "__main__":
    unittest.main()
