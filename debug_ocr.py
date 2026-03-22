"""
Debug: capture the sellable count OCR region, save raw + processed images,
and print what Tesseract reads.

Usage: navigate to the buy/sell order dialog in the emulator, then run:
  python debug_ocr.py
"""

import json
import os
import pytesseract
from PIL import Image, ImageGrab

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Load coords
COORDS_FILE = os.path.join(os.path.dirname(__file__), "emulator_coords.json")
with open(COORDS_FILE, "r") as f:
    coords = json.load(f)

tl = coords.get("SELLABLE_COUNT_TL", [-524, 765])
br = coords.get("SELLABLE_COUNT_BR", [-482, 806])
box = (*tl, *br)

print(f"OCR box: {box}")
print(f"Size: {br[0]-tl[0]}x{br[1]-tl[1]} px")
print()

# Grab raw screenshot of the region
img_raw = ImageGrab.grab(bbox=box, all_screens=True)
img_raw.save("debug_sellable_raw.png")
print(f"Saved: debug_sellable_raw.png ({img_raw.size[0]}x{img_raw.size[1]})")

# Scale up 4x
w, h = img_raw.size
img_4x = img_raw.resize((w * 4, h * 4), Image.NEAREST)
img_4x.save("debug_sellable_4x.png")
print(f"Saved: debug_sellable_4x.png ({img_4x.size[0]}x{img_4x.size[1]})")

# Grayscale
img_gray = img_4x.convert("L")
img_gray.save("debug_sellable_gray.png")
print(f"Saved: debug_sellable_gray.png")

# Threshold to B/W
img_bw = img_gray.point(lambda p: 255 if p > 128 else 0, mode="1")
img_bw.save("debug_sellable_bw.png")
print(f"Saved: debug_sellable_bw.png")

# Inverted threshold (in case digit is light on dark)
img_inv = img_gray.point(lambda p: 0 if p > 128 else 255, mode="1")
img_inv.save("debug_sellable_inv.png")
print(f"Saved: debug_sellable_inv.png")

# Also grab a much wider region for context
wide_box = (tl[0] - 100, tl[1] - 50, br[0] + 100, br[1] + 50)
img_wide = ImageGrab.grab(bbox=wide_box, all_screens=True)
img_wide.save("debug_sellable_wide.png")
print(f"Saved: debug_sellable_wide.png (wide context: {wide_box})")

# Try OCR with different configs
print()
print("=" * 50)
print("OCR Results:")
print("=" * 50)

configs = [
    ("psm10 digits", "--psm 10 -c tessedit_char_whitelist=0123456789"),
    ("psm7 digits", "--psm 7 -c tessedit_char_whitelist=0123456789"),
    ("psm8 digits", "--psm 8 -c tessedit_char_whitelist=0123456789"),
    ("psm13 raw", "--psm 13"),
    ("psm10 default", "--psm 10"),
    ("psm7 default", "--psm 7"),
]

for label, config in configs:
    # Try on B/W image
    text_bw = pytesseract.image_to_string(img_bw, config=config).strip()
    text_inv = pytesseract.image_to_string(img_inv, config=config).strip()
    text_4x = pytesseract.image_to_string(img_4x, config=config).strip()
    print(f"  [{label}]  bw='{text_bw}'  inv='{text_inv}'  color='{text_4x}'")

# Also try 6x and 8x scaling
for scale in (6, 8):
    img_big = img_raw.resize((w * scale, h * scale), Image.NEAREST)
    img_big_gray = img_big.convert("L")
    img_big_bw = img_big_gray.point(lambda p: 255 if p > 128 else 0, mode="1")
    img_big_inv = img_big_gray.point(lambda p: 0 if p > 128 else 255, mode="1")
    img_big_bw.save(f"debug_sellable_bw_{scale}x.png")

    text_bw = pytesseract.image_to_string(img_big_bw, config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
    text_inv = pytesseract.image_to_string(img_big_inv, config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
    print(f"  [{scale}x psm10]  bw='{text_bw}'  inv='{text_inv}'")

print()
print("Check the saved PNG files to see if the digit is actually in the box.")
print("If debug_sellable_wide.png shows the digit outside the box, adjust coords.")