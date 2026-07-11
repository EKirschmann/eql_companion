"""Minimal TGA writer matching EQ's UI texture format.

EQ UI textures are uncompressed true-color (type 2), bottom-left origin,
32bpp BGRA with 8 alpha bits (descriptor 0x08). We author conceptually
top-down (row 0 = top) and emit rows bottom-to-top so XML region coords,
which are top-left based, line up with what the engine samples.
"""
import struct


def write_tga(path, width, height, pixels_top_down):
    """pixels_top_down: list of rows (top->bottom); each row a list of (r,g,b,a)."""
    assert len(pixels_top_down) == height
    hdr = struct.pack(
        "<BBBHHBHHHHBB",
        0,      # id length
        0,      # color map type
        2,      # image type: uncompressed true-color
        0, 0, 0,  # color map spec (origin, length, depth)
        0, 0,   # x/y origin
        width, height,
        32,     # bits per pixel
        0x08,   # descriptor: 8 alpha bits, bottom-left origin
    )
    body = bytearray()
    for y in range(height - 1, -1, -1):  # bottom-to-top
        for (r, g, b, a) in pixels_top_down[y]:
            body += bytes((b, g, r, a))  # TGA stores BGRA
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(body)


def write_tga24(path, width, height, pixels_top_down):
    """24bpp opaque variant, matching EQ's wnd_bg_*_rock.tga panel format
    (type 2, bottom-left origin, descriptor 0x00, BGR). pixels: (r,g,b) rows."""
    assert len(pixels_top_down) == height
    hdr = struct.pack(
        "<BBBHHBHHHHBB",
        0, 0, 2, 0, 0, 0, 0, 0, width, height, 24, 0x00,
    )
    body = bytearray()
    for y in range(height - 1, -1, -1):  # bottom-to-top
        for (r, g, b) in pixels_top_down[y]:
            body += bytes((b, g, r))     # BGR
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(body)


def vgradient(width, height, top_rgb, bot_rgb):
    """Vertical gradient, top->bottom, as a top-down pixel buffer."""
    rows = []
    for y in range(height):
        t = y / (height - 1)
        px = tuple(round(a + (b - a) * t) for a, b in zip(top_rgb, bot_rgb))
        rows.append([px for _ in range(width)])
    return rows


def solid(width, height, rgba):
    return [[tuple(rgba) for _ in range(width)] for _ in range(height)]


def fill_rect(px, x, y, w, h, rgba):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            px[yy][xx] = tuple(rgba)
