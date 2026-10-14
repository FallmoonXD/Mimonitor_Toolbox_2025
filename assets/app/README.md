# Application icons

`logo.svg` uses the MI geometry from [Xiaomi's website](https://www.mi.com/global/), with the background changed to toolbox purple `#734EFF` and the glyph kept white.

`tray.svg` uses the same white glyph on a transparent background. The standalone tray glyph has extra scale for small system tray sizes.

Run `python tools/generate_icons.py` with PyQt6 installed to render the Windows application and tray ICO files and the macOS application ICNS file.
