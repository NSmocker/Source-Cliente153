bl_info = {
    "name": "MimoBMD Exporter",
    "author": "MiMo",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "File > Export > MimoBMD (.bmd)",
    "description": "Export Angelica2 BMD files with optional collision (Convex Hull brushes)",
    "category": "Import-Export",
}

import math
import os
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
    from bpy_extras.io_utils import ExportHelper
except ImportError:
    bpy = None
    ExportHelper = object

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AFILE_BINARY_HEAD = b"MOXB"
A3DLITMODEL_VERSION = 0x10000002
A3DLITMESH_REFERENCE_VERSION = 0x10000004
A3DLITMESH_CURRENT_VERSION = 0x10000006
ELBRUSHBUILDING_VERSION = 0x80000001

DEFAULT_REFERENCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Reference File",
    "withCollision.bmd",
)
DEFAULT_REFERENCE_NO_COLLISION = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Reference File",
    "litmodel_1222.bmd",
)

Vec3 = Tuple[float, float, float]
Color = Tuple[float, float, float, float]
Mat4 = Tuple[Tuple[float, float, float, float], ...]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReferenceDefaults:
    scale: Vec3 = (1.0, 1.0, 1.0)
    direction: Vec3 = (0.0, 0.0, 1.0)
    up: Vec3 = (0.0, 1.0, 0.0)
    position: Vec3 = (0.0, 0.0, 0.0)
    mesh_name: str = "Plane13"
    texture: str = r"Building\textures\g\79c.dds"
    diffuse: int = 0xFFFFFFFF
    day_color: int = 0xFF808080
    night_color: int = 0xFF808080
    mesh_version: int = A3DLITMESH_REFERENCE_VERSION
    write_zero_hull: bool = True


@dataclass
class BMDMaterial:
    name: str = ""
    ambient: Color = (1.0, 1.0, 1.0, 1.0)
    diffuse: Color = (1.0, 1.0, 1.0, 1.0)
    emissive: Color = (0.0, 0.0, 0.0, 0.0)
    specular: Color = (0.0, 0.0, 0.0, 1.0)
    power: float = 0.0
    two_sided: bool = False


@dataclass
class BMDVertex:
    pos: Vec3
    normal: Vec3
    diffuse: int
    day_color: int
    night_color: int
    uv: Tuple[float, float]


@dataclass
class BMDMesh:
    name: str
    texture: str
    vertices: List[BMDVertex] = field(default_factory=list)
    indices: List[int] = field(default_factory=list)
    material: BMDMaterial = field(default_factory=BMDMaterial)
    hull_faces: List[List[int]] = field(default_factory=list)

    @property
    def face_count(self) -> int:
        return len(self.indices) // 3


@dataclass
class CDBrushSide:
    normal: Vec3
    dist: float
    bevel: bool


@dataclass
class CDBrush:
    aabb_center: Vec3 = (0.0, 0.0, 0.0)
    aabb_extents: Vec3 = (0.0, 0.0, 0.0)
    aabb_mins: Vec3 = (0.0, 0.0, 0.0)
    aabb_maxs: Vec3 = (0.0, 0.0, 0.0)
    reserved: int = 0
    sides: List[CDBrushSide] = field(default_factory=list)


@dataclass
class BMDExportSettings:
    use_selection: bool = True
    apply_modifiers: bool = True
    axis_mode: str = "BLENDER_TO_A3D"
    flip_v: bool = True
    flip_winding: bool = True
    mesh_version: str = "REFERENCE_V4"
    transform_mode: str = "IDENTITY"
    texture_folder: str = "building\\textures"
    use_reference_texture: bool = True
    use_reference_colors: bool = True
    write_zero_hull: bool = True
    reference_path: str = DEFAULT_REFERENCE
    use_collision: bool = False
    collide_only: bool = False


# ---------------------------------------------------------------------------
# Low-level read helpers (for reference parsing)
# ---------------------------------------------------------------------------

def _read_u32(data: bytes, offset: int) -> Tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _read_i32(data: bytes, offset: int) -> Tuple[int, int]:
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_vec3(data: bytes, offset: int) -> Tuple[Vec3, int]:
    return struct.unpack_from("<fff", data, offset), offset + 12


def _read_fixed_string(data: bytes, offset: int, size: int) -> Tuple[str, int]:
    raw = data[offset : offset + size]
    return _decode_bytes(raw.split(b"\0", 1)[0]), offset + size


# ---------------------------------------------------------------------------
# Encoding / decoding helpers
# ---------------------------------------------------------------------------

