"""Render the editable MI SVG assets to application and tray icon formats."""
from pathlib import Path
import os
import struct
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/app"
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def render_svg(path, size):
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG: {path}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("PNG encoding failed")
    return bytes(buffer.data())


def write_ico(svg, target):
    images = [png_bytes(render_svg(svg, size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    directory = bytearray()
    offset = len(header) + 16 * len(SIZES)
    for size, blob in zip(SIZES, images):
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset))
        offset += len(blob)
    target.write_bytes(header + directory + b"".join(images))


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    write_ico(ASSETS / "logo.svg", ASSETS / "icon.ico")
    write_ico(ASSETS / "tray.svg", ASSETS / "tray.ico")
    chunks = []
    for tag, size in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
        blob = png_bytes(render_svg(ASSETS / "logo.svg", size))
        chunks.append(tag + struct.pack(">I", len(blob) + 8) + blob)
    data = b"".join(chunks)
    (ROOT / "macos/assets/AppIcon.icns").write_bytes(b"icns" + struct.pack(">I", len(data) + 8) + data)
    print("Rendered purple application logo and white transparent tray icon at 10 sizes.")
    return app


if __name__ == "__main__":
    main()
