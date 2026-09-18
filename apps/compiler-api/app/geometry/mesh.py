from __future__ import annotations

import base64
import json
import math
import struct

import numpy as np

from app.geometry.svg import Sample


MESH_KINDS = {"glb", "obj", "stl"}


def decode_content(content: str) -> bytes | str:
    text = content.strip()
    if text.startswith("data:") and "," in text:
        return base64.b64decode(text.split(",", 1)[1])
    if text.startswith(("v ", "o ", "#", "mtllib", "solid")):
        return text
    try:
        raw = base64.b64decode(text, validate=True)
        if raw[:4] in {b"glTF", b"solid"} or raw[:5] == b"solid" or len(raw) > 80:
            return raw
    except Exception:
        pass
    return text


def icosphere_obj(subdivisions: int = 1) -> str:
    verts, faces = _icosphere(subdivisions)
    lines = ["# lumina icosphere", f"o orb"]
    for x, y, z in verts:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for a, b, c in faces:
        lines.append(f"f {a + 1} {b + 1} {c + 1}")
    return "\n".join(lines) + "\n"


def _icosphere(subdivisions: int) -> tuple[np.ndarray, np.ndarray]:
    t = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1, t, 0),
        (1, t, 0),
        (-1, -t, 0),
        (1, -t, 0),
        (0, -1, t),
        (0, 1, t),
        (0, -1, -t),
        (0, 1, -t),
        (t, 0, -1),
        (t, 0, 1),
        (-t, 0, -1),
        (-t, 0, 1),
    ]
    verts = []
    for p in raw:
        a = np.array(p, dtype=np.float64)
        verts.append(tuple(a / np.linalg.norm(a)))
    faces = [
        (0, 11, 5),
        (0, 5, 1),
        (0, 1, 7),
        (0, 7, 10),
        (0, 10, 11),
        (1, 5, 9),
        (5, 11, 4),
        (11, 10, 2),
        (10, 7, 6),
        (7, 1, 8),
        (3, 9, 4),
        (3, 4, 2),
        (3, 2, 6),
        (3, 6, 8),
        (3, 8, 9),
        (4, 9, 5),
        (2, 4, 11),
        (6, 2, 10),
        (8, 6, 7),
        (9, 8, 1),
    ]
    lookup: dict[tuple[int, int], int] = {}

    def midpoint(i: int, j: int) -> int:
        key = (i, j) if i < j else (j, i)
        if key in lookup:
            return lookup[key]
        p = (np.array(verts[i]) + np.array(verts[j])) * 0.5
        p = p / np.linalg.norm(p)
        lookup[key] = len(verts)
        verts.append(tuple(p))
        return lookup[key]

    for _ in range(subdivisions):
        nxt = []
        lookup.clear()
        for i, j, k in faces:
            a, b, c = midpoint(i, j), midpoint(j, k), midpoint(k, i)
            nxt.extend([(i, a, c), (j, b, a), (k, c, b), (a, b, c)])
        faces = nxt
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int32)


def load_mesh(kind: str, content: str) -> tuple[np.ndarray, np.ndarray]:
    raw = decode_content(content)
    if kind == "obj" or (isinstance(raw, str) and "\nf " in raw):
        return _load_obj(raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore"))
    if kind == "stl":
        data = raw.encode() if isinstance(raw, str) else raw
        return _load_stl(data)
    if kind == "glb":
        data = raw.encode() if isinstance(raw, str) else raw
        return _load_glb(data)
    raise ValueError(f"Unsupported mesh kind: {kind}")


def _load_obj(text: str) -> tuple[np.ndarray, np.ndarray]:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for line in text.splitlines():
        if line.startswith("v "):
            p = line.split()
            verts.append((float(p[1]), float(p[2]), float(p[3])))
        elif line.startswith("f "):
            idx = [int(tok.split("/")[0]) - 1 for tok in line.split()[1:]]
            for i in range(1, len(idx) - 1):
                faces.append((idx[0], idx[i], idx[i + 1]))
    if not verts or not faces:
        raise ValueError("OBJ has no triangles")
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int32)


