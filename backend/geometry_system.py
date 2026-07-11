"""Client-mined zone geometry for the Atlas (eqltools-style "true walls").

Parses the game's own .s3d zone archives (PFS containers) and the WLD mesh
fragments inside (0x36 DmSpriteDef2), classifies triangles into walls and
floors by face normal, derives floor bands from the z-histogram of upward
faces, and emits a compact 2D JSON payload the Atlas canvas renders.

Results are cached to data/geometry/<short>.json and rebuilt when the .s3d
changes. Coordinates: WLD axes are swapped relative to /loc — wld_x is the
/loc Y (northing) and wld_y is the /loc X — so to match the vector charts'
plot convention (-locX, -locY) a WLD vertex plots at (-wld_y, -wld_x),
screen-y down. Verified against live /loc samples and the Brewall Befallen
chart (bbox agreement within 4 units). Everything reads the user's own
install; nothing is downloaded.

Not yet extracted (future 3D pass): placeable props (objects.wld transforms
into <zone>_obj.s3d) and ceilings (downward faces mostly obscure dungeons).
"""
import json
import logging
import re
import struct
import zlib
from collections import Counter
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.map_system import ZONE_FILES, _canonical, normalize_zone

logger = logging.getLogger(__name__)

GEOMETRY_DIR = Path("data") / "geometry"
NAME_DIR_CRC = 0x61580AC9
WALL_NZ = 0.7          # |unit normal z| below this = wall, above = floor/ceiling
FLOOR_BAND_GAP = 15.0  # min z separation between detected floors
FLOOR_SPAN_MIN = 25.0  # z span under this = single-floor zone
MAX_BANDS = 8


# ---------------------------------------------------------------- S3D / WLD

