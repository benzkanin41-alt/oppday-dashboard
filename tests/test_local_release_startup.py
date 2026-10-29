import unittest
import urllib.error
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import publish_release as publisher


class LocalStartupTests(unittest.TestCase):
    def setUp(self):
        self.registered = {"url": "http://127.0.0.1:12015/", "entry_point": "registered-launcher.ps1"}

    def test_ready_local_is_reused_without_a_second_server(self):
        with (mock.patch.object(publisher, "probe_local", return_value={"releaseId": "prior"}),
              mock.patch.object(publisher, "launch_registered_dashboard") as launcher):
            self.assertEqual(publisher.ensure_local_running(self.registered)["status"], "already_running")
            launcher.assert_not_called()

    def test_closed_local_starts_only_the_registered_launcher(self):
        with (mock.patch.object(publisher, "probe_local", side_effect=[urllib.error.URLError("closed"), {"releaseId": "prior"}]),
              mock.patch.object(publisher, "launch_registered_dashboard") as launcher):
            self.assertEqual(publisher.ensure_local_running(self.registered)["status"], "started")
            launcher.assert_called_once_with(self.registered)

    def test_wrong_service_or_snapshot_is_not_replaced(self):
        with (mock.patch.object(publisher, "probe_local", side_effect=ValueError("wrong service")),
              mock.patch.object(publisher, "launch_registered_dashboard") as launcher):
            with self.assertRaisesRegex(ValueError, "wrong service"):
                publisher.ensure_local_running(self.registered)
            launcher.assert_not_called()

    def test_launcher_uses_private_files_not_inheritable_capture_pipes(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            with (mock.patch.object(publisher.store, "WORK", work),
                  mock.patch.object(publisher.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run):
                publisher.launch_registered_dashboard(self.registered)
                self.assertEqual(run.call_args.args[0][-1], self.registered["entry_point"])
                self.assertEqual(run.call_args.kwargs["stdin"], publisher.subprocess.DEVNULL)
                for stream in ("stdout", "stderr"):
                    self.assertNotEqual(run.call_args.kwargs[stream], publisher.subprocess.PIPE)
                    Path(run.call_args.kwargs[stream].name).relative_to(work)
                self.assertEqual(run.call_args.kwargs["timeout"], 90)
                self.assertNotIn("capture_output", run.call_args.kwargs)

    def test_launcher_failure_is_not_a_successful_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (mock.patch.object(publisher.store, "WORK", Path(temporary)),
                  mock.patch.object(publisher.subprocess, "run", return_value=SimpleNamespace(returncode=1))):
                with self.assertRaisesRegex(RuntimeError, "launcher failed"):
                    publisher.launch_registered_dashboard(self.registered)
