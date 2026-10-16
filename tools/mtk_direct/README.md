# MtkDirectTool

`MtkDirectTool.jar` is bundled at `assets/runtime/MtkDirectTool.jar`.
MonitorToolbox deploys it to the display and runs it through `TvService`.

It provides:

- `setSystemOptionChecked`: whitelisted 2025 system picture fields with bank and signal guards, native return codes and delayed readback

- generic MTK config `get`, `set`, `getMinMax`, and `dump`
- `batchGet <key...>` to read multiple MTK config keys in one TvService call
- `setColorGains <red> <green> <blue>` for custom color temperature gain
- `setHdrToneMapping <mtkValue> [isUpdate]` for HDR tone mapping; this mirrors
  Xiaomi's native path by also calling `IMiTVProvider.setHdrAttr(4, value)`

The color gain command uses the factory white-balance API
`MtkTvFApiDisplay.setWbGainOffsetEx(...)` so red, green, and blue are committed
as one group. Writing the three `g_video__clr_gain_*` keys independently can
make the firmware restore untouched channels to `1024`.

Rebuild the bundled jar after changing either Java source:

```powershell
python tools/build_native_helper.py --android-jar <android.jar> --d8 <d8.bat>
```

The build includes `MtkDirectTool` and `ToolboxSession`. Its source digest is
checked by the offline tests so the bundled DEX cannot silently lag the source.

The desktop now starts `ToolboxSession <unique-session-directory>` once and
reuses its TV class loader over an authenticated ADB loopback forward. Requests
and responses use length-prefixed UTF-8 frames. A READY/GO exchange prevents
abandoned queued commands from executing later. A lost reply never replays a
setter. Each native action resets its receipt fields and still performs fresh
native reads and the existing checked-write guards. Receipts return directly
over the socket; no shared result file or logcat is used by the desktop.
The worker also dispatches the existing ColorfulLedTool driver method without
starting another JVM. It exits after ten minutes without a connection.

`ToolboxSession <directory> readonly` rejects every action except `getBatch`
and `getPictureState`; this mode is used for nondisruptive device latency checks.
`getBatch <key...> <result-file>` uses the versioned receipt protocol and has no
fixed settling delay. Legacy one-shot commands remain available.

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

`setOsdOptionChecked <key> <value> <update> <expected-bank> <result-file>`
adds checked 2025 OSD writes using the same unique receipt protocol. Python
validates the option, current signal and HDMI/game restrictions before writing.
Dark enhancement changes only bits 8–15 of `g_video__vid_gamma_mode`, preserving
the gamma byte and other bits; HDMI range uses `g_fusion_picture__hdmi_rgb_range`.
Python mirrors settings only after native verification and checks the final state.
The desktop API rejects eye-protection writes: hardware testing found they switch
color temperature and reload custom white balance. The UI displays its state only.
