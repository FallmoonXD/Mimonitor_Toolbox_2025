"""2025 OS3.0.109 场景：MTK 原生编号，与小米 SceneMode 编号分开。"""

# 来自实机固件的 PictureSettingsManager 常量与 converSceneModeToXiaomi。
# 小米 Dolby 明亮/暗场/自定义/IQ/游戏为 11/12/13/18/19，
# 对应的 MTK 编号为 59/6/61/5/13，不能直接把小米编号写入 native。
NATIVE_MODE_NAMES = {
    0: "自定义", 2: "运动", 3: "图片", 9: "电影", 10: "游戏", 14: "标准",
    4: "Dolby Vision Filmmaker", 5: "Dolby Vision IQ", 6: "Dolby Vision 暗场",
    13: "Dolby Vision 游戏", 59: "Dolby Vision 明亮", 61: "Dolby Vision 自定义",
    15: "HDR", 16: "HDR 游戏", 17: "HDR 电影", 18: "HDR 显示器",
    19: "HDR 图片", 35: "HDR10+", 55: "HLG", 76: "HDR Filmmaker",
    22: "IMAX", 75: "Filmmaker",
}
NATIVE_MODE_GROUPS = {
    14: {14, 69, 70, 71, 72, 73},
    10: {10, 64, 65, 66, 67, 68},
    9: {9},
    16: {16, 25, 26, 27, 28, 29},
    18: {18, 30, 31, 32, 33, 34},
}
for _primary, _members in NATIVE_MODE_GROUPS.items():
    for _member in _members:
        NATIVE_MODE_NAMES.setdefault(_member, NATIVE_MODE_NAMES[_primary] + "预设")

DOLBY_NATIVE_MODES = frozenset({4, 5, 6, 13, 59, 61})
HDR_NATIVE_MODES = frozenset({15, 16, 17, 18, 19, 35, 55, 76}) | frozenset(range(25, 35))
SDR_NATIVE_MODES = frozenset({0, 2, 3, 9, 10, 14, 22, 75}) | frozenset(range(64, 74))
NATIVE_MODE_CHOICES = {
    "SDR": ((14, "标准"), (10, "游戏"), (9, "电影"), (0, "自定义")),
    "HDR": ((15, "标准"), (16, "游戏"), (17, "电影"), (18, "显示器"),
            (19, "图片"), (76, "Filmmaker")),
    "Dolby Vision": ((5, "IQ"), (59, "明亮"), (6, "暗场"), (13, "游戏"), (61, "自定义")),
}


def native_mode_group(mode):
    try:
        mode = int(mode)
    except (TypeError, ValueError):
        return None
    return next((primary for primary, members in NATIVE_MODE_GROUPS.items() if mode in members), mode)


def picture_signal_family(mode, dovi=None):
    """仅依据设备信号/模式分类；矛盾状态留为未知，不借用 Windows HDR bool。"""
    try:
        mode = int(mode)
    except (TypeError, ValueError):
        return None
    if dovi is not None:
        try:
            dovi = int(dovi)
        except (TypeError, ValueError):
            return None
        if dovi not in (0, 1) or (dovi == 1) != (mode in DOLBY_NATIVE_MODES):
            return None
    if mode in DOLBY_NATIVE_MODES:
        return "Dolby Vision"
    if mode in HDR_NATIVE_MODES:
        return "HDR"
    if mode in SDR_NATIVE_MODES:
        return "SDR"
    return None


def picture_mode_choices(mode, dovi=None):
    return NATIVE_MODE_CHOICES.get(picture_signal_family(mode, dovi), ())


def validate_mode_target(target, current, dovi):
    family = picture_signal_family(current, dovi)
    try:
        target = int(target)
    except (TypeError, ValueError):
        raise ValueError("没有可用的原生画面模式") from None
    if family is None or picture_signal_family(target, dovi) != family:
        raise ValueError("输入信号已变化或目标模式不属于当前信号；请刷新后重试")
    if target not in NATIVE_MODE_NAMES:
        raise ValueError(f"未确认的原生画面模式 {target}")
    return target
