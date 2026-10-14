"""System picture settings from the beekeeper firmware, separate from monitor OSD."""

LEVELS = ((0, "关"), (1, "低"), (2, "中"), (3, "高"))
# Framework gamma 0..8 converts to these native values; the resource labels are -4..4.
GAMMA_OFFSETS = tuple(zip((4, 5, 3, 6, 2, 7, 1, 8, 9), map(str, range(-4, 5))))
SYSTEM_OPTIONS = {
    "gamma_offset": ("Gamma 偏移", "g_disp__disp_gamma", ("picture_gamma",), GAMMA_OFFSETS),
    "black_correction": ("黑色校正", "g_video__vid_black_stretch", ("picture_black_stretch",), LEVELS),
    "contrast_enhancement": ("对比度增强", "g_video__vid_luma", ("tv_picture_video_adaptive_luma_control",), LEVELS),
    "local_contrast": ("局部对比度", "g_video__vid_local_contrast", ("tv_picture_video_local_contrast_control",), LEVELS),
    "noise_reduction": ("动态降噪", "g_video__vid_3d_nr", ("tv_picture_advance_video_3d_dnr", "tv_picture_advance_video_dnr"), LEVELS),
    "mpeg_nr": ("MPEG 降噪", "g_video__vid_mpeg_nr", ("tv_picture_advance_video_mpeg_nr",), LEVELS),
    "smooth_gradient": ("平滑渐变", "g_video__vid_de_contour", ("mitv.settings.db.video.de_contour",), LEVELS),
    "super_resolution": ("超分辨率增强", "g_video__vid_aisr", ("mitv.settings.db.video.aisr",), ((0, "关"), (2, "开"))),
}
CMS_COLORS = ("red", "green", "blue", "cyan", "magenta", "yellow", "flesh")
CMS_NAMES = ("红", "绿", "蓝", "青", "品红", "黄", "肤色")
CMS_KEYS = ("g_fusion_picture__color_tuner_enable",) + tuple(
    "g_fusion_picture__color_tuner_" + axis + "_" + color
    for color in CMS_COLORS for axis in ("hue", "sat", "bri"))
WB_KEYS = tuple("g_fusion_picture__pq_wb_cor_" + part for part in ("enable", "gain", "red", "green", "blue"))
SYSTEM_NATIVE_KEYS = tuple(dict.fromkeys(
    [item[1] for item in SYSTEM_OPTIONS.values()] + ["g_video__vid_auto_color", "g_video__vid_nr", "g_video__vid_gamma_mode"] + list(CMS_KEYS) + list(WB_KEYS)))


def system_option_block_reason(option, mode, dovi):
    from .picture_modes import picture_signal_family
    if picture_signal_family(mode, dovi) is None:
        return "输入信号未确认"
    if option == "smooth_gradient" and (mode == 10 or mode in range(64, 69)):
        return "SDR 游戏模式下的平滑渐变写入不生效，仅显示当前状态"
    if option in ("black_correction", "contrast_enhancement", "local_contrast") and (
        mode in (14, 18) or mode in range(30, 35) or mode in range(69, 74)
    ):
        return "当前画面模式在系统菜单中禁用此调节"
    if option == "local_contrast" and mode in (4, 5, 6, 13, 59):
        return "当前杜比模式在系统菜单中隐藏局部对比度"
    return None


def system_option(option, value):
    if option not in SYSTEM_OPTIONS:
        raise ValueError("无效的系统画面选项")
    name, key, settings, choices = SYSTEM_OPTIONS[option]
    value = int(value)
    if value not in dict(choices):
        raise ValueError("无效的系统画面档位")
    native = {key: value}
    if option == "noise_reduction":
        native["g_video__vid_nr"] = value
    return name, native, settings
