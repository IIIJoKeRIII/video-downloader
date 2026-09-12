"""Рисует assets/app.ico. Запускать вручную после правки формы:

    python assets/make_icon.py

Нужен Pillow (в requirements.txt его нет намеренно: библиотека нужна
только здесь, в самом приложении она не используется).
"""
import os

from PIL import Image, ImageDraw

BG = "#3DDC84"
FG = "#0F1B14"


def rounded_cap(draw, point, width):
    """У Pillow нет round cap для линий — дорисовываем круг на конце."""
    x, y = point
    r = width / 2
    draw.ellipse([x - r, y - r, x + r, y + r], fill=FG)


def draw_arrow(draw):
    stem_width = 112
    check_width = 112
    shelf_width = 96

    draw.line([(512, 240), (512, 592)], fill=FG, width=stem_width)
    rounded_cap(draw, (512, 240), stem_width)
    rounded_cap(draw, (512, 592), stem_width)

    draw.line([(336, 480), (512, 656), (688, 480)], fill=FG, width=check_width, joint="curve")
    rounded_cap(draw, (336, 480), check_width)
    rounded_cap(draw, (512, 656), check_width)
    rounded_cap(draw, (688, 480), check_width)

    draw.line([(288, 784), (736, 784)], fill=FG, width=shelf_width)
    rounded_cap(draw, (288, 784), shelf_width)
    rounded_cap(draw, (736, 784), shelf_width)


def main():
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=224, fill=BG)
    draw_arrow(draw)

    img = img.resize((256, 256), Image.LANCZOS)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    img.save(out_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Готово: {out_path}")


if __name__ == "__main__":
    main()
