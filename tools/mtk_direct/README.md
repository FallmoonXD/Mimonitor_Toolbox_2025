# MtkDirectTool

`MtkDirectTool.jar` is bundled at `assets/runtime/MtkDirectTool.jar`.
MonitorToolbox deploys it to the display and runs it through `TvService`.

It provides:

- generic MTK config `get`, `set`, `getMinMax`, and `dump`
- `batchGet <key...>` to read multiple MTK config keys in one TvService call
- `setColorGains <red> <green> <blue>` for custom color temperature gain
- `setHdrToneMapping <mtkValue> [isUpdate]` for HDR tone mapping; this mirrors
  Xiaomi's native path by also calling `IMiTVProvider.setHdrAttr(4, value)`

The color gain command uses the factory white-balance API
`MtkTvFApiDisplay.setWbGainOffsetEx(...)` so red, green, and blue are committed
as one group. Writing the three `g_video__clr_gain_*` keys independently can
make the firmware restore untouched channels to `1024`.

Rebuild the bundled jar from `MtkDirectTool.java` after changing this source.

`getPictureState <result-file>` is getter-only. It reads the native picture mode,
Dolby signal flag, and HDR tone, including scene/signal guards before and after.
It uses a unique versioned result instead of the shared logcat or batch result.

For checked writes, `setPictureModeChecked <native-mode> <update> <expected-bank> <result-file>`,
`setColorGainsChecked <r> <g> <b> <expected-bank> <result-file>` and
`setHdrToneMappingChecked <mtk> <update> <expected-bank> <result-file>` produce a versioned result
in a unique `.mtk_action_<token>.txt` file. It contains the native return code,
delayed native readback, scene before/after, and the separate Provider return for
tone mapping. Python rejects failed setters, mismatched readbacks, and scene
changes. Mode writes allow the requested bank change but require the same signal
family and stable Dolby flag. HDR tone writes require a confirmed HDR family;
Dolby and SDR are rejected before invoking the setter.
A nonzero/missing Provider return is retained as a warning when native
readback succeeds; observed 2025 firmware returns `-1` in this situation.
Legacy commands retain their existing result format.
An expected bank of `-1` preserves operation on firmware without a native scene
readback. When available, the captured bank is checked before any checked setter;
RGB also checks before changing custom color temperature.

The 2025 `OS3.0.109.0.UFFMAMN` getter capture is covered by
`tests/fixtures/redmi_2025_dolby_native.json`. Picture refresh and preset snapshots
use native RGB/tone values. Mode numbers are MTK numbers, not Xiaomi SceneMode
numbers: native Dolby game is 13 and Dolby custom is 61. After a verified native
mode write, Python synchronizes `picture_mode` and, for Dolby, `picture_mode_dolby`,
then verifies the final native state. Unavailable native signal state disables
mode writes. Unknown tone values retain their raw value and clear the old highlight.
