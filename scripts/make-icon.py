"""Generate the simple code-native itx application icon."""
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
image = Image.new("RGBA", (256, 256), (20, 35, 42, 255))
d = ImageDraw.Draw(image)
d.rounded_rectangle((20, 20, 236, 236), radius=48, fill=(35, 67, 58))
d.line([(70, 153), (126, 88), (190, 150)], fill=(135, 191, 168), width=11)
for x, y in [(70, 153), (126, 88), (190, 150)]:
    d.ellipse((x-19, y-19, x+19, y+19), fill=(203, 231, 215))
target = root / "desktop/src-tauri/icons"
target.mkdir(parents=True, exist_ok=True)
image.save(target / "icon.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
