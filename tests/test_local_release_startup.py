import unittest
import urllib.error
from unittest import mock

from scripts import publish_release as publisher


class LocalStartupTests(unittest.TestCase):
    def setUp(self):
        self.registered = {"url": "http://127.0.0.1:12015/", "entry_point": "registered-launcher.ps1"}

    def test_ready_local_is_reused_without_a_second_server(self):
        with (mock.patch.object(publisher, "probe_local", return_value={"releaseId": "prior"}),
              mock.patch.object(publisher, "command") as command):
            self.assertEqual(publisher.ensure_local_running(self.registered)["status"], "already_running")
            command.assert_not_called()

    def test_closed_local_starts_only_the_registered_launcher(self):
        with (mock.patch.object(publisher, "probe_local", side_effect=[urllib.error.URLError("closed"), {"releaseId": "prior"}]),
              mock.patch.object(publisher, "command") as command):
            self.assertEqual(publisher.ensure_local_running(self.registered)["status"], "started")
            self.assertEqual(command.call_args.args[0][-1], self.registered["entry_point"])

    def test_wrong_service_or_snapshot_is_not_replaced(self):
        with (mock.patch.object(publisher, "probe_local", side_effect=ValueError("wrong service")),
              mock.patch.object(publisher, "command") as command):
            with self.assertRaisesRegex(ValueError, "wrong service"):
                publisher.ensure_local_running(self.registered)
            command.assert_not_called()
