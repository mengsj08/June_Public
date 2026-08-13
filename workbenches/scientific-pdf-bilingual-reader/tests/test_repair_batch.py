import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dual_pdf import merge  # noqa: E402
from qa_contract import build_contract  # noqa: E402
from artifact_transaction import install_artifact_set  # noqa: E402
from repair_batch import (  # noqa: E402
    accept_candidate, approved_repair_pool, assemble_candidate,
    batch_preview_file, candidate_observation_path,
    create_one_click_repair_batch, create_repair_batch,
    list_page_patches, mutation_lock_path, repair_batch_projection,
    run_candidate_observations, run_one_click_repair_batch, run_repair_batch,
    set_page_patch_decision, set_page_patch_decision_and_maybe_reassemble,
    start_repair_batch, task_mutation_lock,
)
from review_cycle import (  # noqa: E402
    append_agent_review, append_comment_decision, create_comment,
    enqueue_agent_review_selection, review_cycle_projection, write_page_manifest,
)


def write_pdf(path: Path, texts: list[str]) -> None:
    document = fitz.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


class RepairBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "task"
        self.folder.mkdir()
        self.task = {
            "id": "task",
            "name": "paper.pdf",
            "original_file": "original.pdf",
            "translated_file": "translated-zh.pdf",
            "dual_file": "bilingual-side-by-side.pdf",
            "page_plan_file": "page-plan.json",
            "qa_alpha_file": "qa-alpha.json",
        }
        write_pdf(self.folder / "original.pdf", ["source page one", "source page two"])
        write_pdf(self.folder / "translated-zh.pdf", ["translated page one", "translated page two"])
        merge(
            self.folder / "original.pdf",
            self.folder / "translated-zh.pdf",
            self.folder / "bilingual-side-by-side.pdf",
        )
        plan = {"version": 2, "pages": [{"pdf_page": 1}, {"pdf_page": 2}]}
        (self.folder / "page-plan.json").write_text(json.dumps(plan))
        contract = build_contract(
            original_path=self.folder / "original.pdf",
            output_path=self.folder / "translated-zh.pdf",
            plan_path=self.folder / "page-plan.json",
            task=self.task,
        )
        qa = {
            "version": 2,
            "status": "passed",
            "summary": {"red": 0, "orange": 0, "warning": 0},
            "page_count": 2,
            "document_issues": [],
            "pages": [
                {"pdf_page": 1, "status": "pass", "issues": [], "metrics": {}},
                {"pdf_page": 2, "status": "pass", "issues": [], "metrics": {}},
            ],
            "flagged_pages": [],
            "contract": contract,
        }
        (self.folder / "qa-alpha.json").write_text(json.dumps(qa))
        (self.folder / "task.json").write_text(json.dumps(self.task))
        write_page_manifest(self.folder, self.task, self.folder / "translated-zh.pdf", contract)

    def tearDown(self):
        self.temp.cleanup()

    def reviewed_approved_comment(self, page: int = 1):
        comment = create_comment(self.folder, self.task, page, "翻译本页标题，数字保持不变")
        review = append_agent_review(
            self.folder,
            {"job_id": "job", "task_id": "task", "provider": "claude"},
            comment,
            {"page_review": {
                "is_real_problem": True,
                "repair_family": "untranslated_region",
                "protected_content": [],
                "recommended_action": "翻译标题",
            }},
        )
        refreshed = next(item for item in review_cycle_projection(self.folder, self.task)["comments"] if item["comment_id"] == comment["comment_id"])
        append_comment_decision(
            self.folder,
            comment["comment_id"],
            "agree_needs_change",
            expected_version=refreshed["object_version"],
        )
        return comment, review

    def test_document_projection_counts_cross_page_pending_and_partial_queue(self):
        first = create_comment(self.folder, self.task, 1, "第一页")
        second = create_comment(self.folder, self.task, 2, "第二页")
        queued = enqueue_agent_review_selection(
            self.folder, self.task, [first["comment_id"], "missing", second["comment_id"]], "claude",
        )
        self.assertEqual(set(queued["accepted"]), {first["comment_id"], second["comment_id"]})
        self.assertEqual(queued["rejected"][0]["comment_id"], "missing")
        projection = review_cycle_projection(self.folder, self.task)
        self.assertEqual(projection["pending_comment_count"], 0)
        self.assertEqual(projection["queued_review_count"], 2)

    def test_approved_comment_builds_batch_page_patch_candidate_and_accepts_atomically(self):
        comment, _ = self.reviewed_approved_comment(1)
        pool = approved_repair_pool(self.folder, self.task)
        self.assertEqual(len(pool), 1)
        self.assertTrue(pool[0]["eligible"])
        batch = create_repair_batch(self.folder, self.task, [pool[0]["key"]])
        self.assertEqual(batch["status"], "preflight_ready")
        start_repair_batch(self.folder, self.task, batch["batch_id"])

        def fake_executor(folder, task, record, output):
            output.mkdir(parents=True, exist_ok=True)
            current = fitz.open(folder / "translated-zh.pdf")
            current[0].insert_text((72, 100), "updated title")
            translated = output / "translated-zh.repaired.pdf"
            current.save(translated)
            current.close()
            plan = output / "page-plan.repaired.json"
            plan.write_text((folder / "page-plan.json").read_text())
            qa = output / "qa-repaired.json"
            qa.write_text(json.dumps({
                "status": "passed",
                "summary": {"red": 0, "orange": 0, "warning": 0},
                "pages": [
                    {"pdf_page": 1, "status": "pass", "issues": []},
                    {"pdf_page": 2, "status": "pass", "issues": []},
                ],
            }))
            dual = output / "bilingual-side-by-side.repaired.pdf"
            merge(folder / "original.pdf", translated, dual)
            return {
                "non_target_integrity": {"checked_pages": [2], "mismatched_pages": []},
                "translation_metrics": {"requests": 1},
            }, {"translated": translated, "plan": plan, "qa": qa, "dual": dual}

        completed = run_repair_batch(
            self.folder, self.task, batch["batch_id"], repair_executor=fake_executor,
        )
        self.assertEqual(completed["status"], "awaiting_page_decisions")
        page_patch = list_page_patches(self.folder, batch["batch_id"])[0]
        self.assertEqual(page_patch["machine_gate"], "pass")
        set_page_patch_decision(
            self.folder,
            batch["batch_id"],
            page_patch["page_patch_id"],
            "include",
            expected_version=page_patch["object_version"],
        )
        fake_audit = {
            "version": 2,
            "status": "passed",
            "summary": {"red": 0, "orange": 0, "warning": 0},
            "document_issues": [],
            "pages": [
                {"pdf_page": 1, "status": "pass", "issues": []},
                {"pdf_page": 2, "status": "pass", "issues": []},
            ],
            "flagged_pages": [],
            "contract": {},
        }
        with patch("repair_batch.audit", return_value=fake_audit):
            candidate = assemble_candidate(self.folder, self.task, batch["batch_id"])
        self.assertEqual(candidate["status"], "candidate_ready")
        before_hash = fitz.open(self.folder / "translated-zh.pdf")[0].get_text()
        accepted = accept_candidate(self.folder, self.task, batch["batch_id"])
        after_hash = fitz.open(self.folder / "translated-zh.pdf")[0].get_text()
        self.assertNotEqual(before_hash, after_hash)
        self.assertIn("RepairBatch", accepted["message"])
        projection = repair_batch_projection(self.folder, self.task)
        self.assertIsNone(projection["open_repair_batch_id"])
        updated_comment = next(item for item in list_comments_for_test(self.folder) if item["comment_id"] == comment["comment_id"])
        self.assertEqual(updated_comment["status"], "repair_applied")

    def test_page_patch_decision_is_idempotent_and_missing_version_cannot_change(self):
        comment, _ = self.reviewed_approved_comment(1)
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_repair_batch(self.folder, self.task, [pool[0]["key"]])
        patch = {
            "schema": "page-patch/v1",
            "page_patch_id": "page-patch-idempotent",
            "batch_id": batch["batch_id"],
            "task_id": self.task["id"],
            "pdf_page": 1,
            "status": "awaiting_decision",
            "decision": "defer",
            "decision_events": [],
            "machine_gate": "pass",
            "machine_gate_reasons": [],
            "repair_item_keys": [pool[0]["key"]],
        }
        from review_cycle import write_versioned_object
        from repair_batch import page_patch_path

        saved = write_versioned_object(
            page_patch_path(self.folder, batch["batch_id"], patch["page_patch_id"]),
            patch,
            expected_version=0,
        )
        first = set_page_patch_decision(
            self.folder, batch["batch_id"], saved["page_patch_id"], "include",
            expected_version=saved["object_version"],
        )
        again = set_page_patch_decision(self.folder, batch["batch_id"], saved["page_patch_id"], "include")
        self.assertEqual(again["object_version"], first["object_version"])
        self.assertEqual(len(again["decision_events"]), 1)
        self.assertEqual(again["decision_events"][0]["decision"], "include")
        with self.assertRaises(RuntimeError):
            set_page_patch_decision(self.folder, batch["batch_id"], saved["page_patch_id"], "exclude")

    def test_repair_batch_blocks_new_deterministic_visual_violation(self):
        self.reviewed_approved_comment(1)
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_repair_batch(self.folder, self.task, [pool[0]["key"]])
        start_repair_batch(self.folder, self.task, batch["batch_id"])

        def fake_executor(folder, task, record, output):
            output.mkdir(parents=True, exist_ok=True)
            current = fitz.open(folder / "translated-zh.pdf")
            current[0].insert_text((72, 100), "updated title")
            translated = output / "translated-zh.repaired.pdf"
            current.save(translated)
            current.close()
            plan = output / "page-plan.repaired.json"
            plan.write_text((folder / "page-plan.json").read_text())
            qa = output / "qa-repaired.json"
            qa.write_text(json.dumps({
                "status": "passed",
                "summary": {"red": 0, "orange": 0, "warning": 0},
                "pages": [
                    {"pdf_page": 1, "status": "pass", "issues": [
                        {"issue_type": "rendered_text_overlap", "severity": "red", "evidence": "new overlap"},
                    ]},
                    {"pdf_page": 2, "status": "pass", "issues": []},
                ],
            }))
            dual = output / "bilingual-side-by-side.repaired.pdf"
            merge(folder / "original.pdf", translated, dual)
            return {
                "non_target_integrity": {"checked_pages": [2], "mismatched_pages": []},
                "translation_metrics": {"requests": 1},
            }, {"translated": translated, "plan": plan, "qa": qa, "dual": dual}

        completed = run_repair_batch(
            self.folder, self.task, batch["batch_id"], repair_executor=fake_executor,
        )
        self.assertEqual(completed["status"], "failed")
        patch = list_page_patches(self.folder, batch["batch_id"])[0]
        self.assertEqual(patch["machine_gate"], "blocked")
        self.assertIn("新增确定性视觉违规", "；".join(patch["machine_gate_reasons"]))

    def test_stale_v2_disk_qa_is_rerun_before_new_red_comparison(self):
        self.reviewed_approved_comment(1)
        stale = json.loads((self.folder / "qa-alpha.json").read_text())
        stale["contract"]["qa_rule_version"] = "qa-alpha-red-orange-warning/v2"
        stale["summary"] = {"red": 0, "orange": 0, "warning": 0, "pass": 2}
        stale["pages"] = [
            {"pdf_page": 1, "status": "pass", "issues": [], "metrics": {}},
            {"pdf_page": 2, "status": "pass", "issues": [], "metrics": {}},
        ]
        (self.folder / "qa-alpha.json").write_text(json.dumps(stale))
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_repair_batch(self.folder, self.task, [pool[0]["key"]])
        start_repair_batch(self.folder, self.task, batch["batch_id"])

        def current_v3_report():
            report = {
                "version": 2,
                "status": "needs_review",
                "summary": {"red": 1, "orange": 0, "warning": 0, "pass": 1},
                "pages": [
                    {"pdf_page": 1, "status": "red", "issues": [
                        {"issue_type": "rendered_structure_drift", "severity": "red", "evidence": "existing drift"},
                    ]},
                    {"pdf_page": 2, "status": "pass", "issues": []},
                ],
            }
            report["contract"] = build_contract(
                original_path=self.folder / "original.pdf",
                output_path=self.folder / "translated-zh.pdf",
                plan_path=self.folder / "page-plan.json",
                task=self.task,
            )
            return report

        def fake_executor(folder, task, record, output):
            output.mkdir(parents=True, exist_ok=True)
            current = fitz.open(folder / "translated-zh.pdf")
            current[0].insert_text((72, 100), "updated title")
            translated = output / "translated-zh.repaired.pdf"
            current.save(translated)
            current.close()
            plan = output / "page-plan.repaired.json"
            plan.write_text((folder / "page-plan.json").read_text())
            qa = output / "qa-repaired.json"
            after = current_v3_report()
            after["contract"] = build_contract(
                original_path=folder / "original.pdf",
                output_path=translated,
                plan_path=plan,
                task=task,
            )
            qa.write_text(json.dumps(after))
            dual = output / "bilingual-side-by-side.repaired.pdf"
            merge(folder / "original.pdf", translated, dual)
            return {
                "non_target_integrity": {"checked_pages": [2], "mismatched_pages": []},
                "translation_metrics": {"requests": 1},
            }, {"translated": translated, "plan": plan, "qa": qa, "dual": dual}

        with patch("repair_batch.audit", return_value=current_v3_report()):
            completed = run_repair_batch(
                self.folder, self.task, batch["batch_id"], repair_executor=fake_executor,
            )
        self.assertEqual(completed["status"], "awaiting_page_decisions")
        patch_record = list_page_patches(self.folder, batch["batch_id"])[0]
        self.assertEqual(patch_record["machine_gate"], "pass")
        self.assertEqual(completed["execution"]["new_red_pages"], [])

    def test_one_click_builds_candidate_preview_and_exclude_reassembles(self):
        self.reviewed_approved_comment(1)
        self.reviewed_approved_comment(2)
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_one_click_repair_batch(self.folder, self.task, [item["key"] for item in pool])
        self.assertEqual(batch["status"], "repairing")
        self.assertEqual(batch["progress"]["step"], "executing")

        def fake_executor(folder, task, record, output):
            output.mkdir(parents=True, exist_ok=True)
            current = fitz.open(folder / "translated-zh.pdf")
            current[0].insert_text((72, 100), "updated title one")
            current[1].insert_text((72, 100), "updated title two")
            translated = output / "translated-zh.repaired.pdf"
            current.save(translated)
            current.close()
            plan = output / "page-plan.repaired.json"
            plan.write_text(json.dumps({
                "version": 2,
                "pages": [
                    {"pdf_page": 1, "fallbacks": ["text-layer-fallback"]},
                    {"pdf_page": 2, "fallbacks": ["layout-copy-fallback"]},
                ],
            }))
            qa = output / "qa-repaired.json"
            qa.write_text(json.dumps({
                "status": "passed",
                "summary": {"red": 0, "orange": 0, "warning": 0},
                "pages": [
                    {"pdf_page": 1, "status": "pass", "issues": [], "metrics": {"gate": 1}},
                    {"pdf_page": 2, "status": "pass", "issues": [], "metrics": {"gate": 2}},
                ],
            }))
            dual = output / "bilingual-side-by-side.repaired.pdf"
            merge(folder / "original.pdf", translated, dual)
            return {
                "non_target_integrity": {"checked_pages": [], "mismatched_pages": []},
                "translation_metrics": {"requests": 2},
            }, {"translated": translated, "plan": plan, "qa": qa, "dual": dual}

        fake_audit = {
            "version": 2,
            "status": "passed",
            "summary": {"red": 0, "orange": 0, "warning": 0},
            "document_issues": [],
            "pages": [
                {"pdf_page": 1, "status": "pass", "issues": [], "metrics": {"candidate": 1}},
                {"pdf_page": 2, "status": "pass", "issues": [], "metrics": {"candidate": 2}},
            ],
            "flagged_pages": [],
            "contract": {},
        }
        with patch("repair_batch.audit", return_value=fake_audit):
            completed = run_one_click_repair_batch(
                self.folder, self.task, batch["batch_id"], repair_executor=fake_executor,
            )
            self.assertEqual(completed["status"], "candidate_ready")
            self.assertEqual(completed["one_click"]["result_state"], "acceptable")
            preview = completed["candidate"]["preview"]["changed_pages"]
            self.assertEqual([item["pdf_page"] for item in preview], [1, 2])
            self.assertIn("text-layer-fallback", preview[0]["fallbacks"])
            for item in preview:
                self.assertTrue(batch_preview_file(self.folder, batch["batch_id"], item["before_image"]).is_file())
                self.assertTrue(batch_preview_file(self.folder, batch["batch_id"], item["after_image"]).is_file())
            observations = run_candidate_observations(
                self.folder,
                self.task,
                batch["batch_id"],
                observation_provider=lambda batch_record, preview_page, patch: {
                    "repair_family": "layout",
                    "confidence": 0.82,
                    "reading_order_ok": True,
                    "reading_order_note": "order preserved",
                    "protected_content_ok": True,
                    "protected_content_note": "protected tokens visible",
                    "comment_issue_improved": True,
                    "comment_issue_note": "comment target improved",
                    "observations": ["side-by-side crop is readable"],
                },
            )
            self.assertEqual([item["status"] for item in observations], ["ready", "ready"])
            projected = repair_batch_projection(self.folder, self.task)
            projected_batch = next(item for item in projected["repair_batches"] if item["batch_id"] == batch["batch_id"])
            projected_preview = projected_batch["candidate"]["preview"]["changed_pages"]
            self.assertEqual(projected_preview[0]["model_observation"]["status"], "ready")
            self.assertEqual(projected_batch["one_click"]["result_state"], "acceptable")
            first_patch = list_page_patches(self.folder, batch["batch_id"])[0]
            reassembled = set_page_patch_decision_and_maybe_reassemble(
                self.folder,
                self.task,
                batch["batch_id"],
                first_patch["page_patch_id"],
                "exclude",
                expected_version=first_patch["object_version"],
            )
        self.assertEqual(reassembled["batch"]["status"], "candidate_ready")
        self.assertEqual(reassembled["batch"]["candidate"]["included_pages"], [2])

    def test_task_mutation_lock_blocks_active_writer_and_releases_stale_file(self):
        self.reviewed_approved_comment(1)
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_repair_batch(self.folder, self.task, [pool[0]["key"]])
        with task_mutation_lock(self.folder, "test-writer", ttl_seconds=60):
            with self.assertRaises(RuntimeError):
                assemble_candidate(self.folder, self.task, batch["batch_id"])
        lock_path = mutation_lock_path(self.folder)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps({
            "schema": "task-mutation-lock/v1",
            "owner": "dead",
            "pid": 99999999,
            "token": "stale",
            "created_at": 1,
            "expires_at": 1,
        }))
        with task_mutation_lock(self.folder, "fresh-writer", ttl_seconds=60):
            self.assertTrue(lock_path.is_file())
        self.assertFalse(lock_path.exists())

    def test_artifact_set_rolls_back_all_files_after_partial_install_failure(self):
        prepared = {}
        backup = self.folder / "versions" / "transaction-test"
        backup.mkdir(parents=True)
        names = ["translated-zh.pdf", "bilingual-side-by-side.pdf", "qa-alpha.json", "page-plan.json"]
        for name in names:
            (backup / name).write_bytes((self.folder / name).read_bytes())
            candidate = self.folder / f"candidate-{name}"
            candidate.write_bytes(b"new-" + name.encode())
            prepared[name] = candidate
        calls = 0

        def fail_second_replace(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated partial install")
            source.replace(destination)

        with self.assertRaisesRegex(RuntimeError, "已恢复全部旧正式文件"):
            install_artifact_set(self.folder, prepared, backup, replacer=fail_second_replace)
        for name in names:
            self.assertEqual((self.folder / name).read_bytes(), (backup / name).read_bytes())

    def test_candidate_observation_failure_does_not_block_acceptance(self):
        self.reviewed_approved_comment(1)
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_one_click_repair_batch(self.folder, self.task, [pool[0]["key"]])

        def fake_executor(folder, task, record, output):
            output.mkdir(parents=True, exist_ok=True)
            current = fitz.open(folder / "translated-zh.pdf")
            current[0].insert_text((72, 100), "updated title")
            translated = output / "translated-zh.repaired.pdf"
            current.save(translated)
            current.close()
            plan = output / "page-plan.repaired.json"
            plan.write_text((folder / "page-plan.json").read_text())
            qa = output / "qa-repaired.json"
            qa.write_text(json.dumps({
                "status": "passed",
                "summary": {"red": 0, "orange": 0, "warning": 0},
                "pages": [
                    {"pdf_page": 1, "status": "pass", "issues": []},
                    {"pdf_page": 2, "status": "pass", "issues": []},
                ],
            }))
            dual = output / "bilingual-side-by-side.repaired.pdf"
            merge(folder / "original.pdf", translated, dual)
            return {
                "non_target_integrity": {"checked_pages": [2], "mismatched_pages": []},
                "translation_metrics": {"requests": 1},
            }, {"translated": translated, "plan": plan, "qa": qa, "dual": dual}

        fake_audit = {
            "version": 2,
            "status": "passed",
            "summary": {"red": 0, "orange": 0, "warning": 0},
            "document_issues": [],
            "pages": [
                {"pdf_page": 1, "status": "pass", "issues": []},
                {"pdf_page": 2, "status": "pass", "issues": []},
            ],
            "flagged_pages": [],
            "contract": {},
        }
        with patch("repair_batch.audit", return_value=fake_audit):
            candidate = run_one_click_repair_batch(
                self.folder, self.task, batch["batch_id"], repair_executor=fake_executor,
            )
        self.assertEqual(candidate["status"], "candidate_ready")

        observations = run_candidate_observations(
            self.folder,
            self.task,
            batch["batch_id"],
            observation_provider=lambda batch_record, preview_page, patch: (_ for _ in ()).throw(TimeoutError("timeout")),
        )
        self.assertEqual(observations[0]["status"], "unavailable")
        self.assertEqual(
            json.loads(candidate_observation_path(self.folder, batch["batch_id"], 1).read_text())["message"],
            "标注不可用",
        )
        accepted = accept_candidate(self.folder, self.task, batch["batch_id"])
        self.assertIn("RepairBatch", accepted["message"])

    def test_expired_running_candidate_observation_is_retried(self):
        self.reviewed_approved_comment(1)
        pool = approved_repair_pool(self.folder, self.task)
        batch = create_one_click_repair_batch(self.folder, self.task, [pool[0]["key"]])

        def fake_executor(folder, task, record, output):
            output.mkdir(parents=True, exist_ok=True)
            current = fitz.open(folder / "translated-zh.pdf")
            current[0].insert_text((72, 100), "updated title")
            translated = output / "translated-zh.repaired.pdf"
            current.save(translated)
            current.close()
            plan = output / "page-plan.repaired.json"
            plan.write_text((folder / "page-plan.json").read_text())
            qa = output / "qa-repaired.json"
            qa.write_text(json.dumps({
                "status": "passed",
                "summary": {"red": 0, "orange": 0, "warning": 0},
                "pages": [
                    {"pdf_page": 1, "status": "pass", "issues": []},
                    {"pdf_page": 2, "status": "pass", "issues": []},
                ],
            }))
            dual = output / "bilingual-side-by-side.repaired.pdf"
            merge(folder / "original.pdf", translated, dual)
            return {
                "non_target_integrity": {"checked_pages": [2], "mismatched_pages": []},
                "translation_metrics": {"requests": 1},
            }, {"translated": translated, "plan": plan, "qa": qa, "dual": dual}

        fake_audit = {
            "version": 2,
            "status": "passed",
            "summary": {"red": 0, "orange": 0, "warning": 0},
            "document_issues": [],
            "pages": [
                {"pdf_page": 1, "status": "pass", "issues": []},
                {"pdf_page": 2, "status": "pass", "issues": []},
            ],
            "flagged_pages": [],
            "contract": {},
        }
        with patch("repair_batch.audit", return_value=fake_audit):
            candidate = run_one_click_repair_batch(
                self.folder, self.task, batch["batch_id"], repair_executor=fake_executor,
            )
        self.assertEqual(candidate["status"], "candidate_ready")
        path = candidate_observation_path(self.folder, batch["batch_id"], 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": "candidate-page-observation/v1",
            "status": "running",
            "provider": "claude",
            "pdf_page": 1,
            "created_at": 1,
        }))
        calls = {"count": 0}

        def observer(batch_record, preview_page, patch):
            calls["count"] += 1
            return {
                "repair_family": "layout",
                "confidence": 0.8,
                "reading_order_ok": True,
                "reading_order_note": "order ok",
                "protected_content_ok": True,
                "protected_content_note": "content ok",
                "comment_issue_improved": True,
                "comment_issue_note": "improved",
                "observations": [],
            }

        observations = run_candidate_observations(
            self.folder, self.task, batch["batch_id"], observation_provider=observer,
        )
        self.assertEqual(calls["count"], 1)
        self.assertEqual(observations[0]["status"], "ready")
        self.assertEqual(json.loads(path.read_text())["status"], "ready")


def list_comments_for_test(folder: Path):
    from review_cycle import list_comments
    return list_comments(folder)


if __name__ == "__main__":
    unittest.main()