def _decode_bytes(raw: bytes) -> str:
    for enc in ("mbcs", "cp1251", "utf-8", "latin1"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("latin1", errors="replace")


def _encode_text(text: str, limit: Optional[int] = None) -> bytes:
    text = text or ""
    for enc in ("mbcs", "cp1251", "utf-8"):
        try:
            raw = text.encode(enc, errors="replace")
            break
        except LookupError:
            continue
    else:
        raw = text.encode("latin1", errors="replace")
    if limit is not None:
        raw = raw[: max(0, limit)]
    return raw


def _fixed_string(text: str, size: int) -> bytes:
    raw = _encode_text(text, size - 1)
    return raw + (b"\0" * (size - len(raw)))


def _cstring(text: str) -> bytes:
    return _encode_text(text) + b"\0"


def _sanitize_path(path: str) -> str:
    path = (path or "").replace("/", "\\")
    if path.startswith("\\\\"):
        return path
    while path.startswith(".\\"):
        path = path[2:]
    return path


def _safe_name(name: str, fallback: str) -> str:
    name = (name or "").strip()
    return name if name else fallback


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _vec_len(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _normalize(v: Vec3) -> Vec3:
    mag = _vec_len(v)
    if mag < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _mat_mul(a: Mat4, b: Mat4) -> Mat4:
    rows = []
    for i in range(4):
        row = []
        for j in range(4):
            row.append(sum(a[i][k] * b[k][j] for k in range(4)))
        rows.append(tuple(row))
    return tuple(rows)  # type: ignore[return-value]


def _scale_matrix(scale: Vec3) -> Mat4:
    return (
        (scale[0], 0.0, 0.0, 0.0),
        (0.0, scale[1], 0.0, 0.0),
        (0.0, 0.0, scale[2], 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _transform_matrix(direction: Vec3, up: Vec3, position: Vec3) -> Mat4:
    z_axis = _normalize(direction)
    y_axis = _normalize(up)
    x_axis = _normalize(_cross(y_axis, z_axis))
    return (
        (x_axis[0], x_axis[1], x_axis[2], 0.0),
        (y_axis[0], y_axis[1], y_axis[2], 0.0),
        (z_axis[0], z_axis[1], z_axis[2], 0.0),
        (position[0], position[1], position[2], 1.0),
    )


def _model_matrix(scale: Vec3, direction: Vec3, up: Vec3, position: Vec3) -> Mat4:
    return _mat_mul(_scale_matrix(scale), _transform_matrix(direction, up, position))


def _det3(m: Sequence[Sequence[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _inverse_affine_row(m: Mat4) -> Mat4:
    a = [list(m[i][:3]) for i in range(3)]
    det = _det3(a)
    if abs(det) < 1e-12:
        return (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    inv_det = 1.0 / det
    inv = [
        [
            (a[1][1] * a[2][2] - a[1][2] * a[2][1]) * inv_det,
            (a[0][2] * a[2][1] - a[0][1] * a[2][2]) * inv_det,
            (a[0][1] * a[1][2] - a[0][2] * a[1][1]) * inv_det,
        ],
        [
            (a[1][2] * a[2][0] - a[1][0] * a[2][2]) * inv_det,
            (a[0][0] * a[2][2] - a[0][2] * a[2][0]) * inv_det,
            (a[0][2] * a[1][0] - a[0][0] * a[1][2]) * inv_det,
        ],
        [
            (a[1][0] * a[2][1] - a[1][1] * a[2][0]) * inv_det,
            (a[0][1] * a[2][0] - a[0][0] * a[2][1]) * inv_det,
            (a[0][0] * a[1][1] - a[0][1] * a[1][0]) * inv_det,
        ],
    ]
    t = m[3][:3]
    inv_t = (
        -(t[0] * inv[0][0] + t[1] * inv[1][0] + t[2] * inv[2][0]),
        -(t[0] * inv[0][1] + t[1] * inv[1][1] + t[2] * inv[2][1]),
        -(t[0] * inv[0][2] + t[1] * inv[1][2] + t[2] * inv[2][2]),
    )
    return (
        (inv[0][0], inv[0][1], inv[0][2], 0.0),
        (inv[1][0], inv[1][1], inv[1][2], 0.0),
        (inv[2][0], inv[2][1], inv[2][2], 0.0),
        (inv_t[0], inv_t[1], inv_t[2], 1.0),
    )


def _transform_point_row(v: Vec3, m: Mat4) -> Vec3:
    return (
        v[0] * m[0][0] + v[1] * m[1][0] + v[2] * m[2][0] + m[3][0],
        v[0] * m[0][1] + v[1] * m[1][1] + v[2] * m[2][1] + m[3][1],
        v[0] * m[0][2] + v[1] * m[1][2] + v[2] * m[2][2] + m[3][2],
    )


def _transform_vector_row(v: Vec3, m: Mat4) -> Vec3:
    return (
        v[0] * m[0][0] + v[1] * m[1][0] + v[2] * m[2][0],
        v[0] * m[0][1] + v[1] * m[1][1] + v[2] * m[2][1],
        v[0] * m[0][2] + v[1] * m[1][2] + v[2] * m[2][2],
    )


def _axis_convert(v: Vec3, axis_mode: str) -> Vec3:
    if axis_mode == "BLENDER_TO_A3D":
        return (v[0], v[2], v[1])
    return v


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(value * 255.0 + 0.5)))


def _argb_from_rgba(color: Color) -> int:
    r, g, b, a = color
    return (_clamp_byte(a) << 24) | (_clamp_byte(r) << 16) | (_clamp_byte(g) << 8) | _clamp_byte(b)


def _round_key(values: Iterable[float]) -> Tuple[float, ...]:
    return tuple(round(float(v), 7) for v in values)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def _write_vec3(f: BinaryIO, v: Vec3) -> None:
    f.write(struct.pack("<fff", float(v[0]), float(v[1]), float(v[2])))


def _write_color_value(f: BinaryIO, color: Color) -> None:
    f.write(struct.pack("<ffff", float(color[0]), float(color[1]), float(color[2]), float(color[3])))


def _write_aabb(f: BinaryIO, vertices: Sequence[BMDVertex]) -> None:
    xs = [v.pos[0] for v in vertices]
    ys = [v.pos[1] for v in vertices]
    zs = [v.pos[2] for v in vertices]
    mins = (min(xs), min(ys), min(zs))
    maxs = (max(xs), max(ys), max(zs))
    center = (
        (mins[0] + maxs[0]) * 0.5,
        (mins[1] + maxs[1]) * 0.5,
        (mins[2] + maxs[2]) * 0.5,
    )
    extents = (maxs[0] - center[0], maxs[1] - center[1], maxs[2] - center[2])
    _write_vec3(f, center)
    _write_vec3(f, extents)
    _write_vec3(f, mins)
    _write_vec3(f, maxs)


def _write_material(f: BinaryIO, material: BMDMaterial) -> None:
    f.write(_cstring("MATERIAL: " + material.name))
    _write_color_value(f, material.ambient)
    _write_color_value(f, material.diffuse)
    _write_color_value(f, material.emissive)
    _write_color_value(f, material.specular)
    f.write(struct.pack("<f", float(material.power)))
    f.write(struct.pack("<?", bool(material.two_sided)))


# ---------------------------------------------------------------------------
# Collision: CCDBrush generation
# ---------------------------------------------------------------------------

def _compute_mesh_aabb(vertices: Sequence[BMDVertex]) -> Tuple[Vec3, Vec3, Vec3, Vec3]:
    """Returns (center, extents, mins, maxs) for a set of vertices."""
    xs = [v.pos[0] for v in vertices]
    ys = [v.pos[1] for v in vertices]
    zs = [v.pos[2] for v in vertices]
    mins = (min(xs), min(ys), min(zs))
    maxs = (max(xs), max(ys), max(zs))
    center = (
        (mins[0] + maxs[0]) * 0.5,
        (mins[1] + maxs[1]) * 0.5,
        (mins[2] + maxs[2]) * 0.5,
    )
    extents = (maxs[0] - center[0], maxs[1] - center[1], maxs[2] - center[2])
    return center, extents, mins, maxs


def _make_convex_hull_brush(
    vertices: Sequence[BMDVertex],
    hull_faces: Optional[List[List[int]]] = None,
    reserved: int = 0,
) -> CDBrush:
    """Create a CCDBrush from convex hull face data.

    If hull_faces is provided, generates planes from actual convex hull geometry
    (matching the reference file's ~40 sides).  Falls back to AABB (6 sides)
    when hull data is unavailable.
    """
    center, extents, mins, maxs = _compute_mesh_aabb(vertices)
    brush = CDBrush(
        aabb_center=center,
        aabb_extents=extents,
        aabb_mins=mins,
        aabb_maxs=maxs,
        reserved=reserved,
    )

    if not hull_faces:
        # Fallback: 6 axis-aligned face planes
        brush.sides.append(CDBrushSide(normal=(-1.0, 0.0, 0.0), dist=-mins[0], bevel=True))
        brush.sides.append(CDBrushSide(normal=(1.0, 0.0, 0.0), dist=maxs[0], bevel=True))
        brush.sides.append(CDBrushSide(normal=(0.0, -1.0, 0.0), dist=-mins[1], bevel=True))
        brush.sides.append(CDBrushSide(normal=(0.0, 1.0, 0.0), dist=maxs[1], bevel=True))
        brush.sides.append(CDBrushSide(normal=(0.0, 0.0, -1.0), dist=-mins[2], bevel=True))
        brush.sides.append(CDBrushSide(normal=(0.0, 0.0, 1.0), dist=maxs[2], bevel=True))
        return brush

    # --- Convex hull face planes (non-bevel, matching reference format) ---
    for face_vert_ids in hull_faces:
        if len(face_vert_ids) < 3:
            continue
        v0 = vertices[face_vert_ids[0]].pos
        v1 = vertices[face_vert_ids[1]].pos
        v2 = vertices[face_vert_ids[2]].pos
        e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
        e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
        n = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        )
        mag = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if mag < 1e-10:
            continue
        n = (n[0] / mag, n[1] / mag, n[2] / mag)
        dist = n[0] * v0[0] + n[1] * v0[1] + n[2] * v0[2]
        brush.sides.append(CDBrushSide(normal=n, dist=dist, bevel=False))

    # --- Edge bevel planes (bevel=True, matching reference format) ---
    # Compute the convex hull AABB corners for bevel generation
    all_vert_positions = [v.pos for v in vertices]

    # Build edge set from hull faces
    edge_set: set = set()
    for face in hull_faces:
        nfv = len(face)
        for j in range(nfv):
            a, b = face[j], face[(j + 1) % nfv]
            edge_key = (min(a, b), max(a, b))
            edge_set.add(edge_key)

    for ei0, ei1 in edge_set:
        v0 = all_vert_positions[ei0]
        v1 = all_vert_positions[ei1]
        dx = v1[0] - v0[0]
        dy = v1[1] - v0[1]
        dz = v1[2] - v0[2]
        edge_len = math.sqrt(dx * dx + dy * dy + dz * dz)
        if edge_len < 1e-10:
            continue
        ex, ey, ez = dx / edge_len, dy / edge_len, dz / edge_len

        for axis in range(3):
            for sign in (-1.0, 1.0):
                v_ax = [0.0, 0.0, 0.0]
                v_ax[axis] = sign
                nx = ey * v_ax[2] - ez * v_ax[1]
                ny = ez * v_ax[0] - ex * v_ax[2]
                nz = ex * v_ax[1] - ey * v_ax[0]
                mag = math.sqrt(nx * nx + ny * ny + nz * nz)
                if mag < 0.5:
                    continue
                nx, ny, nz = nx / mag, ny / mag, nz / mag
                d = nx * v0[0] + ny * v0[1] + nz * v0[2]

                # All hull vertices must be on the back side
                all_ok = True
                for vp in all_vert_positions:
                    if nx * vp[0] + ny * vp[1] + nz * vp[2] - d > 0.01:
                        all_ok = False
                        break
                if not all_ok:
                    continue

                # Duplicate check
                is_dup = False
                for existing in brush.sides:
                    en = existing.normal
                    if (abs(en[0] - nx) < 0.01 and
                        abs(en[1] - ny) < 0.01 and
                        abs(en[2] - nz) < 0.01 and
                        abs(existing.dist - d) < 0.01):
                        is_dup = True
                        break
                if not is_dup:
                    brush.sides.append(CDBrushSide(normal=(nx, ny, nz), dist=d, bevel=True))

    return brush


def _write_cd_brush(f: BinaryIO, brush: CDBrush) -> None:
    """Write a single CCDBrush in binary format.

    Format per brush:
        A3DAABB (48 bytes): center(12) + extents(12) + mins(12) + maxs(12)
        DWORD reserved (4 bytes)
        int nSides (4 bytes)
        For each side:
            A3DVECTOR3 normal (12 bytes)
            float dist (4 bytes)
            bool bevel (1 byte)
    """
    _write_vec3(f, brush.aabb_center)
    _write_vec3(f, brush.aabb_extents)
    _write_vec3(f, brush.aabb_mins)
    _write_vec3(f, brush.aabb_maxs)
    f.write(struct.pack("<I", brush.reserved))
    f.write(struct.pack("<i", len(brush.sides)))
    for side in brush.sides:
        _write_vec3(f, side.normal)
        f.write(struct.pack("<f", side.dist))
        f.write(struct.pack("<?", side.bevel))


def _write_collision_data(
    f: BinaryIO,
    meshes: Sequence[BMDMesh],
) -> None:
    """Write the full collision section that follows the A3DLitModel.

    Structure:
        int numHull
        For each hull:
            int numMeshesInHull
            int[] meshIds
        For each hull:
            CCDBrush data
    """
    num_hull = len(meshes)
    f.write(struct.pack("<i", num_hull))

    # Hull mesh list: each hull contains exactly one mesh
    for i in range(num_hull):
        f.write(struct.pack("<i", 1))  # numMeshesInHull
        f.write(struct.pack("<i", i))  # meshId

    # Write one CCDBrush per mesh
    for mesh in meshes:
        brush = _make_convex_hull_brush(
            mesh.vertices,
            hull_faces=mesh.hull_faces if mesh.hull_faces else None,
        )
        _write_cd_brush(f, brush)


# ---------------------------------------------------------------------------
# Reference file parsing
# ---------------------------------------------------------------------------

def parse_bmd_summary(path: str) -> Dict[str, object]:
    data = open(path, "rb").read()
    offset = 0
    file_head = data[:4]
    offset += 4 if file_head in (b"MOXB", b"MOXT") else 0

    first_dword, probe = _read_u32(data, offset)
    has_brush_header = first_dword == ELBRUSHBUILDING_VERSION
    if has_brush_header:
        offset = probe + 1

    # Skip MOXB/MOXT magic that follows the brush header
    if data[offset:offset + 4] in (b"MOXB", b"MOXT"):
        offset += 4

    model_version, offset = _read_u32(data, offset)
    scale, offset = _read_vec3(data, offset)
    direction, offset = _read_vec3(data, offset)
    up, offset = _read_vec3(data, offset)
    position, offset = _read_vec3(data, offset)
    mesh_count, offset = _read_i32(data, offset)
    meshes = []

    for _ in range(mesh_count):
        start = offset
        mesh_version, offset = _read_u32(data, offset)
        name, offset = _read_fixed_string(data, offset, 64)
        texture, offset = _read_fixed_string(data, offset, 256)
        vert_count, offset = _read_i32(data, offset)
        face_count, offset = _read_i32(data, offset)
        has_extra = False
        if mesh_version == A3DLITMESH_CURRENT_VERSION:
            has_extra = bool(data[offset])
            offset += 1

        first_diffuse = None
        for i in range(vert_count):
            offset += 12
            diffuse, offset = _read_u32(data, offset)
            if i == 0:
                first_diffuse = diffuse
            offset += 8

        offset += face_count * 3 * 2
        offset += vert_count * 12

        first_day = None
        first_night = None
        if mesh_version >= 0x10000003:
            for i in range(vert_count):
                color, offset = _read_u32(data, offset)
                if i == 0:
                    first_day = color
            for i in range(vert_count):
                color, offset = _read_u32(data, offset)
                if i == 0:
                    first_night = color

        if has_extra:
            offset += vert_count * 8

        offset += 48

        if mesh_version in (0x10000005, A3DLITMESH_CURRENT_VERSION, 0x10000100):
            end = data.index(b"\0", offset)
            offset = end + 1 + 16 + 16 + 16 + 16 + 4 + 1

        meshes.append(
            {
                "start": start,
                "version": mesh_version,
                "name": name,
                "texture": texture,
                "vertices": vert_count,
                "faces": face_count,
                "first_diffuse": first_diffuse,
                "first_day": first_day,
                "first_night": first_night,
            }
        )

    trailing = data[offset:]
    return {
        "file_head": file_head.decode("latin1", errors="replace") if file_head else "",
        "has_brush_header": has_brush_header,
        "model_version": model_version,
        "scale": scale,
        "direction": direction,
        "up": up,
        "position": position,
        "mesh_count": mesh_count,
        "meshes": meshes,
        "trailing_size": len(trailing),
        "trailing": trailing,
    }


def read_reference_defaults(path: str) -> ReferenceDefaults:
    ref = ReferenceDefaults()
    if not path or not os.path.exists(path):
        return ref
    try:
        summary = parse_bmd_summary(path)
    except Exception:
        return ref

    meshes = summary.get("meshes") or []
    ref.scale = tuple(summary.get("scale", ref.scale))  # type: ignore[arg-type]
    ref.direction = tuple(summary.get("direction", ref.direction))  # type: ignore[arg-type]
    ref.up = tuple(summary.get("up", ref.up))  # type: ignore[arg-type]
    ref.position = tuple(summary.get("position", ref.position))  # type: ignore[arg-type]
    ref.write_zero_hull = summary.get("trailing") == b"\0\0\0\0"

    if meshes:
        first = meshes[0]
        ref.mesh_name = str(first.get("name") or ref.mesh_name)
        ref.texture = str(first.get("texture") or ref.texture)
        ref.mesh_version = int(first.get("version") or ref.mesh_version)
        ref.diffuse = int(first.get("first_diffuse") or ref.diffuse)
        ref.day_color = int(first.get("first_day") or ref.day_color)
        ref.night_color = int(first.get("first_night") or ref.night_color)

    return ref


# ---------------------------------------------------------------------------
# Scene mesh collection
# ---------------------------------------------------------------------------

def _path_filename(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] if normalized else ""


def _join_texture_folder(folder: str, texture_name: str) -> str:
    folder = _sanitize_path(folder.strip()).rstrip("\\/")
    texture_name = _path_filename(_sanitize_path(texture_name.strip()))
    if folder and texture_name:
        return f"{folder}\\{texture_name}"
    return texture_name or folder


def _material_texture_name(mat, obj) -> str:
    for source in (mat, obj):
        if source is not None and "bmd_texture" in source:
            return _path_filename(str(source["bmd_texture"]))
    if mat and getattr(mat, "use_nodes", False):
        for node in mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
                image = node.image
                if image.filepath:
                    path = bpy.path.abspath(image.filepath) if bpy else image.filepath
                    return _path_filename(path)
    return ""


def _material_texture(mat, obj, settings: BMDExportSettings, ref: ReferenceDefaults) -> str:
    texture_name = _material_texture_name(mat, obj)
    if settings.texture_folder.strip():
        if not texture_name and settings.use_reference_texture:
            texture_name = _path_filename(ref.texture)
        return _join_texture_folder(settings.texture_folder, texture_name)
    for source in (mat, obj):
        if source is not None and "bmd_texture" in source:
            return _sanitize_path(str(source["bmd_texture"]))
    if mat and getattr(mat, "use_nodes", False):
        for node in mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
                image = node.image
                if image.filepath:
                    path = bpy.path.abspath(image.filepath) if bpy else image.filepath
                    return _sanitize_path(path)
    if settings.use_reference_texture:
        return ref.texture
    return ""


def _material_settings(mat) -> BMDMaterial:
    if mat is None:
        return BMDMaterial()
    diffuse = tuple(getattr(mat, "diffuse_color", (1.0, 1.0, 1.0, 1.0)))
    return BMDMaterial(
        name=getattr(mat, "name", "") or "",
        ambient=diffuse,
        diffuse=diffuse,
        emissive=(0.0, 0.0, 0.0, diffuse[3]),
        specular=(0.0, 0.0, 0.0, diffuse[3]),
        power=0.0,
        two_sided=not bool(getattr(mat, "use_backface_culling", False)),
    )


def _active_color_attribute(mesh):
    attrs = getattr(mesh, "color_attributes", None)
    if attrs:
        return getattr(attrs, "active_color", None) or getattr(attrs, "active", None)
    return None


def _loop_color(mesh, color_attr, loop_index: int, vertex_index: int) -> Optional[Color]:
    if color_attr is None:
        return None
    domain = getattr(color_attr, "domain", "CORNER")
    data_index = loop_index if domain == "CORNER" else vertex_index
    try:
        c = color_attr.data[data_index].color
        return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
    except Exception:
        return None


def _loop_normal(mesh, loop_index: int) -> Vec3:
    try:
        n = mesh.corner_normals[loop_index].vector
    except Exception:
        n = mesh.loops[loop_index].normal
    return (float(n.x), float(n.y), float(n.z))


def _mesh_material(obj, mat_index: int):
    slots = getattr(obj, "material_slots", [])
    if 0 <= mat_index < len(slots):
        return slots[mat_index].material
    return None


def collect_scene_meshes(context, settings: BMDExportSettings, reference: ReferenceDefaults) -> List[BMDMesh]:
    if bpy is None:
        raise RuntimeError("Blender Python API is not available")

    from mathutils import Vector
    import bmesh

    depsgraph = context.evaluated_depsgraph_get()
    objects = context.selected_objects if settings.use_selection else context.scene.objects
    mesh_objects = [obj for obj in objects if obj.type == "MESH" and obj.visible_get()]
    if not mesh_objects:
        raise ValueError("No visible mesh objects selected" if settings.use_selection else "No visible mesh objects found")

    transform_inverse = None
    if settings.transform_mode == "REFERENCE":
        transform_inverse = _inverse_affine_row(
            _model_matrix(reference.scale, reference.direction, reference.up, reference.position)
        )

    result: List[BMDMesh] = []

    for obj in mesh_objects:
        eval_obj = obj.evaluated_get(depsgraph) if settings.apply_modifiers else obj
        mesh = eval_obj.to_mesh()
        try:
            mesh.calc_loop_triangles()
            if not mesh.loop_triangles:
                continue

            uv_data = mesh.uv_layers.active.data if mesh.uv_layers.active else None
            color_attr = _active_color_attribute(mesh)
            normal_matrix = eval_obj.matrix_world.to_3x3().inverted().transposed()
            groups: Dict[int, Dict[str, object]] = {}

            for tri in mesh.loop_triangles:
                mat_index = int(tri.material_index)
                if mat_index not in groups:
                    mat = _mesh_material(obj, mat_index)
                    tex = _material_texture(mat, obj, settings, reference)
                    mat_name = getattr(mat, "name", "") if mat else ""
                    mesh_name = _safe_name(obj.name if not mat_name else f"{obj.name}-{mat_name}", reference.mesh_name)
                    groups[mat_index] = {
                        "name": mesh_name,
                        "texture": tex,
                        "material": _material_settings(mat),
                        "vertices": [],
                        "indices": [],
                        "lookup": {},
                        "blender_vert_map": {},  # blender_vert_idx -> group_vert_idx
                    }

                group = groups[mat_index]
                loop_indices = list(tri.loops)
                if settings.flip_winding:
                    loop_indices = [loop_indices[0], loop_indices[2], loop_indices[1]]

                for loop_index in loop_indices:
                    loop = mesh.loops[loop_index]
                    vertex_index = loop.vertex_index
                    world_pos = eval_obj.matrix_world @ mesh.vertices[vertex_index].co
                    local_normal = _loop_normal(mesh, loop_index)
                    world_normal = normal_matrix @ Vector(local_normal)

                    pos = _axis_convert((float(world_pos.x), float(world_pos.y), float(world_pos.z)), settings.axis_mode)
                    normal = _axis_convert(
                        (float(world_normal.x), float(world_normal.y), float(world_normal.z)),
                        settings.axis_mode,
                    )

                    if transform_inverse is not None:
                        pos = _transform_point_row(pos, transform_inverse)
                        normal = _transform_vector_row(normal, transform_inverse)

                    normal = _normalize(normal)

                    if uv_data is not None:
                        uv = uv_data[loop_index].uv
                        u = float(uv.x)
                        v = 1.0 - float(uv.y) if settings.flip_v else float(uv.y)
                    else:
                        u, v = 0.0, 0.0

                    color = _loop_color(mesh, color_attr, loop_index, vertex_index)
                    if color is not None:
                        diffuse = day = night = _argb_from_rgba(color)
                    elif settings.use_reference_colors:
                        diffuse, day, night = reference.diffuse, reference.day_color, reference.night_color
                    else:
                        mat = _mesh_material(obj, mat_index)
                        diffuse_color = tuple(getattr(mat, "diffuse_color", (1.0, 1.0, 1.0, 1.0)))
                        diffuse = day = night = _argb_from_rgba(diffuse_color)

                    key = (
                        _round_key(pos),
                        _round_key(normal),
                        round(u, 7),
                        round(v, 7),
                        diffuse,
                        day,
                        night,
                    )

                    lookup = group["lookup"]  # type: ignore[assignment]
                    vertices = group["vertices"]  # type: ignore[assignment]
                    indices = group["indices"]  # type: ignore[assignment]
                    blender_map = group["blender_vert_map"]  # type: ignore[assignment]
                    if key not in lookup:
                        group_idx = len(vertices)
                        lookup[key] = group_idx
                        vertices.append(BMDVertex(pos=pos, normal=normal, diffuse=diffuse, day_color=day, night_color=night, uv=(u, v)))
                        blender_map[vertex_index] = group_idx
                    indices.append(lookup[key])

            # Compute convex hull for each group using bmesh
            hull_faces_per_group: Dict[int, List[List[int]]] = {}
            if settings.use_collision and groups:
                try:
                    bm = bmesh.new()
                    bm.from_mesh(mesh)
                    geom = bmesh.ops.calc_convex_hull(bm, input=bm.verts)
                    hull_bm_faces = geom.get("geom_out", [])
                    # Build hull face index lists in group vertex index space
                    blender_to_group: Dict[int, int] = {}
                    for mat_idx, grp in groups.items():
                        blender_to_group.update(grp["blender_vert_map"])  # type: ignore[arg-type]
                    for mat_idx in groups:
                        hull_faces_per_group[mat_idx] = []
                    for face_el in hull_bm_faces:
                        if not hasattr(face_el, "verts"):
                            continue
                        group_ids: Dict[int, List[int]] = {}
                        for v in face_el.verts:
                            bi = v.index
                            gi = blender_to_group.get(bi)
                            if gi is None:
                                continue
                            # Find which group this belongs to
                            for mat_idx, grp in groups.items():
                                bmap = grp["blender_vert_map"]  # type: ignore[arg-type]
                                if bi in bmap:
                                    gidx = bmap[bi]
                                    group_ids.setdefault(mat_idx, []).append(gidx)
                                    break
                        for mat_idx, gids in group_ids.items():
                            if len(gids) >= 3:
                                hull_faces_per_group[mat_idx].append(gids)
                    bm.free()
                except Exception:
                    pass

            for group in groups.values():
                vertices = group["vertices"]  # type: ignore[assignment]
                indices = group["indices"]  # type: ignore[assignment]
                if vertices and indices:
                    mat_idx = None
                    for k, v in groups.items():
                        if v is group:
                            mat_idx = k
                            break
                    hf = hull_faces_per_group.get(mat_idx, []) if mat_idx is not None else []
                    result.append(
                        BMDMesh(
                            name=str(group["name"]),
                            texture=_sanitize_path(str(group["texture"])),
                            vertices=list(vertices),
                            indices=list(indices),
                            material=group["material"],  # type: ignore[arg-type]
                            hull_faces=hf,
                        )
                    )
        finally:
            eval_obj.to_mesh_clear()

    return result


# ---------------------------------------------------------------------------
# Mesh splitting (16-bit index limit)
# ---------------------------------------------------------------------------

def _split_mesh_for_word_indices(mesh: BMDMesh) -> List[BMDMesh]:
    if len(mesh.vertices) <= 65535:
        return [mesh]

    chunks: List[BMDMesh] = []
    local_vertices: List[BMDVertex] = []
    local_indices: List[int] = []
    remap: Dict[int, int] = {}
    part = 1

    def flush() -> None:
        nonlocal local_vertices, local_indices, remap, part
        if not local_indices:
            return
        chunks.append(
            BMDMesh(
                name=f"{mesh.name}_{part:02d}",
                texture=mesh.texture,
                vertices=local_vertices,
                indices=local_indices,
                material=mesh.material,
            )
        )
        part += 1
        local_vertices = []
        local_indices = []
        remap = {}

    for i in range(0, len(mesh.indices), 3):
        tri = mesh.indices[i : i + 3]
        needed = [idx for idx in tri if idx not in remap]
        if local_indices and len(local_vertices) + len(needed) > 65535:
            flush()
        for idx in tri:
            if idx not in remap:
                remap[idx] = len(local_vertices)
                local_vertices.append(mesh.vertices[idx])
            local_indices.append(remap[idx])

    flush()
    return chunks


# ---------------------------------------------------------------------------
# Main export: write BMD file
# ---------------------------------------------------------------------------

def write_bmd_file(
    path: str,
    meshes: Sequence[BMDMesh],
    settings: BMDExportSettings,
    reference: Optional[ReferenceDefaults] = None,
) -> None:
    meshes_to_write: List[BMDMesh] = []
    for mesh in meshes:
        if mesh.face_count > 0:
            meshes_to_write.extend(_split_mesh_for_word_indices(mesh))

    if not meshes_to_write:
        raise ValueError("No mesh data to export")

    ref = reference or read_reference_defaults(settings.reference_path)
    mesh_version = (
        A3DLITMESH_CURRENT_VERSION
        if settings.mesh_version == "CURRENT_V6"
        else A3DLITMESH_REFERENCE_VERSION
    )

    if settings.transform_mode == "REFERENCE":
        scale, direction, up, position = ref.scale, ref.direction, ref.up, ref.position
    else:
        scale, direction, up, position = (1.0, 1.0, 1.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)

    with open(path, "wb") as f:
        # ---- Brush Building header (if collision enabled) ----
        if settings.use_collision:
            f.write(struct.pack("<I", ELBRUSHBUILDING_VERSION))
            f.write(struct.pack("<?", settings.collide_only))

        # ---- A3DLitModel header ----
        f.write(AFILE_BINARY_HEAD)
        f.write(struct.pack("<I", A3DLITMODEL_VERSION))
        _write_vec3(f, scale)
        _write_vec3(f, direction)
        _write_vec3(f, up)
        _write_vec3(f, position)
        f.write(struct.pack("<i", len(meshes_to_write)))

        # ---- Meshes ----
        for mesh in meshes_to_write:
            f.write(struct.pack("<I", mesh_version))
            f.write(_fixed_string(mesh.name, 64))
            f.write(_fixed_string(mesh.texture, 256))
            f.write(struct.pack("<ii", len(mesh.vertices), mesh.face_count))

            if mesh_version == A3DLITMESH_CURRENT_VERSION:
                f.write(struct.pack("<?", False))

            for vertex in mesh.vertices:
                _write_vec3(f, vertex.pos)
                f.write(struct.pack("<Iff", vertex.diffuse, float(vertex.uv[0]), float(vertex.uv[1])))

            f.write(struct.pack("<" + "H" * len(mesh.indices), *mesh.indices))

            for vertex in mesh.vertices:
                _write_vec3(f, vertex.normal)

            for vertex in mesh.vertices:
                f.write(struct.pack("<I", vertex.day_color))

            for vertex in mesh.vertices:
                f.write(struct.pack("<I", vertex.night_color))

            _write_aabb(f, mesh.vertices)

            if mesh_version == A3DLITMESH_CURRENT_VERSION:
                _write_material(f, mesh.material)

        # ---- Hull / Collision data ----
        if settings.use_collision:
            _write_collision_data(f, meshes_to_write)
        elif settings.write_zero_hull:
            f.write(struct.pack("<i", 0))


# ---------------------------------------------------------------------------
# Export entry point
# ---------------------------------------------------------------------------

def export_bmd(context, filepath: str, settings: BMDExportSettings) -> Dict[str, int]:
    # Pick the right reference file based on collision setting
    if settings.use_collision:
        ref_path = settings.reference_path
    else:
        ref_path = DEFAULT_REFERENCE_NO_COLLISION if not settings.reference_path else settings.reference_path
    reference = read_reference_defaults(ref_path)
    meshes = collect_scene_meshes(context, settings, reference)
    write_bmd_file(filepath, meshes, settings, reference)
    return {
        "meshes": len(meshes),
        "vertices": sum(len(m.vertices) for m in meshes),
        "faces": sum(m.face_count for m in meshes),
        "has_collision": settings.use_collision,
    }


# ---------------------------------------------------------------------------
# Blender operator & UI
# ---------------------------------------------------------------------------

if bpy is not None:

    class EXPORT_OT_mimobmd(bpy.types.Operator, ExportHelper):
        bl_idname = "export_scene.mimobmd"
        bl_label = "Export MimoBMD"
        bl_options = {"PRESET"}

        filename_ext = ".bmd"
        filter_glob: StringProperty(default="*.bmd", options={"HIDDEN"})

        # -- Selection / modifiers --
        use_selection: BoolProperty(
            name="Selected Objects Only",
            default=True,
        )
        apply_modifiers: BoolProperty(
            name="Apply Modifiers",
            default=True,
        )

        # -- Reference --
        reference_path: StringProperty(
            name="Reference BMD",
            subtype="FILE_PATH",
            default=DEFAULT_REFERENCE,
        )

        # -- Mesh format --
        mesh_version: EnumProperty(
            name="Mesh Version",
            items=(
                ("REFERENCE_V4", "Reference v4", "Match litmodel_1222.bmd: no material block"),
                ("CURRENT_V6", "Current v6", "Write current Angelica2 mesh version with material block"),
            ),
            default="REFERENCE_V4",
        )
        transform_mode: EnumProperty(
            name="Model Transform",
            items=(
                ("IDENTITY", "Identity", "Bake scene positions into vertices"),
                ("REFERENCE", "Reference", "Use reference model transform"),
            ),
            default="IDENTITY",
        )
        axis_mode: EnumProperty(
            name="Axis Conversion",
            items=(
                ("BLENDER_TO_A3D", "Blender Z-up to Angelica Y-up", "Write (x, z, y) coordinates"),
                ("NONE", "None", "Write Blender coordinates as-is"),
            ),
            default="BLENDER_TO_A3D",
        )
        flip_winding: BoolProperty(
            name="Flip Triangle Winding",
            default=True,
        )
        flip_v: BoolProperty(
            name="Flip UV V",
            default=True,
        )

        # -- Texture / colors --
        texture_folder: StringProperty(
            name="Texture Folder",
            description="Game-relative folder for exported texture paths",
            default="building\\textures",
        )
        use_reference_texture: BoolProperty(
            name="Use Reference Texture If Missing",
            default=True,
        )
        use_reference_colors: BoolProperty(
            name="Use Reference Vertex Colors If Missing",
            default=True,
        )

        # -- Hull / collision --
        write_zero_hull: BoolProperty(
            name="Write Zero Hull Tail",
            description="Write a trailing int32 zero when collision is disabled",
            default=True,
        )

        # ==========================================
        #  COLLISION OPTIONS
        # ==========================================
        use_collision: BoolProperty(
            name="Use Collision",
            description="Write CELBrushBuilding collision data after the model (convex hull brushes per mesh)",
            default=False,
        )
        collide_only: BoolProperty(
            name="Collide Only",
            description="Mark collision as collide-only (no ray trace, model invisible in engine)",
            default=False,
        )

        def draw(self, context):
            layout = self.layout

            # -- General --
            box = layout.box()
            box.label(text="General", icon="SETTINGS")
            box.prop(self, "use_selection")
            box.prop(self, "apply_modifiers")

            # -- Reference --
            box = layout.box()
            box.label(text="Reference", icon="FILE_FOLDER")
            box.prop(self, "reference_path")

            # -- Mesh --
            box = layout.box()
            box.label(text="Mesh Format", icon="MESH_DATA")
            box.prop(self, "mesh_version")
            box.prop(self, "transform_mode")
            box.prop(self, "axis_mode")
            box.prop(self, "flip_winding")
            box.prop(self, "flip_v")

            # -- Texture / Colors --
            box = layout.box()
            box.label(text="Texture & Colors", icon="TEXTURE")
            box.prop(self, "texture_folder")
            box.prop(self, "use_reference_texture")
            box.prop(self, "use_reference_colors")

            # -- Collision (highlighted) --
            box = layout.box()
            box.label(text="Collision (CELBrushBuilding)", icon="PHYSICS")
            box.prop(self, "use_collision")
            sub = box.column(align=True)
            sub.active = self.use_collision
            sub.prop(self, "collide_only")
            if not self.use_collision:
                box.prop(self, "write_zero_hull")

        def execute(self, context):
            settings = BMDExportSettings(
                use_selection=self.use_selection,
                apply_modifiers=self.apply_modifiers,
                axis_mode=self.axis_mode,
                flip_v=self.flip_v,
                flip_winding=self.flip_winding,
                mesh_version=self.mesh_version,
                transform_mode=self.transform_mode,
                texture_folder=self.texture_folder,
                use_reference_texture=self.use_reference_texture,
                use_reference_colors=self.use_reference_colors,
                write_zero_hull=self.write_zero_hull,
                reference_path=bpy.path.abspath(self.reference_path),
                use_collision=self.use_collision,
                collide_only=self.collide_only,
            )
            try:
                stats = export_bmd(context, self.filepath, settings)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

            collision_info = " + collision" if stats["has_collision"] else ""
            self.report(
                {"INFO"},
                f"Exported {stats['meshes']} meshes, {stats['vertices']} verts, {stats['faces']} faces{collision_info}",
            )
            return {"FINISHED"}

    def _menu_export(self, context):
        self.layout.operator(EXPORT_OT_mimobmd.bl_idname, text="MimoBMD (.bmd)")

    def register():
        bpy.utils.register_class(EXPORT_OT_mimobmd)
        bpy.types.TOPBAR_MT_file_export.append(_menu_export)

    def unregister():
        bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
        bpy.utils.unregister_class(EXPORT_OT_mimobmd)


if __name__ == "__main__":
    if bpy is None:
        import json
        import sys
        target = sys.argv[-1] if len(sys.argv) > 1 else DEFAULT_REFERENCE
        print(json.dumps(parse_bmd_summary(target), indent=2, default=lambda v: v.hex() if isinstance(v, bytes) else v))
    else:
        register()
