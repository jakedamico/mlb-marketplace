import subprocess
result = subprocess.run(
    ["adb", "-s", "127.0.0.1:7555", "exec-out", "screencap", "-p"],
    capture_output=True,
)
with open("screen.png", "wb") as f:
    f.write(result.stdout)
print(f"Saved {len(result.stdout)} bytes")