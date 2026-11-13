import math
import os
from PIL import Image, ImageDraw, ImageFont

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
web_dir = os.path.join(root, 'web')
icons_dir = os.path.join(web_dir, 'icons')
os.makedirs(icons_dir, exist_ok=True)

size = 512
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
mask = Image.new('L', (size, size), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=84, fill=255)

grad = Image.new('RGBA', (size, size), (0, 0, 0, 0))
for y in range(size):
    t = y / (size - 1)
    r = int(32 + (76 - 32) * t)
    g = int(125 + (196 - 125) * t)
    b = int(220 + (230 - 220) * t)
    for x in range(size):
        grad.putpixel((x, y), (r, g, b, 255))

shadow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
shadow_draw = ImageDraw.Draw(shadow)
shadow_draw.rounded_rectangle((18, 22, size - 18, size - 18), radius=76, fill=(15, 77, 160, 90))
img = Image.alpha_composite(img, shadow)
img = Image.composite(grad, Image.new('RGBA', grad.size, (0, 0, 0, 0)), mask)

highlight = Image.new('RGBA', (size, size), (255, 255, 255, 0))
hdraw = ImageDraw.Draw(highlight)
hdraw.rounded_rectangle((28, 26, size - 28, size - 26), radius=70, fill=(255, 255, 255, 50))
img = Image.alpha_composite(img, highlight)

try:
    font_big = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 210)
except Exception:
    font_big = ImageFont.truetype('DejaVuSans-Bold.ttf', 210)
text = 'FD'
text_bbox = font_big.getbbox(text)
text_w = text_bbox[2] - text_bbox[0]
text_h = text_bbox[3] - text_bbox[1]
text_x = (size - text_w) / 2
text_y = (size - text_h) / 2 - 18
text_img = Image.new('RGBA', img.size, (0, 0, 0, 0))
text_draw = ImageDraw.Draw(text_img)
text_draw.text((text_x, text_y), text, font=font_big, fill=(255, 255, 255, 255))
img = Image.alpha_composite(img, text_img)

badge_radius = 110
badge_center = (size - 120, size - 120)
badge = Image.new('RGBA', (size, size), (0, 0, 0, 0))
badge_draw = ImageDraw.Draw(badge)
badge_draw.ellipse(
    (badge_center[0] - badge_radius, badge_center[1] - badge_radius,
     badge_center[0] + badge_radius, badge_center[1] + badge_radius),
    fill=(104, 224, 216, 255),
)
badge_draw.ellipse(
    (badge_center[0] - badge_radius + 12, badge_center[1] - badge_radius + 12,
     badge_center[0] + badge_radius - 12, badge_center[1] + badge_radius - 12),
    outline=(18, 170, 175, 255), width=10,
)
for i in range(16):
    a = (i * 22 + 15) % 360
    r = 82 + (i % 4) * 12
    x = int(badge_center[0] + r * math.cos(math.radians(a)))
    y = int(badge_center[1] + r * math.sin(math.radians(a)))
    badge_draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(255, 255, 255, 110))
img = Image.alpha_composite(img, badge)

try:
    font_small = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 96)
except Exception:
    font_small = ImageFont.truetype('DejaVuSans-Bold.ttf', 96)
text2 = 'IA'
text2_bbox = font_small.getbbox(text2)
text2_w = text2_bbox[2] - text2_bbox[0]
text2_h = text2_bbox[3] - text2_bbox[1]
text2_x = badge_center[0] - text2_w / 2
text2_y = badge_center[1] - text2_h / 2 + 8
badge_text = Image.new('RGBA', img.size, (0, 0, 0, 0))
text_draw2 = ImageDraw.Draw(badge_text)
text_draw2.text((text2_x, text2_y), text2, font=font_small, fill=(255, 255, 255, 255))
img = Image.alpha_composite(img, badge_text)

favicon_path = os.path.join(web_dir, 'favicon.png')
img.save(favicon_path)

for w in (192, 512):
    resized = img.resize((w, w), Image.Resampling.LANCZOS)
    resized.save(os.path.join(icons_dir, f'Icon-{w}.png'))
    resized.save(os.path.join(icons_dir, f'Icon-maskable-{w}.png'))

print(f'Generated {favicon_path} and {icons_dir}')
