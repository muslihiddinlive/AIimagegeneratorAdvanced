"""
AI rasm generatorlar (Stable Diffusion asosidagilar, shu jumladan Stable
Horde va Pollinations) matnni deyarli hech qachon to'g'ri chizolmaydi -
harflar buzilib, tushunarsiz "abrakadabra" bo'lib chiqadi. Buning yechimi:
rasmni AI chizadi (fonda hech qanday matnsiz), aniq matn esa shu modul
orqali DASTURIY ravishda, haqiqiy shrift bilan ustiga qo'yiladi - natijada
matn har doim 100% to'g'ri va o'qilishi mumkin bo'ladi.
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "fonts", "Poppins-Bold.ttf")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def add_text_overlay(image_bytes: bytes, text: str) -> bytes:
    """Berilgan rasm baytiga aniq matnni markazga (biroz pastroqqa) chiroyli
    shrift, oq rang + qora kontur bilan chizadi - har qanday fonda o'qilishi
    uchun. Xato bo'lsa, asl rasmni o'zgarishsiz qaytaradi (bot to'xtamasin)."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)

        width, height = img.size
        max_text_width = int(width * 0.85)
        font_size = max(24, width // 14)
        font = _load_font(font_size)

        lines = _wrap_text(draw, text, font, max_text_width)
        # Matn juda uzun bo'lsa, sig'guncha shrift o'lchamini kichraytiramiz
        while len(lines) > 3 and font_size > 18:
            font_size -= 4
            font = _load_font(font_size)
            lines = _wrap_text(draw, text, font, max_text_width)

        line_heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_heights.append(bbox[3] - bbox[1])
        line_spacing = int(font_size * 0.35)
        total_height = sum(line_heights) + line_spacing * (len(lines) - 1)

        y = (height - total_height) // 2 + int(height * 0.12)  # markazdan biroz pastroq (banner uslubi)
        outline_width = max(2, font_size // 14)

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2

            # Qora kontur (har qanday fon rangida o'qilishi uchun) + oq matn
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx * dx + dy * dy <= outline_width * outline_width:
                        draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

            y += line_heights[i] + line_spacing

        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception:
        return image_bytes
