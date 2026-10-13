# ColorfulLedTool

Bundled as `assets/runtime/ColorfulLedTool.jar`, run through `TvService`.
The helper calls `IBspMServer/default` and `IVendorConfig.SetColorfulLed` using
reflection for the Android HIDL classes that are absent from the public SDK.

## 2025 OSD protocol

| OSD choice | Driver mode | Driver color |
| --- | --- | --- |
| Always on / breathe / colorful / marquee | 1 / 2 / 3 / 4 | OSD color index + 1, 1–12 |
| Screen color | 5 | 1 |
| Turn off | 5, then 0 | 0, then saved OSD color index |

The desktop uses `raw <mode> <color> <result-file>` with a unique
`.led_action_<token>.txt` result containing mode, color, driver return and a
completion marker. A failed/missing driver receipt stops OSD settings writes.
The four settings are read fresh before each operation and verified afterward:

```text
atmosphere_light_switcher
atmosphere_light_effect
atmosphere_light_preset_color
atmosphere_light_same_color
```

Legacy PM2 commands remain in the helper for source compatibility; the 2025
desktop does not expose or call illumination, brightness or color-temperature
commands. Rebuild the jar after changing the Java source.
