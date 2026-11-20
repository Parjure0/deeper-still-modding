"""Fix of GLB files written by Blender for the game's glTF loader.

glTF accessors without a bufferView (all zeros according to the
specification, e.g. empty morph targets written by Blender) are refused by
the game's loader: they are given a zero-filled buffer view. The file is
rewritten in place.
"""

import json
import struct

COMP = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def fix(path):
    with open(path, "rb") as f:
        data = f.read()
    jlen = struct.unpack_from("<I", data, 12)[0]
    j = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen = struct.unpack_from("<I", data, off)[0]
    bin_chunk = bytearray(data[off + 8:off + 8 + blen])
    todo = [a for a in j.get("accessors", []) if "bufferView" not in a]
    if not todo:
        return False
    for a in todo:
        while len(bin_chunk) % 4:
            bin_chunk.append(0)
        size = a["count"] * NCOMP[a["type"]] * COMP[a["componentType"]]
        j.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": len(bin_chunk), "byteLength": size})
        a["bufferView"] = len(j["bufferViews"]) - 1
        bin_chunk.extend(b"\0" * size)
    while len(bin_chunk) % 4:
        bin_chunk.append(0)
    j["buffers"][0]["byteLength"] = len(bin_chunk)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_chunk))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk
    with open(path, "wb") as f:
        f.write(out)
    return True