def _read_pfs(path: Path) -> dict:
    """PFS archive -> {lowercase filename: inflated bytes}."""
    data = path.read_bytes()
    dir_off, magic = struct.unpack_from("<I4s", data, 0)
    if magic != b"PFS ":
        raise ValueError(f"{path.name}: not a PFS archive")
    count = struct.unpack_from("<I", data, dir_off)[0]
    entries = []
    for i in range(count):
        crc, off, size = struct.unpack_from("<III", data, dir_off + 4 + i * 12)
        entries.append((crc, off, size))

    def inflate(off: int, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            dlen, _ilen = struct.unpack_from("<II", data, off)
            off += 8
            out += zlib.decompress(data[off:off + dlen])
            off += dlen
        return bytes(out)

    names_entry = next(e for e in entries if e[0] == NAME_DIR_CRC)
    nd = inflate(names_entry[1], names_entry[2])
    n = struct.unpack_from("<I", nd, 0)[0]
    names, p = [], 4
    for _ in range(n):
        ln = struct.unpack_from("<I", nd, p)[0]
        p += 4
        names.append(nd[p:p + ln - 1].decode("ascii", "replace"))
        p += ln
    files = {}
    data_entries = sorted((e for e in entries if e[0] != NAME_DIR_CRC),
                          key=lambda e: e[1])
    for (crc, off, size), name in zip(data_entries, names):
        files[name.lower()] = inflate(off, size)
    return files


def _iter_meshes(wld: bytes):
    """Yield (vertices, triangles) from every 0x36 fragment (world coords)."""
    magic, _version, fragcount = struct.unpack_from("<III", wld, 0)
    if magic != 0x54503D02:
        raise ValueError("not a WLD file")
    hashlen = struct.unpack_from("<I", wld, 20)[0]
    p = 28 + hashlen
    for _ in range(fragcount):
        fsize, ftype = struct.unpack_from("<II", wld, p)
        if ftype == 0x36:
            b = p + 8 + 4          # header + nameRef
            b += 4 + 4 * 4         # flags + 4 fragment refs
            cx, cy, cz = struct.unpack_from("<fff", wld, b)
            b += 12
            b += 12                # params2
            b += 4 + 12 + 12       # maxDist + min + max
            (vcount, uvcount, ncount, ccount, pcount,
             _vp, _pt, _vt, _s9, scale) = struct.unpack_from("<10H", wld, b)
            b += 20
            s = 1.0 / (1 << scale)
            verts = []
            for i in range(vcount):
                x, y, z = struct.unpack_from("<3h", wld, b + i * 6)
                verts.append((cx + x * s, cy + y * s, cz + z * s))
            b += vcount * 6
            b += uvcount * 4       # old-format texcoords (int16 pairs)
            b += ncount * 3        # normals (int8 triples)
            b += ccount * 4       # vertex colors
            tris = []
            for i in range(pcount):
                _flags, v1, v2, v3 = struct.unpack_from("<4H", wld, b + i * 8)
                if v1 < vcount and v2 < vcount and v3 < vcount:
                    tris.append((v1, v2, v3))
            yield verts, tris
        p += 8 + fsize


# ------------------------------------------------------------ classification

def _floor_bands(zs: list) -> list:
    """Detect distinct floor levels from upward-face centroid z values."""
    if not zs:
        return []
    lo, hi = min(zs), max(zs)
    if hi - lo < FLOOR_SPAN_MIN:
        return [round((lo + hi) / 2, 1)]
    bins = Counter(round(z / 5.0) for z in zs)
    total = sum(bins.values())
    peaks: list = []
    for b, cnt in sorted(bins.items(), key=lambda kv: -kv[1]):
        if cnt < total * 0.02:
            break
        z = b * 5.0
        if all(abs(z - pz) >= FLOOR_BAND_GAP for pz in peaks):
            peaks.append(z)
        if len(peaks) >= MAX_BANDS:
            break
    return sorted(round(pz, 1) for pz in peaks) or [round((lo + hi) / 2, 1)]


def _band_index(bands: list, z: float) -> int:
    return min(range(len(bands)), key=lambda i: abs(bands[i] - z))


def build_geometry(s3d_path: Path, short: str) -> dict:
    """Extract, classify, and band the zone's 2D geometry payload."""
    files = _read_pfs(s3d_path)
    wld = files.get(f"{short}.wld")
    if wld is None:
        wld_names = [n for n in files if n.endswith(".wld")
                     and n not in ("lights.wld", "objects.wld")]
        if not wld_names:
            raise ValueError("no zone wld inside archive")
        wld = files[wld_names[0]]

    floor_tris, wall_tris = [], []
    for verts, tris in _iter_meshes(wld):
        for v1, v2, v3 in tris:
            ax, ay, az = verts[v1]
            bx, by, bz = verts[v2]
            cx, cy, cz = verts[v3]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            length = (nx * nx + ny * ny + nz * nz) ** 0.5
            if length < 1e-6:
                continue
            zc = (az + bz + cz) / 3.0
            tri = ((ax, ay), (bx, by), (cx, cy), zc)
            if abs(nz / length) >= WALL_NZ:
                if nz < 0:  # CW winding: geometric-down = walkable floor
                    floor_tris.append(tri)
            else:
                wall_tris.append(tri)

    bands = _floor_bands([t[3] for t in floor_tris])
    floors = [{"z": bz, "walls": set(), "tris": []} for bz in bands]

    for (a, b, c, zc) in floor_tris:
        idx = _band_index(bands, zc)
        floors[idx]["tris"].append([
            round(-a[1]), round(-a[0]), round(-b[1]),
            round(-b[0]), round(-c[1]), round(-c[0])])

    for (a, b, c, zc) in wall_tris:
        idx = _band_index(bands, zc)
        pa = (round(-a[1]), round(-a[0]))
        pb = (round(-b[1]), round(-b[0]))
        pc = (round(-c[1]), round(-c[0]))
        for p1, p2 in ((pa, pb), (pb, pc), (pc, pa)):
            if p1 != p2:
                floors[idx]["walls"].add((p1, p2) if p1 <= p2 else (p2, p1))

    xs, ys = [], []
    out_floors = []
    for f in floors:
        walls = [[p1[0], p1[1], p2[0], p2[1]] for p1, p2 in f["walls"]]
        for p1, p2 in f["walls"]:
            xs.extend((p1[0], p2[0]))
            ys.extend((p1[1], p2[1]))
        out_floors.append({"z": f["z"], "walls": walls, "tris": f["tris"]})

    return {
        "available": True,
        "zone": short,
        "bounds": {"min_x": min(xs), "min_y": min(ys),
                   "max_x": max(xs), "max_y": max(ys)} if xs else None,
        "floors": out_floors,
        "wall_count": sum(len(f["walls"]) for f in out_floors),
        "tri_count": sum(len(f["tris"]) for f in out_floors),
    }


# ------------------------------------------------------------------- lookup

def _short_candidates(zone_name: str) -> list:
    key = _canonical(zone_name)
    cands = list(ZONE_FILES.get(key or "", []))
    squashed = re.sub(r"[^a-z0-9]", "", normalize_zone(zone_name).lower())
    if squashed and squashed not in cands:
        cands.append(squashed)
    return cands


def geometry_for_zone(zone_name: str) -> Optional[dict]:
    """Cached geometry payload for a zone, or None when no .s3d exists."""
    game_dir = Path(settings.eql_game_dir)
    for short in _short_candidates(zone_name):
        s3d = game_dir / f"{short}.s3d"
        if not s3d.exists():
            continue
        GEOMETRY_DIR.mkdir(parents=True, exist_ok=True)
        cache = GEOMETRY_DIR / f"{short}.v2.json"
        try:
            if cache.exists() and cache.stat().st_mtime >= s3d.stat().st_mtime:
                return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            payload = build_geometry(s3d, short)
        except Exception:
            logger.exception("Geometry extraction failed for %s", s3d.name)
            return None
        try:
            cache.write_text(json.dumps(payload, separators=(",", ":")),
                             encoding="utf-8")
        except OSError:
            logger.warning("Could not cache geometry for %s", short)
        return payload
    return None


# ------------------------------------------------------------------- 3D view

XOR_KEY = (0x95, 0x3A, 0xC5, 0x2A, 0x95, 0x7A, 0x95, 0x6A)
GEOMETRY3D_DIR = Path("data") / "geometry3d"
TEXTURE_DIR = Path("data") / "textures"
FLAT_NZ = 0.95          # unit-normal z above this = flat floor
RAMP_NZ = 0.34          # RAMP_NZ..FLAT_NZ (upward) = ramp/stair
MASKED_METHODS = {0x13, 0x14, 0x17}  # color-key transparency (leaves, grates)
MAX_PROP_TRIS = 150_000


def _wld_fragments(wld: bytes):
    """All fragments with a resolver for string-hash names."""
    magic, _v, fragcount = struct.unpack_from("<III", wld, 0)
    if magic != 0x54503D02:
        raise ValueError("not a WLD file")
    hashlen = struct.unpack_from("<I", wld, 20)[0]
    raw = wld[28:28 + hashlen]
    strings = bytes(b ^ XOR_KEY[i % 8] for i, b in enumerate(raw))

    def name_at(ref: int):
        if ref >= 0:
            return None
        i = -ref
        end = strings.find(b"\x00", i)
        return strings[i:end].decode("ascii", "replace") if end > i else None

    frags = []
    p = 28 + hashlen
    for _ in range(fragcount):
        fsize, ftype = struct.unpack_from("<II", wld, p)
        frags.append((ftype, p + 8, fsize))
        p += 8 + fsize
    return frags, name_at


def _bitmap_names(wld: bytes, body: int) -> list:
    """0x03: i32 nameRef, u32 count-1, then (u16 len, XOR-encoded name)*."""
    count = struct.unpack_from("<I", wld, body + 4)[0] + 1
    names, p = [], body + 8
    for _ in range(count):
        ln = struct.unpack_from("<H", wld, p)[0]
        p += 2
        dec = bytes(b ^ XOR_KEY[i % 8] for i, b in enumerate(wld[p:p + ln]))
        names.append(dec.rstrip(b"\x00").decode("ascii", "replace").lower())
        p += ln
    return names


def _material_tables(wld: bytes, frags: list) -> dict:
    """0x31 fragment index -> [(texture|None, render_method), ...].
    render_method 0 = invisible boundary material (its polygons are skipped:
    zone shells that would otherwise read as a phantom ceiling)."""
    by_index = {i + 1: f for i, f in enumerate(frags)}

    def mat_info(midx):
        _t, body, _s = by_index[midx]
        params1 = struct.unpack_from("<I", wld, body + 8)[0]
        rm = params1 & 0xFF
        if rm == 0:
            return (None, 0)
        ref05 = struct.unpack_from("<i", wld, body + 24)[0]
        tex = None
        if 0 < ref05 <= len(frags) and by_index[ref05][0] == 0x05:
            b5 = by_index[ref05][1]
            r4 = struct.unpack_from("<i", wld, b5)[0]
            if r4 <= 0:
                r4 = struct.unpack_from("<i", wld, b5 + 4)[0]
            if 0 < r4 <= len(frags) and by_index[r4][0] == 0x04:
                b4 = by_index[r4][1]
                fl4 = struct.unpack_from("<I", wld, b4 + 4)[0]
                p4 = b4 + 12 + (4 if fl4 & 0x04 else 0) + (4 if fl4 & 0x08 else 0)
                r3 = struct.unpack_from("<i", wld, p4)[0]
                if not (0 < r3 <= len(frags) and by_index[r3][0] == 0x03):
                    for off in (12, 16, 20):  # defensive: flag variants
                        cand = struct.unpack_from("<i", wld, b4 + off)[0]
                        if 0 < cand <= len(frags) and by_index[cand][0] == 0x03:
                            r3 = cand
                            break
                if 0 < r3 <= len(frags) and by_index[r3][0] == 0x03:
                    names = _bitmap_names(wld, by_index[r3][1])
                    if names:
                        tex = names[0]
        return (tex, rm)

    tables = {}
    for idx, (ftype, body, _s) in by_index.items():
        if ftype != 0x31:
            continue
        cnt = struct.unpack_from("<I", wld, body + 8)[0]
        refs = struct.unpack_from(f"<{cnt}i", wld, body + 12)
        tables[idx] = [
            mat_info(r) if (0 < r <= len(frags) and by_index[r][0] == 0x30)
            else (None, 1)
            for r in refs]
    return tables


def _iter_meshes36(wld: bytes):
    """0x36 meshes with uvs + per-triangle material index + material list ref."""
    frags, _ = _wld_fragments(wld)
    for ftype, body, _size in frags:
        if ftype != 0x36:
            continue
        b = body + 4          # skip nameRef
        b += 4                # flags
        matlist = struct.unpack_from("<i", wld, b)[0]
        b += 4 * 4            # frag1..frag4
        cx, cy, cz = struct.unpack_from("<fff", wld, b)
        b += 12 + 12 + 4 + 12 + 12
        (vcount, uvcount, ncount, ccount, pcount,
         vpcount, ptcount, _vt, _s9, scale) = struct.unpack_from("<10H", wld, b)
        b += 20
        s = 1.0 / (1 << scale)
        verts = []
        for i in range(vcount):
            x, y, z = struct.unpack_from("<3h", wld, b + i * 6)
            verts.append((cx + x * s, cy + y * s, cz + z * s))
        b += vcount * 6
        uvs = []
        for i in range(uvcount):
            u, v = struct.unpack_from("<2h", wld, b + i * 4)
            uvs.append((u / 256.0, v / 256.0))
        b += uvcount * 4
        b += ncount * 3 + ccount * 4
        tris = []
        for i in range(pcount):
            _f, v1, v2, v3 = struct.unpack_from("<4H", wld, b + i * 8)
            tris.append((v1, v2, v3))
        b += pcount * 8
        b += vpcount * 4
        tri_mat = [0] * pcount
        cursor = 0
        for i in range(ptcount):
            cnt, midx = struct.unpack_from("<2H", wld, b + i * 4)
            for j in range(cursor, min(cursor + cnt, pcount)):
                tri_mat[j] = midx
            cursor += cnt
        yield verts, uvs, tris, tri_mat, matlist


def _export_textures(short: str, used: dict, archives: list) -> None:
    """Convert used BMPs to PNG under data/textures/<short>/ (masked ones get
    palette-index-0 transparency, the classic color-key convention)."""
    from io import BytesIO
    from PIL import Image

    out_dir = TEXTURE_DIR / short
    out_dir.mkdir(parents=True, exist_ok=True)
    for tex, masked in used.items():
        target = out_dir / (Path(tex).stem + ".png")
        if target.exists():
            continue
        data = None
        for files in archives:
            if tex in files:
                data = files[tex]
                break
        if data is None:
            continue
        try:
            img = Image.open(BytesIO(data))
            if masked and img.mode == "P":
                alpha = img.point(lambda i: 0 if i == 0 else 255, mode="L")
                img = img.convert("RGBA")
                img.putalpha(alpha)
            else:
                img = img.convert("RGBA")
            img.save(target)
        except Exception:
            logger.warning("Texture conversion failed for %s/%s", short, tex)


def build_geometry3d(s3d_path: Path, short: str) -> dict:
    """Textured 3D payload: floors/ramps/walls/props as per-texture submeshes.
    Ceilings (steep downward faces) and invisible boundary materials are
    dropped. Coordinates are native WLD space (z up)."""
    from math import cos, sin

    files = _read_pfs(s3d_path)
    wld = files.get(f"{short}.wld")
    if wld is None:
        cands = [n for n in files if n.endswith(".wld")
                 and n not in ("lights.wld", "objects.wld")]
        if not cands:
            raise ValueError("no zone wld inside archive")
        wld = files[cands[0]]

    frags, _ = _wld_fragments(wld)
    mat_tables = _material_tables(wld, frags)
    layers = {"floors": {}, "ramps": {}, "walls": {}, "props": {}}
    used_tex: dict = {}

    def push(layer, tex, masked, tri_pts, tri_uvs):
        sub = layers[layer].setdefault(
            tex or "", {"masked": masked, "pos": [], "uv": []})
        sub["masked"] = sub["masked"] or masked
        # reverse winding (CW -> CCW) so three.js FrontSide + lighting work
        order = (0, 2, 1)
        for i in order:
            x, y, z = tri_pts[i]
            u, v = tri_uvs[i]
            sub["pos"].extend((round(x, 1), round(y, 1), round(z, 1)))
            sub["uv"].extend((round(u, 3), round(v, 3)))
        if tex:
            used_tex[tex] = used_tex.get(tex, False) or masked

    def classify(a, b, c):
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length < 1e-6:
            return None
        # EQ winds triangles clockwise (seen from the visible side), so the
        # geometric normal points AWAY from the viewer: negate it.
        nzu = -nz / length
        if nzu >= FLAT_NZ:
            return "floors"
        if nzu >= RAMP_NZ:
            return "ramps"
        if nzu > -RAMP_NZ:
            return "walls"
        return None  # ceiling — always off, never shipped

    def add_mesh(verts, uvs, tris, tri_mat, table,
                 layer_override=None, transform=None):
        for ti, (v1, v2, v3) in enumerate(tris):
            if v1 >= len(verts) or v2 >= len(verts) or v3 >= len(verts):
                continue
            tex, rm = table[tri_mat[ti]] if tri_mat[ti] < len(table) else (None, 1)
            if rm == 0:
                continue  # invisible boundary shell (the phantom "ceiling")
            pts = [verts[v1], verts[v2], verts[v3]]
            if transform:
                pts = [transform(p) for p in pts]
            layer = layer_override or classify(*pts)
            if layer is None:
                continue
            tuvs = [uvs[v] if v < len(uvs) else (0.0, 0.0) for v in (v1, v2, v3)]
            push(layer, tex, rm in MASKED_METHODS, pts, tuvs)

    for verts, uvs, tris, tri_mat, matlist in _iter_meshes36(wld):
        add_mesh(verts, uvs, tris, tri_mat, mat_tables.get(matlist, []))

    # props: instances from objects.wld onto meshes from <short>_obj.s3d
    obj_s3d = s3d_path.with_name(f"{short}_obj.s3d")
    obj_archive = None
    if obj_s3d.exists() and "objects.wld" in files:
        obj_wld = None
        try:
            obj_archive = _read_pfs(obj_s3d)
            obj_wld = obj_archive.get(f"{short}_obj.wld")
        except ValueError:
            obj_archive = None
        if obj_wld:
            obj_frags, obj_name_at = _wld_fragments(obj_wld)
            obj_tables = _material_tables(obj_wld, obj_frags)
            named = [obj_name_at(struct.unpack_from("<i", obj_wld, body)[0]) or ""
                     for ftype, body, _s in obj_frags if ftype == 0x36]
            meshes: dict = {}
            for name, mesh in zip(named, _iter_meshes36(obj_wld)):
                meshes.setdefault(name.split("_")[0], []).append(mesh)
            prop_tris = 0
            for prefix, px, py, pz, yaw, scale in _object_instances(files):
                for verts, uvs, tris, tri_mat, matlist in meshes.get(prefix, []):
                    if prop_tris + len(tris) > MAX_PROP_TRIS:
                        break
                    prop_tris += len(tris)
                    cy_, sy_ = cos(yaw), sin(yaw)

                    def tf(p, px=px, py=py, pz=pz, cy_=cy_, sy_=sy_, s=scale):
                        return (px + s * (cy_ * p[0] - sy_ * p[1]),
                                py + s * (sy_ * p[0] + cy_ * p[1]),
                                pz + s * p[2])

                    add_mesh(verts, uvs, tris, tri_mat,
                             obj_tables.get(matlist, []),
                             layer_override="props", transform=tf)

    _export_textures(short, used_tex,
                     [files] + ([obj_archive] if obj_archive else []))

    out_layers = {}
    xs, ys, zs = [], [], []
    for lname, subs in layers.items():
        out = []
        for tex, sub in subs.items():
            out.append({"tex": (Path(tex).stem + ".png") if tex else None,
                        "masked": sub["masked"],
                        "pos": sub["pos"], "uv": sub["uv"]})
            if lname != "props":
                xs.extend(sub["pos"][0::3])
                ys.extend(sub["pos"][1::3])
                zs.extend(sub["pos"][2::3])
        out_layers[lname] = out
    return {
        "available": True,
        "zone": short,
        "bounds": {"min_x": min(xs), "max_x": max(xs),
                   "min_y": min(ys), "max_y": max(ys),
                   "min_z": min(zs), "max_z": max(zs)} if xs else None,
        "layers": out_layers,
        "counts": {k: sum(len(s["pos"]) // 9 for s in v)
                   for k, v in out_layers.items()},
    }


def geometry3d_for_zone(zone_name: str) -> Optional[dict]:
    """Cached textured 3D payload, or None when no .s3d exists."""
    game_dir = Path(settings.eql_game_dir)
    for short in _short_candidates(zone_name):
        s3d = game_dir / f"{short}.s3d"
        if not s3d.exists():
            continue
        GEOMETRY3D_DIR.mkdir(parents=True, exist_ok=True)
        cache = GEOMETRY3D_DIR / f"{short}.v3.json"
        try:
            if cache.exists() and cache.stat().st_mtime >= s3d.stat().st_mtime:
                return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            payload = build_geometry3d(s3d, short)
        except Exception:
            logger.exception("3D extraction failed for %s", s3d.name)
            return None
        try:
            cache.write_text(json.dumps(payload, separators=(",", ":")),
                             encoding="utf-8")
        except OSError:
            logger.warning("Could not cache 3D geometry for %s", short)
        return payload
    return None


def _object_instances(zone_files: dict):
    """(prefix, x, y, z, yaw_rad, scale) from objects.wld 0x15 fragments.
    Layout (verified on akanon): i32 nameRef(0), i32 actorNameRef, i32 flags,
    i32 pad, floats: x y z, rotZ rotY rotX (512ths of a circle), pad,
    scaleA scaleB, pad."""
    obj = zone_files.get("objects.wld")
    if not obj:
        return
    from math import pi
    frags, name_at = _wld_fragments(obj)
    for ftype, body, _size in frags:
        if ftype != 0x15:
            continue
        actor_ref = struct.unpack_from("<i", obj, body + 4)[0]
        name = (name_at(actor_ref) or "") if actor_ref < 0 else ""
        if not name.endswith("_ACTORDEF"):
            continue
        (px, py, pz, r0, _r1, _r2, _pad,
         s0, s1) = struct.unpack_from("<9f", obj, body + 16)
        scale = s0 or s1 or 1.0
        yaw = r0 / 512.0 * 2.0 * pi
        yield name[:-len("_ACTORDEF")], px, py, pz, yaw, scale
