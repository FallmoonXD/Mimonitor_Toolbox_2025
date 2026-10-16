import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import _isolation  # noqa: F401

from mimonitor_toolbox import adb as adb_runtime
from mimonitor_toolbox import device_features, presets
from mimonitor_toolbox.display_features import DisplayFeaturesMixin


class NativePictureReadTests(unittest.TestCase):
    def test_live_2025_dolby_fixture_overrides_stale_rgb_and_scene(self):
        native = json.loads((Path(__file__).parent / "fixtures/redmi_2025_dolby_native.json")
                            .read_text(encoding="utf-8"))["native"]
        values = {"picture_mode": 14, "picture_preset_scenario": 14,
                  "picture_red_gain": 1024, "picture_green_gain": 1024, "picture_blue_gain": 1024,
                  "settings_display_hdr_color_tone": 0}
        device_features.apply_picture_jni_overrides(values, native)
        device_features.apply_picture_signal_reads(values, native)
        host = SimpleNamespace(current_vals=values)
        self.assertEqual(DisplayFeaturesMixin._active_picture_scene_mode(host), 13)
        self.assertEqual([values[key] for key in ("picture_red_gain", "picture_green_gain", "picture_blue_gain")],
                         [1022, 1008, 942])
        self.assertEqual(values["picture_color_temperature"], 3)
        self.assertEqual(values["picture_mode"], 14)  # writable database enum is preserved

    def test_unavailable_signal_clears_cached_native_state_without_using_stale_database(self):
        values = {"g_video__picture_mode": 13, "g_dovi_info__": 1,
                  "picture_mode": 10, "picture_preset_scenario": 25}
        device_features.apply_picture_signal_reads(values, {"g_video__picture_mode": -1, "g_dovi_info__": "ERROR"})
        self.assertIsNone(values["g_video__picture_mode"])
        self.assertIsNone(values["g_dovi_info__"])
        self.assertIsNone(DisplayFeaturesMixin._active_picture_scene_mode(SimpleNamespace(current_vals=values)))

    def test_confirmed_dolby_does_not_borrow_a_stale_sdr_scene(self):
        values = {"g_video__picture_mode": None, "g_dovi_info__": 1,
                  "picture_mode": 14, "picture_preset_scenario": 14}
        self.assertIsNone(DisplayFeaturesMixin._active_picture_scene_mode(SimpleNamespace(current_vals=values)))

    def test_unknown_tone_clears_old_button_value_without_changing_the_raw_value(self):
        values = {"picture_hdr_tone_mapping": 5, "settings_display_hdr_color_tone": 0}
        device_features.apply_picture_jni_overrides(values, {"g_video__vid_hdr_tone_mapping_mode": 4})
        self.assertEqual(values["picture_hdr_tone_mapping"], 4)
        self.assertIsNone(values["settings_display_hdr_color_tone"])
        target = mock.Mock()
        with self.assertRaises(ValueError):
            presets._apply_hdr_tone_mapping(target, values)
        target.hdr_tone_mapping.assert_not_called()

    def test_negative_native_readbacks_do_not_overwrite_database_values(self):
        values = {"picture_red_gain": 987, "picture_local_dimming": 2, "picture_hdr_tone_mapping": 5}
        device_features.apply_picture_jni_overrides(values, {
            "g_video__clr_gain_r": -1, "g_video__vid_local_dimming": -1,
            "g_video__vid_hdr_tone_mapping_mode": -1})
        self.assertEqual(values, {"picture_red_gain": 987, "picture_local_dimming": 2,
                                  "picture_hdr_tone_mapping": 5})

    def test_snapshot_includes_native_tone_and_rgb_but_signal_fields_are_not_settings_writes(self):
        for key in ("g_video__vid_hdr_tone_mapping_mode", "g_video__clr_gain_r",
                    "g_video__clr_gain_g", "g_video__clr_gain_b", "g_video__picture_mode", "g_dovi_info__"):
            self.assertIn(key, presets.PICTURE_PRESET_JNI_KEYS)
            self.assertNotIn(key, presets.PICTURE_PRESET_SETTINGS_KEYS)

    def test_unsupported_optional_getter_does_not_break_existing_snapshot_reads(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "jni_batch_get", return_value={"g_disp__disp_back_light": 100}), \
                mock.patch.object(target, "jni_get", side_effect=RuntimeError("unsupported")) as getter:
            values = target.jni_batch_get_or_single(
                ["g_disp__disp_back_light", "g_dovi_info__"], check=True, optional_keys=["g_dovi_info__"])
        self.assertEqual(values, {"g_disp__disp_back_light": 100})
        getter.assert_called_once_with("g_dovi_info__", check=False)

    def test_required_native_getter_failure_still_aborts_snapshot(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "jni_batch_get", return_value={}), \
                mock.patch.object(target, "jni_get", side_effect=RuntimeError("read failed")):
            with self.assertRaisesRegex(RuntimeError, "read failed"):
                target.jni_batch_get_or_single(["g_disp__disp_back_light"], check=True)


