from __future__ import annotations

import copy
import itertools
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import publish_release as publisher  # noqa: E402


COMMIT = "a" * 40
PRIOR_COMMIT = "b" * 40
BUBBLE_COMMIT = "c" * 40


def pages_run(number, *, commit=COMMIT, status="completed", conclusion="success"):
    return {
        "databaseId": number,
        "headSha": commit,
        "workflowName": "Deploy GitHub Pages",
        "status": status,
        "conclusion": conclusion,
        "url": f"https://example.invalid/actions/runs/{number}",
        "createdAt": f"2026-10-28T00:{number % 60:02d}:00Z",
    }


class IsolatedPublisherTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.patch(publisher.subprocess, "run", side_effect=AssertionError("real process forbidden"))
        self.patch(publisher.urllib.request, "urlopen", side_effect=AssertionError("real HTTP forbidden"))
        self.patch(publisher, "command", side_effect=AssertionError("unmocked command forbidden"))
        self.patch(publisher, "git", side_effect=AssertionError("unmocked Git forbidden"))
        self.patch(publisher, "fetch", side_effect=AssertionError("unmocked HTTP forbidden"))
        self.patch(publisher.store, "write_json_atomic", side_effect=AssertionError("production write forbidden"))
        self.patch(publisher.snapshots, "export_release", side_effect=AssertionError("production export forbidden"))
        self.patch(publisher.snapshots, "promote_release", side_effect=AssertionError("production promotion forbidden"))
        self.patch(publisher.snapshots, "release_lock", side_effect=AssertionError("production lock forbidden"))
        self.emit = self.patch(publisher, "emit")

    def patch(self, target, name, **kwargs):
        return self.stack.enter_context(mock.patch.object(target, name, **kwargs))


class PagesRetryTests(IsolatedPublisherTest):
    def setUp(self):
        super().setUp()
        self.listings = []
        self.poll_count = 0
        self.dispatches = []
        self.ancestors = set()
        self.command = self.patch(publisher, "command", side_effect=self.fake_command)
        self.git = self.patch(publisher, "git", side_effect=self.fake_git)
        self.patch(publisher.time, "sleep")
        self.patch(publisher.time, "monotonic", side_effect=itertools.count())

    def fake_command(self, arguments, **kwargs):
        if arguments[:3] == ["gh", "run", "list"]:
            index = min(self.poll_count, len(self.listings) - 1)
            self.poll_count += 1
            return json.dumps(self.listings[index])
        if arguments[:3] == ["gh", "workflow", "run"]:
            self.dispatches.append(arguments)
            return ""
        raise AssertionError(f"Unexpected command: {arguments!r}")

    def fake_git(self, *arguments):
        if arguments == ("fetch", "origin", "main"):
            return ""
        if arguments[:2] == ("merge-base", "--is-ancestor"):
            if arguments[2:] in self.ancestors:
                return ""
            raise RuntimeError("not an ancestor")
        raise AssertionError(f"Unexpected Git call: {arguments!r}")

    def test_old_failure_does_not_abort_new_running_attempt_then_success(self):
        old_failed = pages_run(101, conclusion="failure")
        running = pages_run(102, status="in_progress", conclusion=None)
        successful = pages_run(102)
        self.listings = [[running, old_failed], [successful, old_failed]]

        result = publisher.wait_pages(COMMIT, timeout=30)

        self.assertEqual(result["databaseId"], 102)
        self.assertGreaterEqual(self.poll_count, 2)
        self.assertEqual(self.dispatches, [], "An existing running retry must not be duplicated")

    def test_same_commit_success_is_preferred_to_old_failure_in_either_order(self):
        failed, successful = pages_run(101, conclusion="failure"), pages_run(102)
        for listing in ([failed, successful], [successful, failed]):
            with self.subTest(listing=listing):
                self.listings = [listing]
                self.poll_count = 0
                self.assertEqual(publisher.wait_pages(COMMIT, timeout=30)["databaseId"], 102)
        self.assertEqual(self.dispatches, [])

    def test_successful_bubble_descendant_is_considered_before_exact_run_failure(self):
        failed = pages_run(101, conclusion="failure")
        bubble = pages_run(102, commit=BUBBLE_COMMIT)
        self.listings = [[bubble, failed]]
        self.ancestors.add((COMMIT, BUBBLE_COMMIT))

        result = publisher.wait_pages(COMMIT, timeout=30)

        self.assertEqual(result["headSha"], BUBBLE_COMMIT)
        self.git.assert_any_call("merge-base", "--is-ancestor", COMMIT, BUBBLE_COMMIT)
        self.assertEqual(self.dispatches, [])

    def test_failed_unchanged_commit_dispatches_pages_main_once_then_waits(self):
        failed = pages_run(101, conclusion="failure")
        queued = pages_run(102, status="queued", conclusion=None)
        successful = pages_run(102)
        # The old failure can remain the sole listing briefly after dispatch.
        self.listings = [[failed], [failed], [queued, failed], [successful, failed]]

        result = publisher.wait_pages(COMMIT, timeout=30)

        self.assertEqual(result["databaseId"], 102)
        self.assertEqual(len(self.dispatches), 1)
        dispatch = self.dispatches[0]
        self.assertIn("pages.yml", dispatch)
        self.assertEqual(dispatch[dispatch.index("--ref") + 1], "main")
        self.assertEqual(dispatch[dispatch.index("--repo") + 1], publisher.REPOSITORY)
        self.assertGreaterEqual(self.poll_count, 4)

    def test_successful_unrelated_commit_is_not_accepted_as_a_release_descendant(self):
        self.listings = [[pages_run(102, commit=BUBBLE_COMMIT)]]
        with self.assertRaises(TimeoutError):
            publisher.wait_pages(COMMIT, timeout=8)
        self.git.assert_any_call("merge-base", "--is-ancestor", COMMIT, BUBBLE_COMMIT)


