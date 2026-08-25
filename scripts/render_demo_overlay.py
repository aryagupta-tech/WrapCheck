from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


def font(size: int):
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def main() -> None:
    output = Path(sys.argv[1])
    clip = int(sys.argv[2])
    take = int(sys.argv[3])
    image = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1280, 52), fill=(5, 7, 10, 172))
    draw.text((24, 14), f"A017 C00{clip}  |  SC 24B  TAKE {take:02d}  |  24 FPS", font=font(20), fill=(246, 246, 244, 255))
    warning = "SOURCE CARD - DO NOT ERASE"
    warning_font = font(18)
    right = draw.textbbox((0, 0), warning, font=warning_font)[2]
    draw.text((1256 - right, 15), warning, font=warning_font, fill=(255, 156, 90, 255))
    draw.rectangle((22, 658, 318, 700), fill=(5, 7, 10, 142))
    draw.text((36, 669), f"SOURCE TC  01:24:{10 + clip:02d}:00", font=font(17), fill=(235, 235, 230, 235))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


if __name__ == "__main__":
    main()