def _load_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    if data[:5].lower() == b"solid" and b"facet" in data[:2000]:
        return _load_stl_ascii(data.decode("utf-8", errors="ignore"))
    count = struct.unpack_from("<I", data, 80)[0]
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    off = 84
    for _ in range(count):
        tri = struct.unpack_from("<12fH", data, off)
        off += 50
        base = len(verts)
        verts.extend([(tri[3], tri[4], tri[5]), (tri[6], tri[7], tri[8]), (tri[9], tri[10], tri[11])])
        faces.append((base, base + 1, base + 2))
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int32)


def _load_stl_ascii(text: str) -> tuple[np.ndarray, np.ndarray]:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    cur: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("vertex"):
            p = s.split()
            cur.append((float(p[1]), float(p[2]), float(p[3])))
            if len(cur) == 3:
                base = len(verts)
                verts.extend(cur)
                faces.append((base, base + 1, base + 2))
                cur = []
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int32)


def _load_glb(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    magic, _version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("Not a GLB file")
    off = 12
    doc = None
    blob = b""
    while off + 8 <= length:
        clen, ctype = struct.unpack_from("<I4s", data, off)
        off += 8
        chunk = data[off : off + clen]
        off += clen
        if ctype.startswith(b"JSON"):
            doc = json.loads(chunk)
        elif ctype.startswith(b"BIN"):
            blob = chunk
    if not doc:
        raise ValueError("GLB missing JSON")
    views = doc.get("bufferViews", [])
    accessors = doc.get("accessors", [])

    def accessor_data(index: int) -> np.ndarray:
        acc = accessors[index]
        view = views[acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        ctype = acc["componentType"]
        typ = acc["type"]
        n = acc["count"]
        fmt = {5126: "f", 5123: "H", 5125: "I", 5121: "B"}[ctype]
        comps = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[typ]
        raw = blob[start : start + n * comps * struct.calcsize(fmt)]
        arr = np.frombuffer(raw, dtype={"f": np.float32, "H": np.uint16, "I": np.uint32, "B": np.uint8}[fmt])
        return arr.reshape(n, comps).astype(np.float64)

    def primitive_mesh(mesh_index: int) -> list[tuple[np.ndarray, np.ndarray]]:
        out: list[tuple[np.ndarray, np.ndarray]] = []
        mesh = doc.get("meshes", [])[mesh_index]
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            v = accessor_data(attrs["POSITION"])
            if "indices" in prim:
                idx = accessor_data(prim["indices"]).reshape(-1).astype(np.int32)
                faces = idx.reshape(-1, 3)
            else:
                faces = np.arange(len(v), dtype=np.int32).reshape(-1, 3)
            out.append((v, faces))
        return out

    all_v: list[np.ndarray] = []
    all_f: list[np.ndarray] = []
    base = 0

    def append_transformed(v: np.ndarray, faces: np.ndarray, world: np.ndarray) -> None:
        nonlocal base
        ones = np.ones((len(v), 1))
        h = np.hstack([v, ones])
        w = (world @ h.T).T[:, :3]
        all_v.append(w)
        all_f.append(faces + base)
        base += len(v)

    nodes = doc.get("nodes", [])
    children: set[int] = set()
    for node in nodes:
        children.update(int(c) for c in node.get("children", []))
    scene_id = doc.get("scene")
    if scene_id is not None and doc.get("scenes"):
        roots = [int(i) for i in doc["scenes"][scene_id].get("nodes", [])]
    else:
        roots = [i for i in range(len(nodes)) if i not in children]

    def walk(index: int, parent: np.ndarray) -> None:
        node = nodes[index]
        world = parent @ _node_matrix(node)
        if "mesh" in node:
            for v, faces in primitive_mesh(int(node["mesh"])):
                append_transformed(v, faces, world)
        for child in node.get("children", []):
            walk(int(child), world)

    if nodes and roots:
        for root in roots:
            walk(root, np.eye(4))
    else:
        for mesh_i in range(len(doc.get("meshes", []))):
            for v, faces in primitive_mesh(mesh_i):
                append_transformed(v, faces, np.eye(4))
    if not all_v:
        raise ValueError("GLB has no POSITION data")
    return weld_mesh(np.vstack(all_v), np.vstack(all_f))


def _node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.array(node.get("translation", [0.0, 0.0, 0.0]), dtype=np.float64)
    q = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    s = np.array(node.get("scale", [1.0, 1.0, 1.0]), dtype=np.float64)
    x, y, z, w = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    rot = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    m = np.eye(4)
    m[:3, :3] = rot @ np.diag(s)
    m[:3, 3] = t
    return m


def weld_mesh(verts: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(verts) == 0:
        return verts, faces
    span = float(np.max(verts.max(axis=0) - verts.min(axis=0)))
    decimals = 5 if span < 50 else 4
    uniq, inv = np.unique(np.round(verts, decimals), axis=0, return_inverse=True)
    remapped = inv[faces]
    keep = (remapped[:, 0] != remapped[:, 1]) & (remapped[:, 1] != remapped[:, 2]) & (remapped[:, 0] != remapped[:, 2])
    return uniq.astype(np.float64), remapped[keep]


def to_dshow(verts: np.ndarray) -> np.ndarray:
    """Mesh Y-up → DSHOW_LOCAL_RH (X right, Y audience, Z up)."""
    return np.column_stack([verts[:, 0], verts[:, 2], verts[:, 1]])


def sample_surface(verts: np.ndarray, faces: np.ndarray, count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total = float(areas.sum())
    if total <= 1e-12:
        return verts[:count] if len(verts) >= count else np.repeat(verts, count, axis=0)[:count]
    n = max(count * 8, count)
    pick = rng.choice(len(faces), size=n, p=areas / total)
    u = rng.random(n)
    v = rng.random(n)
    fold = u + v > 1.0
    u[fold] = 1.0 - u[fold]
    v[fold] = 1.0 - v[fold]
    w = 1.0 - u - v
    pts = a[pick] * w[:, None] + b[pick] * u[:, None] + c[pick] * v[:, None]
    return farthest_3d(pts, count)


def farthest_3d(pts: np.ndarray, n: int) -> np.ndarray:
    if len(pts) <= n:
        extra = []
        need = n - len(pts)
        for i in range(need):
            extra.append(pts[i % len(pts)] + np.array([0.02 * ((i % 5) - 2), 0.02 * ((i // 5) % 3 - 1), 0.02 * (i % 3 - 1)]))
        return np.vstack([pts, extra]) if extra else pts
    start = int(np.argmax(pts[:, 2]))
    picked = [start]
    min_d = np.sum((pts - pts[start]) ** 2, axis=1)
    for _ in range(n - 1):
        nxt = int(np.argmax(min_d))
        picked.append(nxt)
        min_d = np.minimum(min_d, np.sum((pts - pts[nxt]) ** 2, axis=1))
    return pts[picked]


def sample_silhouette(verts: np.ndarray, faces: np.ndarray, count: int, seed: int) -> np.ndarray:
    cloud = sample_surface(verts, faces, max(count * 4, 64), seed)
    xz = cloud[:, [0, 2]]
    hull = _convex_hull(xz)
    if len(hull) < 3:
        return cloud[:count]
    edge = _even_polyline(hull, max(count // 2, 8))
    fill_n = count - len(edge)
    fill = cloud[np.argsort(np.abs(cloud[:, 1]))[: max(fill_n, 0)]]
    pts = np.vstack([np.column_stack([edge[:, 0], np.zeros(len(edge)), edge[:, 1]]), fill])
    return farthest_3d(pts, count)


def _convex_hull(pts: np.ndarray) -> np.ndarray:
    pts = np.unique(np.round(pts, 6), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[np.ndarray] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[np.ndarray] = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def _even_polyline(poly: np.ndarray, n: int) -> np.ndarray:
    closed = np.vstack([poly, poly[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1]) or 1.0
    ts = (np.arange(n) + 0.5) / n * total
    out = []
    for t in ts:
        i = int(np.searchsorted(cum, t, side="right") - 1)
        i = min(max(i, 0), len(seg) - 1)
        span = max(seg[i], 1e-9)
        u = (t - cum[i]) / span
        out.append(closed[i] + (closed[i + 1] - closed[i]) * u)
    return np.array(out)


def crease_samples(verts: np.ndarray, faces: np.ndarray, count: int) -> np.ndarray:
    if len(faces) == 0 or count <= 0:
        return np.zeros((0, 3))
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    normals = np.cross(b - a, c - a)
    nn = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, np.maximum(nn, 1e-12))
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fi, (i, j, k) in enumerate(faces):
        for u, v in ((i, j), (j, k), (k, i)):
            key = (int(u), int(v)) if u < v else (int(v), int(u))
            edge_faces.setdefault(key, []).append(fi)
    creases: list[np.ndarray] = []
    for (u, v), fis in edge_faces.items():
        if len(fis) != 2:
            creases.append(0.5 * (verts[u] + verts[v]))
            continue
        if float(np.dot(normals[fis[0]], normals[fis[1]])) < 0.76:
            creases.append(0.5 * (verts[u] + verts[v]))
    if not creases:
        return np.zeros((0, 3))
    pts = np.array(creases, dtype=np.float64)
    return farthest_3d(pts, min(count, len(pts)))


def occupancy_silhouette(cloud: np.ndarray, count: int) -> np.ndarray:
    if len(cloud) == 0 or count <= 0:
        return np.zeros((0, 3))
    xz = cloud[:, [0, 2]]
    mn = xz.min(axis=0)
    span = np.maximum(xz.max(axis=0) - mn, 1e-6)
    res = 72
    ix = np.clip(((xz[:, 0] - mn[0]) / span[0] * (res - 1)).astype(int), 0, res - 1)
    iz = np.clip(((xz[:, 1] - mn[1]) / span[1] * (res - 1)).astype(int), 0, res - 1)
    occ = np.zeros((res, res), dtype=bool)
    occ[ix, iz] = True
    pad = np.pad(occ, 1, constant_values=False)
    border = occ & ~(pad[1:-1, 1:-1] & pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:])
    on_border = border[ix, iz]
    if not on_border.any():
        return farthest_3d(cloud, min(count, len(cloud)))
    return farthest_3d(cloud[on_border], min(count, int(on_border.sum())))


def mesh_candidates(kind: str, content: str, count: int, mode: str, seed: int) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float, float]]]:
    verts, faces = load_mesh(kind, content)
    if kind != "glb":
        verts, faces = weld_mesh(verts, faces)
    dshow = to_dshow(verts)
    n_surf = max(count * 10, 160)
    n_feat = max(count, 48)
    surface = sample_surface(dshow, faces, n_surf, seed)
    outline = occupancy_silhouette(surface, n_feat)
    if mode in {"silhouette", "audience", "outline"}:
        fill = surface[np.argsort(np.abs(surface[:, 1]))[: max(count * 4, 64)]]
        pts = np.vstack([outline, fill]) if len(outline) else fill
        weights = np.concatenate([np.full(len(outline), 1.4), np.full(len(fill), 1.0)])
    else:
        creases = crease_samples(dshow, faces, n_feat)
        parts = [p for p in (creases, outline, surface) if len(p)]
        pts = np.vstack(parts)
        weights = np.concatenate(
            [
                np.full(len(creases), 1.45),
                np.full(len(outline), 1.35),
                np.full(len(surface), 1.0),
            ]
        )
    z = pts[:, 2]
    zn = (z - z.min()) / max(float(z.max() - z.min()), 1e-6)
    colors = [(0.45 + 0.45 * float(t), 0.7, 1.0 - 0.25 * float(t)) for t in zn]
    return pts, weights, colors


def mesh_samples(kind: str, content: str, count: int, mode: str, seed: int) -> tuple[list[Sample], np.ndarray]:
    pts, weights, colors = mesh_candidates(kind, content, count, mode, seed)
    samples = [Sample(float(p[0]), float(p[2]), float(w), col) for p, w, col in zip(pts, weights, colors, strict=True)]
    return samples, pts


def fit_volume(
    pts: np.ndarray,
    colors: list[tuple[float, float, float]],
    width: float,
    height: float,
    depth: float,
    z0: float,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float], float]]:
    span = np.maximum(pts.max(axis=0) - pts.min(axis=0), 1e-4)
    depth = max(depth, 8.0)
    scale = min(width / span[0], depth / span[1], height / span[2]) * 0.92
    c = pts.mean(axis=0)
    out = []
    for p, col in zip(pts, colors, strict=True):
        q = (p - c) * scale
        out.append(((float(q[0]), float(q[1]), float(q[2]) + z0), col, 1.0))
    return out
