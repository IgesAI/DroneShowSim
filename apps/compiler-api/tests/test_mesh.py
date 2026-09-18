import base64
import json
import struct

import numpy as np

from app.formation.sample import generate_formation
from app.geometry.mesh import icosphere_obj, load_mesh
from app.models import FormationGenerationSettings


def _minimal_glb(translation=(0.0, 0.0, 0.0)) -> bytes:
    verts = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=np.float32)
    idx = np.array([0, 1, 2, 0, 2, 3, 0, 3, 1, 1, 3, 2], dtype=np.uint16)
    blob = verts.tobytes() + idx.tobytes()
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "translation": list(translation)}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "max": [2, 2, 2],
                "min": [0, 0, 0],
            },
            {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 48},
            {"buffer": 0, "byteOffset": 48, "byteLength": 24},
        ],
        "buffers": [{"byteLength": 72}],
    }
    payload = json.dumps(doc, separators=(",", ":")).encode() + b"   "
    payload = payload[: len(payload) - (len(payload) % 4)]
    while len(payload) % 4:
        payload += b" "
    blob += b"\x00" * ((4 - (len(blob) % 4)) % 4)
    json_chunk = struct.pack("<I4s", len(payload), b"JSON") + payload
    bin_chunk = struct.pack("<I4s", len(blob), b"BIN\x00") + blob
    header = struct.pack("<4sII", b"glTF", 2, 12 + len(json_chunk) + len(bin_chunk))
    return header + json_chunk + bin_chunk


def test_icosphere_has_triangles():
    verts, faces = load_mesh("obj", icosphere_obj(1))
    assert len(verts) >= 12
    assert len(faces) >= 20


def test_mesh_formation_is_volumetric():
    f = generate_formation(
        formation_id="orb",
        name="orb",
        asset_id="a",
        content=icosphere_obj(1),
        kind="obj",
        count=40,
        settings=FormationGenerationSettings(mode="surface", widthM=40, heightM=40, depthM=40, seed=2),
    )
    assert len(f.points) == 40
    xs = [p.position[0] for p in f.points]
    ys = [p.position[1] for p in f.points]
    zs = [p.position[2] for p in f.points]
    assert max(xs) - min(xs) > 10
    assert max(ys) - min(ys) > 10
    assert max(zs) - min(zs) > 10


def test_mesh_deterministic():
    kwargs = dict(
        formation_id="orb",
        name="orb",
        asset_id="a",
        content=icosphere_obj(1),
        kind="obj",
        count=24,
        settings=FormationGenerationSettings(mode="surface", widthM=30, heightM=30, depthM=30, seed=9),
    )
    a = generate_formation(**kwargs)
    b = generate_formation(**kwargs)
    assert [p.position for p in a.points] == [p.position for p in b.points]


def test_glb_applies_node_translation():
    content = base64.b64encode(_minimal_glb((10.0, 0.0, 0.0))).decode("ascii")
    raw = load_mesh("glb", content)
    xs = raw[0][:, 0]
    assert float(xs.mean()) > 8.0


def test_mesh_keeps_drones_on_the_part():
    f = generate_formation(
        formation_id="orb",
        name="orb",
        asset_id="a",
        content=icosphere_obj(1),
        kind="obj",
        count=80,
        settings=FormationGenerationSettings(mode="surface", widthM=24, heightM=24, depthM=24, seed=2),
        min_sep_m=3.7,
    )
    on_part = [p for p in f.points if p.importance >= 0.9]
    assert len(f.points) == 80
    assert len(on_part) >= 70
    assert f.generationSettings.packScale >= 1.0
    pts = np.array([p.position for p in f.points])
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
    np.fill_diagonal(d2, np.inf)
    assert float(np.sqrt(d2.min())) >= 3.7 * 0.999
