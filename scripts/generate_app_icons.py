from __future__ import annotations

from pathlib import Path
import struct
import subprocess
import sys
import zlib


ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets" / "icons"
ICONSET_DIR = ASSETS_DIR / "shucheng.iconset"
ICO_PATH = ASSETS_DIR / "shucheng.ico"
ICNS_PATH = ASSETS_DIR / "shucheng.icns"
PNG_PATH = ASSETS_DIR / "shucheng.png"
FAVICON_PATH = ROOT / "app" / "static" / "favicon.ico"


def clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def lerp_color(start: tuple[int, int, int], end: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(clamp_channel(start[idx] + (end[idx] - start[idx]) * ratio) for idx in range(3))


class Canvas:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.buffer = bytearray(width * height * 4)

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        index = (y * self.width + x) * 4
        r, g, b, a = color
        if a >= 255:
            self.buffer[index:index + 4] = bytes((r, g, b, 255))
            return
        if a <= 0:
            return

        base_r = self.buffer[index]
        base_g = self.buffer[index + 1]
        base_b = self.buffer[index + 2]
        base_a = self.buffer[index + 3]
        alpha = a / 255.0
        inv_alpha = 1.0 - alpha
        out_a = alpha + (base_a / 255.0) * inv_alpha
        if out_a <= 0:
            self.buffer[index:index + 4] = b"\x00\x00\x00\x00"
            return

        out_r = (r * alpha + base_r * (base_a / 255.0) * inv_alpha) / out_a
        out_g = (g * alpha + base_g * (base_a / 255.0) * inv_alpha) / out_a
        out_b = (b * alpha + base_b * (base_a / 255.0) * inv_alpha) / out_a
        self.buffer[index:index + 4] = bytes((
            clamp_channel(out_r),
            clamp_channel(out_g),
            clamp_channel(out_b),
            clamp_channel(out_a * 255),
        ))

    def fill(self, color: tuple[int, int, int, int]) -> None:
        for y in range(self.height):
            for x in range(self.width):
                self.set_pixel(x, y, color)

    def fill_gradient(self, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
        for y in range(self.height):
            ratio = y / max(1, self.height - 1)
            row_color = lerp_color(top, bottom, ratio)
            for x in range(self.width):
                drift = (x / max(1, self.width - 1)) * 0.08
                tint = lerp_color(row_color, (64, 97, 203), drift)
                self.set_pixel(x, y, (tint[0], tint[1], tint[2], 255))

    def rounded_rect(self, left: int, top: int, right: int, bottom: int, radius: int, color: tuple[int, int, int, int]) -> None:
        for y in range(top, bottom):
            for x in range(left, right):
                dx = 0
                dy = 0
                if x < left + radius:
                    dx = left + radius - x
                elif x >= right - radius:
                    dx = x - (right - radius - 1)
                if y < top + radius:
                    dy = top + radius - y
                elif y >= bottom - radius:
                    dy = y - (bottom - radius - 1)
                if dx * dx + dy * dy <= radius * radius:
                    self.set_pixel(x, y, color)

    def circle(self, cx: int, cy: int, radius: int, color: tuple[int, int, int, int]) -> None:
        radius_sq = radius * radius
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                dx = x - cx
                dy = y - cy
                if dx * dx + dy * dy <= radius_sq:
                    self.set_pixel(x, y, color)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)
    return payload


def write_ico(path: Path, png_blobs: list[tuple[int, bytes]]) -> None:
    count = len(png_blobs)
    header = struct.pack("<HHH", 0, 1, count)
    entries = bytearray()
    offset = 6 + 16 * count
    body = bytearray()

    for size, png_bytes in png_blobs:
        width = 0 if size >= 256 else size
        height = 0 if size >= 256 else size
        entries.extend(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(png_bytes), offset))
        body.extend(png_bytes)
        offset += len(png_bytes)

    path.write_bytes(header + entries + body)


def render_icon(size: int) -> bytes:
    canvas = Canvas(size, size)
    canvas.fill_gradient((35, 45, 132), (26, 35, 105))

    canvas.circle(int(size * 0.82), int(size * 0.20), int(size * 0.17), (255, 125, 72, 255))
    canvas.circle(int(size * 0.22), int(size * 0.84), int(size * 0.12), (255, 125, 72, 90))

    card_left = int(size * 0.20)
    card_top = int(size * 0.18)
    card_right = int(size * 0.80)
    card_bottom = int(size * 0.82)
    radius = max(8, size // 10)
    canvas.rounded_rect(card_left, card_top, card_right, card_bottom, radius, (250, 251, 255, 255))

    canvas.rounded_rect(card_left, card_top, card_right, int(size * 0.34), radius // 2, (255, 125, 72, 255))
    canvas.rounded_rect(int(size * 0.28), int(size * 0.43), int(size * 0.72), int(size * 0.48), max(4, size // 40), (36, 47, 137, 255))
    canvas.rounded_rect(int(size * 0.28), int(size * 0.56), int(size * 0.62), int(size * 0.61), max(4, size // 40), (36, 47, 137, 180))
    canvas.rounded_rect(int(size * 0.28), int(size * 0.66), int(size * 0.66), int(size * 0.71), max(4, size // 40), (36, 47, 137, 180))
    canvas.rounded_rect(int(size * 0.64), int(size * 0.54), int(size * 0.73), int(size * 0.73), max(4, size // 30), (255, 125, 72, 255))

    notch_radius = max(4, size // 18)
    for direction in (-1, 1):
        canvas.circle(int(size * (0.20 if direction == -1 else 0.80)), int(size * 0.50), notch_radius, (35, 45, 132, 255))

    return bytes(canvas.buffer)


def build_iconset() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    FAVICON_PATH.parent.mkdir(parents=True, exist_ok=True)

    size_map = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    rendered_pngs: dict[int, bytes] = {}
    for size in sorted(set(size_map.values())):
        rgba = render_icon(size)
        target = PNG_PATH if size == 1024 else ASSETS_DIR / f"icon-{size}.png"
        rendered_pngs[size] = write_png(target, size, size, rgba)

    for filename, size in size_map.items():
        (ICONSET_DIR / filename).write_bytes(rendered_pngs[size])

    write_ico(ICO_PATH, [(size, rendered_pngs[size]) for size in [16, 32, 64, 128, 256]])
    FAVICON_PATH.write_bytes(ICO_PATH.read_bytes())

    if sys.platform == "darwin":
        try:
            subprocess.run(["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)], check=True)
        except Exception as exc:
            print(f"warning: failed to build icns: {exc}")


if __name__ == "__main__":
    build_iconset()
    print(f"icons ready in: {ASSETS_DIR}")