class PublishRecoveryTests(IsolatedPublisherTest):
    def setUp(self):
        super().setUp()
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(temporary).resolve()
        self.work = self.root / ".oppday-work"
        self.releases = self.work / "releases"
        self.current_path = self.releases / "current.json"
        self.current_path.parent.mkdir(parents=True)
        self.previous = "release-previous"
        self.candidate = "release-candidate"
        self.previous_pointer = {
            "releaseId": self.previous,
            "indexSha256": "old-index-hash",
            "promotedAt": "2026-10-27T00:00:00Z",
            "verification": {"ok": True, "commit": PRIOR_COMMIT},
        }
        self.current_path.write_text(json.dumps(self.previous_pointer), encoding="utf-8")
        self.current = copy.deepcopy(self.previous_pointer)
        self.remote_release = self.previous
        self.working_release = self.previous
        self.events = []
        self.writes = []
        self.fail_stage = None
        self.rollback_fail_stage = None
        self.pointer_restore_error = None
        self.failure_text = "candidate verification failed"
        self.rollback_failure_text = "rollback publication failed"

        for name, value in {
            "ROOT": self.root, "WORK": self.work, "RELEASES": self.releases,
            "CURRENT": self.current_path, "PROFILE": self.work / "project-profile.json",
        }.items():
            self.patch(publisher.store, name, new=value)
        self.patch(publisher, "ROOT", new=self.root)
        self.patch(publisher.snapshots, "ROOT", new=self.root)
        self.patch(publisher.store, "read_json", side_effect=self.fake_read_json)
        self.patch(publisher.store, "write_json_atomic", side_effect=self.fake_write_json)
        self.patch(publisher.store, "release_directory", side_effect=lambda name: self.releases / name)
        self.patch(publisher.store, "current_pointer", side_effect=lambda: copy.deepcopy(self.current))
        self.verify_release = self.patch(publisher.snapshots, "verify_release", side_effect=self.fake_verify_release)
        self.patch(publisher.snapshots, "release_lock", side_effect=nullcontext)
        self.patch(publisher.snapshots, "export_release", side_effect=self.fake_export)
        self.promote = self.patch(publisher.snapshots, "promote_release", side_effect=self.fake_promote)
        self.patch(publisher, "registered_dashboard", return_value={"url": "http://example.invalid/", "root": str(self.root)})
        self.patch(publisher, "ensure_local_running", return_value={"status": "already_running"})
        self.sync_remote = self.patch(publisher, "sync_remote")
        self.publish_files = self.patch(publisher, "publish_files", side_effect=self.fake_publish_files)
        self.wait_pages = self.patch(publisher, "wait_pages", side_effect=self.fake_wait_pages)
        self.verify_online = self.patch(publisher, "verify_online", side_effect=self.fake_verify_online)
        self.verify_local = self.patch(publisher, "verify_local", side_effect=self.fake_verify_local)
        self.patch(publisher, "git", side_effect=self.fake_git)

    def index(self, release_id):
        items = [{"id": "old-item"}]
        if release_id == self.candidate:
            items.append({"id": "new-item"})
        return {"releaseId": release_id, "items": items, "stats": {"items": len(items)}}

    def fake_read_json(self, path):
        path = Path(path)
        if path == self.current_path:
            return copy.deepcopy(self.current)
        if path == self.root / "docs/data/index.json":
            return self.index(self.working_release)
        for release_id in (self.candidate, self.previous):
            directory = self.releases / release_id
            if path == directory / "manifest.json":
                return {
                    "releaseId": release_id, "previousReleaseId": self.previous,
                    "selectedItemIds": ["new-item"] if release_id == self.candidate else [],
                    "indexSha256": self.index_hash(release_id),
                }
            if path == directory / "public/data/index.json":
                return self.index(release_id)
        raise AssertionError(f"Unexpected read outside fixture: {path}")

    def fake_write_json(self, path, payload):
        path = Path(path)
        try:
            path.relative_to(self.work)
        except ValueError as exc:
            raise AssertionError(f"Write must stay in private fixture: {path}") from exc
        payload = copy.deepcopy(payload)
        self.events.append(("write", path.name))
        if path == self.current_path and payload == self.previous_pointer and self.pointer_restore_error:
            raise OSError(self.pointer_restore_error)
        self.writes.append((path, payload))
        if path == self.current_path:
            self.current = payload

    def index_hash(self, release_id):
        return "new-index-hash" if release_id == self.candidate else "old-index-hash"

    def commit(self, release_id):
        return COMMIT if release_id == self.candidate else PRIOR_COMMIT

    def fake_verify_release(self, release_id, **kwargs):
        return {
            "ok": True, "releaseId": release_id, "items": len(self.index(release_id)["items"]),
            "indexSha256": self.index_hash(release_id), "previousReleaseId": self.previous,
        }

    def fail_if_requested(self, stage, release_id):
        if release_id == self.candidate and self.fail_stage == stage:
            raise RuntimeError(self.failure_text)
        if release_id == self.previous and self.rollback_fail_stage == stage:
            raise RuntimeError(self.rollback_failure_text)

    def fake_export(self, release_id):
        self.events.append(("export", release_id))
        self.working_release = release_id
        return self.fake_verify_release(release_id)

    def fake_publish_files(self, release_id):
        self.events.append(("publish_files", release_id))
        if release_id == self.previous:
            self.fail_if_requested("publish_files", release_id)
        self.working_release = release_id
        self.remote_release = release_id
        # Simulate an exception after the push, not a harmless preflight error.
        if release_id == self.candidate:
            self.fail_if_requested("publish_files", release_id)
        return self.commit(release_id)

    def fake_wait_pages(self, commit, **kwargs):
        release_id = self.candidate if commit == COMMIT else self.previous
        self.events.append(("wait_pages", release_id))
        self.fail_if_requested("wait_pages", release_id)
        return pages_run(102 if release_id == self.candidate else 101, commit=commit)

    def fake_verify_online(self, release_id, commit, **kwargs):
        self.events.append(("verify_online", release_id))
        self.fail_if_requested("verify_online", release_id)
        self.assertEqual(self.remote_release, release_id)
        return {"ok": True, "releaseId": release_id, "commit": commit,
                "indexSha256": self.index_hash(release_id)}

    def fake_promote(self, release_id, verification, **kwargs):
        self.events.append(("promote", release_id))
        self.assertTrue(verification["ok"])
        self.assertIn(("verify_online", release_id), self.events)
        publisher.store.write_json_atomic(self.current_path, {
            "releaseId": release_id, "indexSha256": self.index_hash(release_id),
        })
        self.fail_if_requested("promote", release_id)
        return {"ok": True, "promoted": True, "releaseId": release_id}

    def fake_verify_local(self, release_id, registered):
        self.events.append(("verify_local", release_id))
        self.fail_if_requested("verify_local", release_id)
        self.assertEqual(self.current["releaseId"], release_id)
        return {"ok": True, "releaseId": release_id, "url": registered["url"]}

    def fake_git(self, *arguments):
        if arguments[:1] == ("rev-parse",):
            return self.commit(self.working_release)
        if arguments[:1] == ("ls-remote",):
            return self.commit(self.remote_release) + "\trefs/heads/main"
        if arguments[:1] == ("show",):
            return json.dumps(self.index(self.remote_release))
        if arguments[:1] == ("status",):
            return ""
        if arguments[:1] in (("fetch",), ("rebase",)):
            return ""
        if arguments == ("push", "origin", "main"):
            self.remote_release = self.working_release
            return ""
        raise AssertionError(f"Unexpected Git call: {arguments!r}")

    def invoke_failure(self):
        try:
            result = publisher.publish(self.candidate)
        except AssertionError:
            raise
        except Exception as exc:
            return None, exc
        self.assertIsInstance(result, dict)
        self.assertIsNot(result.get("complete"), True)
        return result, None

    def assert_no_false_completion(self, result):
        if result is not None:
            self.assertIsNot(result.get("complete"), True)
        for path, payload in self.writes:
            if payload.get("releaseId") == self.candidate:
                self.assertIsNot(payload.get("complete"), True, f"False completion in {path}")
        self.assertFalse(any(call.args and call.args[0] == "complete" for call in self.emit.call_args_list))

    def assert_recovered_failure(self):
        result, error = self.invoke_failure()
        self.assertEqual(self.current, self.previous_pointer, "Restore the exact prior pointer")
        self.assertEqual(self.remote_release, self.previous, "Restore the prior public release")
        self.assertIn(("verify_online", self.previous), self.events)
        self.assert_no_false_completion(result)
        diagnostics = str(error) + json.dumps(result) + json.dumps([payload for _, payload in self.writes])
        self.assertIn(self.failure_text, diagnostics)

    def assert_degraded_journal(self, *errors):
        journals = [payload for path, payload in self.writes if path != self.current_path]
        diagnostics = json.dumps(journals)
        for error in errors:
            self.assertIn(error, diagnostics, "Journal must retain every recovery failure")

        def is_degraded(value):
            if isinstance(value, dict):
                if value.get("degraded") is True or value.get("status") == "degraded":
                    return True
                return any(is_degraded(nested) for nested in value.values())
            if isinstance(value, list):
                return any(is_degraded(nested) for nested in value)
            return False

        self.assertTrue(is_degraded(journals), "Private journal must explicitly report degraded recovery")

    def test_success_promotes_only_after_online_verification_then_checks_local(self):
        result = publisher.publish(self.candidate, full_verification=True)

        self.assertIs(result.get("complete"), True)
        self.assertEqual(self.current["releaseId"], self.candidate)
        self.assertEqual(self.remote_release, self.candidate)
        self.assertLess(self.events.index(("verify_online", self.candidate)), self.events.index(("promote", self.candidate)))
        self.assertLess(self.events.index(("promote", self.candidate)), self.events.index(("verify_local", self.candidate)))
        self.verify_online.assert_any_call(self.candidate, COMMIT, all_payloads=True)
        self.assertNotIn(("publish_files", self.previous), self.events)

    def test_post_push_publish_files_error_restores_previous_pointer_and_public(self):
        self.fail_stage = "publish_files"
        self.assert_recovered_failure()

    def test_pages_wait_failure_restores_previous_pointer_and_public(self):
        self.fail_stage = "wait_pages"
        self.assert_recovered_failure()

    def test_online_mismatch_attempts_verified_rollback(self):
        self.fail_stage = "verify_online"
        self.assert_recovered_failure()
        self.promote.assert_not_called()

    def test_local_mismatch_restores_previous_pointer_and_public(self):
        self.fail_stage = "verify_local"
        self.assert_recovered_failure()

    def test_promotion_exception_after_pointer_change_restores_previous_pointer(self):
        self.fail_stage = "promote"
        self.assert_recovered_failure()

    def test_failed_rollback_is_journaled_as_degraded_with_both_errors(self):
        self.fail_stage = "verify_local"
        self.rollback_fail_stage = "publish_files"

        result, _ = self.invoke_failure()

        self.assertEqual(self.current, self.previous_pointer)
        self.assert_no_false_completion(result)
        self.assert_degraded_journal(self.failure_text, self.rollback_failure_text)

    def test_locked_prior_pointer_restore_is_journaled_as_degraded(self):
        self.fail_stage = "verify_local"
        self.pointer_restore_error = "prior current.json is locked"

        result, _ = self.invoke_failure()

        self.assert_no_false_completion(result)
        self.assert_degraded_journal(self.failure_text, self.pointer_restore_error)

    def test_failed_candidate_preflight_does_not_publish_or_promote(self):
        self.verify_release.side_effect = ValueError("invalid candidate hash")
        with self.assertRaisesRegex(ValueError, "invalid candidate hash"):
            publisher.publish(self.candidate)
        self.publish_files.assert_not_called()
        self.promote.assert_not_called()
        self.assertEqual(self.current, self.previous_pointer)
        self.assertEqual(self.remote_release, self.previous)

    def qualified_manifest(self):
        def read(path):
            value = self.fake_read_json(path)
            if Path(path) == self.releases / self.candidate / "manifest.json":
                value["qualificationId"] = "current"
            return value
        self.patch(publisher.store, "read_json", side_effect=read)

    def test_prepared_qualification_is_revalidated_before_any_public_write(self):
        from scripts import requalification
        self.qualified_manifest()
        with mock.patch.object(requalification, "verify_prepared_release", side_effect=ValueError("authorization revoked")):
            with self.assertRaisesRegex(ValueError, "authorization revoked"):
                publisher.publish(self.candidate)
        self.publish_files.assert_not_called()
        self.promote.assert_not_called()
        self.assertEqual(self.remote_release, self.previous)

    def test_mid_publication_qualification_revocation_recovers_without_local_promotion(self):
        from scripts import requalification
        self.qualified_manifest()
        with mock.patch.object(requalification, "verify_prepared_release", side_effect=[{"pass": True}, ValueError("authorization revoked after online")]):
            with self.assertRaisesRegex(ValueError, "revoked after online"):
                publisher.publish(self.candidate)
        self.promote.assert_not_called()
        self.assertEqual(self.current, self.previous_pointer)
        self.assertEqual(self.remote_release, self.previous)
        self.assertIn(("verify_online", self.previous), self.events)

    def markdown_manifest(self):
        def read(path):
            value = self.fake_read_json(path)
            if Path(path) == self.releases / self.candidate / "manifest.json":
                value["markdownImportId"] = "md-only"
            return value
        self.patch(publisher.store, "read_json", side_effect=read)

    def test_md_import_authorization_rechecked_before_public_write(self):
        from scripts import markdown_import
        self.markdown_manifest()
        with mock.patch.object(markdown_import, "verify_prepared_release", side_effect=ValueError("MD authorization revoked")):
            with self.assertRaisesRegex(ValueError, "MD authorization revoked"):
                publisher.publish(self.candidate)
        self.publish_files.assert_not_called()
        self.promote.assert_not_called()

    def test_md_import_mid_publication_revocation_rolls_back(self):
        from scripts import markdown_import
        self.markdown_manifest()
        with mock.patch.object(markdown_import, "verify_prepared_release", side_effect=[{}, ValueError("MD revoked after online")]):
            with self.assertRaisesRegex(ValueError, "MD revoked after online"):
                publisher.publish(self.candidate)
        self.promote.assert_not_called()
        self.assertEqual(self.current, self.previous_pointer)
        self.assertEqual(self.remote_release, self.previous)


if __name__ == "__main__":
    unittest.main()
