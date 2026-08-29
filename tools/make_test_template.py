"""Scaffolding: generates two 1200x675 stand-in templates for local preview,
so tools/preview.py is runnable before real per-user templates exist.

DELETE THIS FILE once real templates are added under templates/.
"""
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 1200, 675
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _make(path: Path, photo_cx: int) -> None:
    # Light background: real templates bake in a readable zone for the
    # fixed dark #text color in overlay.html, so the stand-in should too.
    img = Image.new("RGB", (W, H), "#eef1f5")
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [photo_cx - 150, H // 2 - 150, photo_cx + 150, H // 2 + 150],
        fill="#c7cdd6",
        outline="#5eaee0",
        width=4,
    )
    img.save(path)


def main() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    left = TEMPLATES_DIR / "testleft.png"
    right = TEMPLATES_DIR / "testright.png"
    _make(left, photo_cx=220)   # photo on the LEFT, empty zone on the right
    _make(right, photo_cx=980)  # photo on the RIGHT, empty zone on the left
    print(f"wrote {left}")
    print(f"wrote {right}")


if __name__ == "__main__":
    main()
