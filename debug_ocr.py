"""
Debug: test OCR of the top buy price from the card marketplace page.

Usage: navigate to a card's marketplace page in the emulator, then run:
  python debug_price_ocr.py
"""

import pytesseract
import os
from PIL import Image, ImageGrab

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

BOX_TL = (-961, 870)
BOX_BR = (-559, 914)
box = (*BOX_TL, *BOX_BR)

print(f"OCR box: {box}")
print(f"Size: {BOX_BR[0]-BOX_TL[0]}x{BOX_BR[1]-BOX_TL[1]} px")
print()

img_raw = ImageGrab.grab(bbox=box, all_screens=True)
img_raw.save("debug_price_raw.png")
print(f"Saved: debug_price_raw.png ({img_raw.size[0]}x{img_raw.size[1]})")

w, h = img_raw.size

# Also save a wider version for context
wide_box = (BOX_TL[0] - 50, BOX_TL[1] - 30, BOX_BR[0] + 50, BOX_BR[1] + 30)
img_wide = ImageGrab.grab(bbox=wide_box, all_screens=True)
img_wide.save("debug_price_wide.png")
print(f"Saved: debug_price_wide.png")

# Try various approaches
for scale in (2, 3, 4):
    img_big = img_raw.resize((w * scale, h * scale), Image.NEAREST)
    
    # Grayscale
    img_gray = img_big.convert("L")
    
    # Normal B/W
    img_bw = img_gray.point(lambda p: 255 if p > 128 else 0, mode="1")
    
    # Inverted
    img_inv = img_gray.point(lambda p: 0 if p > 128 else 255, mode="1")

    img_bw.save(f"debug_price_{scale}x_bw.png")
    img_inv.save(f"debug_price_{scale}x_inv.png")

    print(f"\n=== {scale}x scale ===")
    configs = [
        ("psm7 digits+comma", "--psm 7 -c tessedit_char_whitelist=0123456789,"),
        ("psm7 default", "--psm 7"),
        ("psm6 default", "--psm 6"),
        ("psm8 digits", "--psm 8 -c tessedit_char_whitelist=0123456789,"),
    ]
    for label, config in configs:
        t_color = pytesseract.image_to_string(img_big, config=config).strip()
        t_bw = pytesseract.image_to_string(img_bw, config=config).strip()
        t_inv = pytesseract.image_to_string(img_inv, config=config).strip()
        print(f"  [{label}]")
        if t_color: print(f"    color: '{t_color}'")
        if t_bw:    print(f"    bw:    '{t_bw}'")
        if t_inv:   print(f"    inv:   '{t_inv}'")
        if not (t_color or t_bw or t_inv):
            print(f"    (all empty)")

print("\nCheck debug_price_wide.png to verify the box captures the price.")