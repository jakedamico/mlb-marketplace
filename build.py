"""
Build script for MLB Bot exe.

Run: python build.py

Prerequisites:
  pip install pyinstaller customtkinter pillow pytesseract

This will create dist/MLB-Bot.exe
"""

import subprocess
import sys
import os

def main():
    # Check prerequisites
    try:
        import customtkinter
        ctk_path = os.path.dirname(customtkinter.__file__)
        print(f"  customtkinter found at: {ctk_path}")
    except ImportError:
        print("ERROR: pip install customtkinter")
        return

    try:
        import pytesseract
        print(f"  pytesseract found")
    except ImportError:
        print("ERROR: pip install pytesseract")
        return

    # Files to include
    project_modules = [
        "automation",
        "main",
        "api",
        "adb_screen",
    ]

    # Optional config files (included if they exist)
    optional_files = [
        "emulator_coords.json",
        "cookies.json",
    ]

    # Build the arguments
    add_data = []
    hidden_imports = []

    for mod in project_modules:
        hidden_imports.append(f"--hidden-import={mod}")

    for f in optional_files:
        if os.path.exists(f):
            add_data.append(f"--add-data={f}{os.pathsep}.")
            print(f"  Including config: {f}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "MLB-Bot",
        "--collect-all", "customtkinter",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "pytesseract",
        "--hidden-import", "requests",
        *hidden_imports,
        *add_data,
        "gui.py",
    ]

    print(f"\n  Running PyInstaller...")
    print(f"  {' '.join(cmd)}\n")
    subprocess.run(cmd)

    print(f"\n{'='*55}")
    print(f"  Build complete!")
    print(f"  Output: dist/MLB-Bot.exe")
    print(f"")
    print(f"  IMPORTANT — you still need these on the target machine:")
    print(f"    1. ADB (adb.exe) on PATH or in the same folder")
    print(f"    2. Tesseract OCR installed at:")
    print(f"       C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
    print(f"    3. emulator_coords.json in the same folder as the exe")
    print(f"    4. cookies.json in the same folder (for API auth)")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()