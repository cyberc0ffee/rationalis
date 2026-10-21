"""Genera rationalis/resources/rationalis.ico (16–256 px): una «R» bianca su quadrato blu arrotondato.

Uso: python tools_build/make_icon.py   (dalla cartella del progetto)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QImageWriter, QPainter, QPainterPath  # noqa: E402


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.2, size * 0.2)
    p.fillPath(path, QColor("#2a78d6"))
    f = QFont("Segoe UI")
    f.setBold(True)
    f.setPixelSize(int(size * 0.66))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), "R")
    p.end()
    return img


def main():
    QGuiApplication(sys.argv)
    out = Path(__file__).resolve().parent.parent / "rationalis" / "resources"
    out.mkdir(exist_ok=True)
    draw(256).save(str(out / "rationalis.png"))
    w = QImageWriter(str(out / "rationalis.ico"), b"ico")
    if not w.write(draw(256)):
        raise SystemExit(f"Scrittura ICO non riuscita: {w.errorString()}")
    print(out / "rationalis.ico")


if __name__ == "__main__":
    main()
