"""Fast adjustments must not replay obsolete values or roll back newer UI state."""
import unittest
from unittest import mock

import _isolation  # noqa: F401
from test_device_features import ReconnectHost, FakeSignal
from mimonitor_toolbox import device_features


class AdjustmentQueueTests(unittest.TestCase):
    def host(self):
        host = ReconnectHost()
        host.adb_connected = True
        host.adb.ensure_connected = lambda: (True, "device")
        host.adb_action_finished = FakeSignal(host._finish_adb_action)
        return host

    def test_dragging_keeps_only_latest_waiting_value(self):
        host, workers, writes, completed = self.host(), [], [], []
        with mock.patch.object(device_features, "async_run", side_effect=workers.append):
            for value in (10, 20, 30):
                host._run_adb_action("亮度", lambda v=value: writes.append(v),
                    lambda v=value: completed.append(v), lambda: self.fail("Obsolete value rolled back UI"),
                    coalesce_key="setting:brightness")
        for worker in workers:
            worker()
        self.assertEqual(writes, [30])
        self.assertEqual(completed, [30])

    def test_an_inflight_result_cannot_override_newer_slider_state(self):
        host, workers, completed = self.host(), [], []
        with mock.patch.object(device_features, "async_run", side_effect=workers.append):
            def first_write():
                host._run_adb_action("亮度", lambda: None, lambda: completed.append(20),
                                     coalesce_key="setting:brightness")
            host._run_adb_action("亮度", first_write, lambda: completed.append(10),
                                 coalesce_key="setting:brightness")
            workers[0]()
            workers[1]()
        self.assertEqual(completed, [20])

    def test_mode_changes_are_not_coalesced_or_reordered(self):
        host, workers, writes = self.host(), [], []
        with mock.patch.object(device_features, "async_run", side_effect=workers.append):
            for mode in (13, 59):
                host._run_adb_action("模式", lambda m=mode: writes.append(m))
        for worker in workers:
            worker()
        self.assertEqual(writes, [13, 59])
