"""Controls matched to the beekeeper 2025 OSD, OS3.0.109.0.UFFMAMN."""

SOURCE_CHOICES = ((23, "HDMI 1"), (24, "HDMI 2"), (29, "DP"))
LIGHT_KEYS = ("atmosphere_light_switcher", "atmosphere_light_effect",
              "atmosphere_light_preset_color", "atmosphere_light_same_color")
LIGHT_EFFECTS = ((0, "常亮"), (1, "呼吸"), (2, "七彩梦境"), (3, "七彩跑马灯"))
LIGHT_COLORS = tuple(enumerate(("深蓝色", "蓝色", "青色", "草绿色", "浅绿色", "金色",
                               "橘红色", "番茄色", "品红色", "紫色", "靛蓝色", "蓝紫色")))
OSD_NATIVE_KEYS = ("g_video__vid_gamma_mode", "g_fusion_picture__hdmi_rgb_range",
                   "g_video__clr_eye_protection_mode", "g_video__vid_od_response_time")
OSD_OPTIONS = {
    "dark_enhancement": ((0, "关"), (1, "低"), (2, "中"), (3, "高")),
    "color_range": ((0, "自动"), (1, "全范围"), (2, "有限范围")),
    "eye_protection": ((0, "关"), (1, "开")),
}


def validate_osd_option(option, value):
    if option not in OSD_OPTIONS or int(value) not in dict(OSD_OPTIONS[option]):
        raise ValueError("无效的 2025 OSD 选项")
    return int(value)


def light_commands(values):
    """Use the non-PM2 OSD protocol; never default missing live settings."""
    state = {key: int(values[key]) for key in LIGHT_KEYS}
    for key, bounds in zip(LIGHT_KEYS, ((0, 1), (0, 3), (0, 11), (0, 1))):
        if not bounds[0] <= state[key] <= bounds[1]:
            raise ValueError("无法确认当前炫彩灯设置")
    on, effect, color, same = (state[key] for key in LIGHT_KEYS)
    if not on:
        return [(5, 0), (0, color)]
    return [(5, 1)] if same else [(effect + 1, color + 1)]


def native_option_value(option, value, native):
    value = validate_osd_option(option, value)
    if option == "dark_enhancement":
        packed = int(native["g_video__vid_gamma_mode"])
        if packed < 0:
            raise ValueError("无法读取 Gamma 配置")
        # OSD stores black stretch in byte 2; preserve gamma and all other bits.
        return "g_video__vid_gamma_mode", (packed & ~0xFF00) | (value << 8)
    if option == "color_range":
        return "g_fusion_picture__hdmi_rgb_range", value
    return "g_video__clr_eye_protection_mode", value