def tone_receipt(native_return=0, provider_return=-1, readback=5, before=16, after=16):
    return (f"__version=1\n__action=setHdrToneMapping\nnative_return={native_return}\n"
            f"provider_return={provider_return}\nreadback.g_video__vid_hdr_tone_mapping_mode={readback}\n"
            f"bank_before={before}\nbank_after={after}\n__complete=1\n")


class NativeActionResultTests(unittest.TestCase):
    expected = {"g_video__vid_hdr_tone_mapping_mode": 5}

    def test_2025_provider_nonzero_is_preserved_as_partial_completion(self):
        result = adb_runtime.parse_native_action_result(tone_receipt(), "setHdrToneMapping", self.expected)
        self.assertTrue(result["native_verified"])
        self.assertEqual(result["provider_return"], -1)
        self.assertIn("Provider 返回 -1", result["warnings"][0])

    def test_native_failure_is_not_hidden_by_matching_readback(self):
        with self.assertRaisesRegex(RuntimeError, "setter 返回 -1"):
            adb_runtime.parse_native_action_result(tone_receipt(native_return=-1), "setHdrToneMapping", self.expected)

    def test_wrong_native_readback_is_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, "回读不一致"):
            adb_runtime.parse_native_action_result(tone_receipt(readback=0), "setHdrToneMapping", self.expected)

    def test_signal_switch_during_write_is_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, "场景变化"):
            adb_runtime.parse_native_action_result(tone_receipt(after=13), "setHdrToneMapping", self.expected)

    def test_truncated_or_wrong_action_result_cannot_be_accepted(self):
        for output in (tone_receipt().replace("__complete=1", ""),
                       tone_receipt().replace("setHdrToneMapping", "setColorGains"), "0"):
            with self.subTest(output=output), self.assertRaisesRegex(RuntimeError, "结果不完整"):
                adb_runtime.parse_native_action_result(output, "setHdrToneMapping", self.expected)

    def test_unavailable_provider_and_bank_are_not_reported_as_verified(self):
        result = adb_runtime.parse_native_action_result(tone_receipt(provider_return="N/A", before=-1, after=-1),
                                                       "setHdrToneMapping", self.expected)
        self.assertIsNone(result["provider_return"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_fully_successful_tone_write_has_no_warning(self):
        result = adb_runtime.parse_native_action_result(tone_receipt(provider_return=0), "setHdrToneMapping", self.expected)
        self.assertEqual(result["warnings"], [])

    def test_checked_action_uses_session_and_a_unique_receipt(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "check_and_heal_jar"), \
                mock.patch.object(target, "read_picture_state", return_value={"g_video__picture_mode": 16, "g_dovi_info__": 0}), \
                mock.patch.object(target, "_session_call", return_value=tone_receipt()) as call, \
                mock.patch.object(adb_runtime.uuid, "uuid4", return_value=SimpleNamespace(hex="abc")):
            result = target.hdr_tone_mapping(5, check=True)
        call.assert_called_once_with("native", ["setHdrToneMappingChecked", 5, 3, 16,
            "/sdcard/Download/Mimonitor_Toolbox/.mtk_action_abc.txt"])
        self.assertEqual(result["provider_return"], -1)

    def test_checked_action_does_not_repeat_write_when_validation_fails(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "check_and_heal_jar"), \
                mock.patch.object(target, "read_picture_state", return_value={"g_video__picture_mode": 16, "g_dovi_info__": 0}), \
                mock.patch.object(target, "_session_call", return_value=tone_receipt(readback=0)) as call:
            with self.assertRaises(RuntimeError):
                target.hdr_tone_mapping(5, check=True)
        self.assertEqual(call.call_count, 1)

    def test_preflight_bank_mismatch_stops_before_color_temperature_or_rgb_writes(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "jni_batch_get_or_single", return_value={"g_video__picture_mode": 16}), \
                mock.patch.object(target, "jni_set") as setter, \
                mock.patch.object(target, "jni_set_color_gains") as rgb:
            with self.assertRaisesRegex(RuntimeError, "停止写入"):
                target.require_picture_bank(13)
        setter.assert_not_called()
        rgb.assert_not_called()

    def test_rgb_receipt_cannot_accept_one_mismatched_channel(self):
        output = ("__version=1\n__action=setColorGains\nnative_return=0\nbank_before=13\nbank_after=13\n"
                  "readback.g_video__clr_gain_r=1022\nreadback.g_video__clr_gain_g=1008\n"
                  "readback.g_video__clr_gain_b=941\n__complete=1\n")
        with self.assertRaisesRegex(RuntimeError, "回读不一致"):
            adb_runtime.parse_native_action_result(output, "setColorGains",
                {"g_video__clr_gain_r": 1022, "g_video__clr_gain_g": 1008, "g_video__clr_gain_b": 942})
