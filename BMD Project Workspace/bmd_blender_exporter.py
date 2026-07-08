bl_info = {
    "name": "Angelica2 BMD Exporter",
    "author": "Codex",
    "version": (0, 1, 0),
    "blender": (4, 5, 0),
    "location": "File > Export > Angelica2 BMD (.bmd)",
    "description": "Export static Angelica2 lit-model BMD files compatible with the provided reference",
    "category": "Import-Export",
}

import math
import os
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, StringProperty
    from bpy_extras.io_utils import ExportHelper, ImportHelper
except ImportError:
    bpy = None
    ExportHelper = object
    ImportHelper = object


AFILE_BINARY_HEAD = b"MOXB"
A3DLITMODEL_VERSION = 0x10000002
A3DLITMESH_REFERENCE_VERSION = 0x10000004
A3DLITMESH_CURRENT_VERSION = 0x10000006
ELBRUSHBUILDING_VERSION = 0x80000001
ADDON_NAME = os.path.splitext(os.path.basename(__file__))[0]

DEFAULT_REFERENCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Reference File",
    "litmodel_1222.bmd",
)

Vec3 = Tuple[float, float, float]
Color = Tuple[float, float, float, float]
Mat4 = Tuple[Tuple[float, float, float, float], ...]


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

    @property
    def face_count(self) -> int:
        return len(self.indices) // 3


@dataclass
class BMDExportSettings:
    use_selection: bool = True
    apply_modifiers: bool = True
    axis_mode: str = "BLENDER_TO_A3D"
    flip_v: bool = True
    flip_winding: bool = True
    mesh_version: str = "REFERENCE_V4"
    transform_mode: str = "IDENTITY"
    texture_folder: str = ""
    texture_search_folder: str = ""
    use_reference_texture: bool = True
    use_reference_colors: bool = True
    write_zero_hull: bool = True
    reference_path: str = DEFAULT_REFERENCE


def _read_u32(data: bytes, offset: int) -> Tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _read_i32(data: bytes, offset: int) -> Tuple[int, int]:
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_vec3(data: bytes, offset: int) -> Tuple[Vec3, int]:
    return struct.unpack_from("<fff", data, offset), offset + 12


def _read_fixed_string(data: bytes, offset: int, size: int) -> Tuple[str, int]:
    raw = data[offset : offset + size]
    return _decode_bytes(raw.split(b"\0", 1)[0]), offset + size


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


def parse_bmd_summary(path: str) -> Dict[str, object]:
    data = open(path, "rb").read()
    offset = 0
    file_head = data[:4]
    offset += 4 if file_head in (b"MOXB", b"MOXT") else 0

    first_dword, probe = _read_u32(data, offset)
    has_brush_header = first_dword == ELBRUSHBUILDING_VERSION
    if has_brush_header:
        offset = probe + 1

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


def parse_bmd_meshes(path: str, apply_model_transform: bool = True) -> List[BMDMesh]:
    data = open(path, "rb").read()
    offset = 0
    file_head = data[:4]
    offset += 4 if file_head in (b"MOXB", b"MOXT") else 0

    first_dword, probe = _read_u32(data, offset)
    has_brush_header = first_dword == ELBRUSHBUILDING_VERSION
    if has_brush_header:
        offset = probe + 1

    model_version, offset = _read_u32(data, offset)
    scale, offset = _read_vec3(data, offset)
    direction, offset = _read_vec3(data, offset)
    up, offset = _read_vec3(data, offset)
    position, offset = _read_vec3(data, offset)
    model_matrix = _model_matrix(scale, direction, up, position)
    mesh_count, offset = _read_i32(data, offset)
    meshes: List[BMDMesh] = []

    for _ in range(mesh_count):
        mesh_version, offset = _read_u32(data, offset)
        name, offset = _read_fixed_string(data, offset, 64)
        texture, offset = _read_fixed_string(data, offset, 256)
        vert_count, offset = _read_i32(data, offset)
        face_count, offset = _read_i32(data, offset)

        has_extra = False
        if mesh_version == A3DLITMESH_CURRENT_VERSION:
            has_extra = bool(data[offset])
            offset += 1

        vertices: List[BMDVertex] = []
        for i in range(vert_count):
            pos, offset = _read_vec3(data, offset)
            diffuse, offset = _read_u32(data, offset)
            u = struct.unpack_from("<f", data, offset)[0]
            v = struct.unpack_from("<f", data, offset + 4)[0]
            offset += 8

            if apply_model_transform:
                pos = _transform_point_row(pos, model_matrix)

            vertices.append(
                BMDVertex(
                    pos=pos,
                    normal=(0.0, 0.0, 0.0),
                    diffuse=diffuse,
                    day_color=0xFF808080,
                    night_color=0xFF808080,
                    uv=(u, v),
                )
            )

        indices = []
        if face_count > 0:
            indices = list(struct.unpack_from("<" + "H" * (face_count * 3), data, offset))
        offset += face_count * 3 * 2

        normals: List[Vec3] = []
        for i in range(vert_count):
            normal, offset = _read_vec3(data, offset)
            if apply_model_transform:
                normal = _transform_vector_row(normal, model_matrix)
            normals.append(_normalize(normal))

        if mesh_version >= 0x10000003:
            for _ in range(vert_count):
                _, offset = _read_u32(data, offset)
            for _ in range(vert_count):
                _, offset = _read_u32(data, offset)

        if has_extra:
            offset += vert_count * 8

        offset += 48

        if mesh_version in (0x10000005, A3DLITMESH_CURRENT_VERSION, 0x10000100):
            try:
                end = data.index(b"\0", offset)
                offset = end + 1 + 16 + 16 + 16 + 16 + 4 + 1
            except ValueError:
                offset = len(data)

        for idx, vertex in enumerate(vertices):
            vertex.normal = normals[idx] if idx < len(normals) else (0.0, 0.0, 0.0)

        meshes.append(
            BMDMesh(
                name=name or f"Mesh{len(meshes) + 1}",
                texture=texture,
                vertices=vertices,
                indices=indices,
                material=BMDMaterial(),
            )
        )

    return meshes


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


def _axis_convert_import(v: Vec3) -> Vec3:
    return (v[0], v[2], v[1])


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(value * 255.0 + 0.5)))


def _argb_from_rgba(color: Color) -> int:
    r, g, b, a = color
    return (_clamp_byte(a) << 24) | (_clamp_byte(r) << 16) | (_clamp_byte(g) << 8) | _clamp_byte(b)


def _sanitize_path(path: str) -> str:
    path = (path or "").replace("/", "\\")
    if path.startswith("\\\\"):
        return path
    while path.startswith(".\\"):
        path = path[2:]
    return path


def _get_texture_search_folder(bmd_filepath: str) -> str:
    """
    Determine texture search folder based on BMD file location.
    
    Rules:
    - If BMD is in a 'litmodels' folder: use parent/building/textures
    - Otherwise: use textures folder next to BMD file
    """
    bmd_dir = os.path.dirname(os.path.abspath(bmd_filepath))
    bmd_dir_name = os.path.basename(bmd_dir).lower()
    
    if bmd_dir_name == "litmodels":
        # File is in litmodels, check parent/building/textures
        parent_dir = os.path.dirname(bmd_dir)
        building_textures = os.path.join(parent_dir, "building", "textures")
        if os.path.isdir(building_textures):
            return building_textures
        # Fallback to parent directory if building/textures doesn't exist
        return parent_dir
    else:
        # File is not in litmodels, use textures folder next to it
        textures_dir = os.path.join(bmd_dir, "textures")
        if os.path.isdir(textures_dir):
            return textures_dir
        # Fallback to the BMD directory itself
        return bmd_dir


def _resolve_texture_path(root: str, texture_path: str) -> str:
    texture_path = _sanitize_path(texture_path).lstrip("\\/")
    if not texture_path:
        return ""
    texture_path = texture_path.replace("\\", os.sep)
    
    # If the path contains "building\textures" or "building/textures", 
    # extract everything after it (e.g., "Building\textures\g\7ac.dds" -> "g\7ac.dds")
    path_lower = texture_path.lower()
    building_textures_pos = path_lower.find(f"building{os.sep}textures")
    if building_textures_pos != -1:
        # Found "building\textures" in the path, get everything after it
        after_building_textures = texture_path[building_textures_pos + len(f"building{os.sep}textures"):].lstrip(os.sep + "/\\")
        texture_path = after_building_textures
    
    if os.path.isabs(texture_path):
        return os.path.normpath(texture_path)

    candidate = os.path.normpath(os.path.join(root, texture_path)) if root else os.path.normpath(texture_path)
    if os.path.exists(candidate):
        return candidate

    if root:
        base_name = os.path.basename(texture_path)
        for dirpath, _, filenames in os.walk(root):
            if base_name in filenames:
                return os.path.normpath(os.path.join(dirpath, base_name))
    return candidate


def _safe_name(name: str, fallback: str) -> str:
    name = (name or "").strip()
    return name if name else fallback


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
        f.write(AFILE_BINARY_HEAD)
        f.write(struct.pack("<I", A3DLITMODEL_VERSION))
        _write_vec3(f, scale)
        _write_vec3(f, direction)
        _write_vec3(f, up)
        _write_vec3(f, position)
        f.write(struct.pack("<i", len(meshes_to_write)))

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

        if settings.write_zero_hull:
            f.write(struct.pack("<i", 0))


def _round_key(values: Iterable[float]) -> Tuple[float, ...]:
    return tuple(round(float(v), 7) for v in values)


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
                    if key not in lookup:
                        lookup[key] = len(vertices)
                        vertices.append(BMDVertex(pos=pos, normal=normal, diffuse=diffuse, day_color=day, night_color=night, uv=(u, v)))
                    indices.append(lookup[key])

            for group in groups.values():
                vertices = group["vertices"]  # type: ignore[assignment]
                indices = group["indices"]  # type: ignore[assignment]
                if vertices and indices:
                    result.append(
                        BMDMesh(
                            name=str(group["name"]),
                            texture=_sanitize_path(str(group["texture"])),
                            vertices=list(vertices),
                            indices=list(indices),
                            material=group["material"],  # type: ignore[arg-type]
                        )
                    )
        finally:
            eval_obj.to_mesh_clear()

    return result


def import_bmd(context, filepath: str, settings: BMDExportSettings) -> Dict[str, int]:
    if bpy is None:
        raise RuntimeError("Blender Python API is not available")

    from mathutils import Vector

    meshes = parse_bmd_meshes(filepath)
    imported_meshes = 0
    imported_vertices = 0
    imported_faces = 0

    collection = getattr(context, "collection", None) or getattr(context.scene, "collection", None)
    if collection is None:
        collection = context.scene.collection

    # Determine texture search folder
    texture_root = os.path.abspath(settings.texture_search_folder) if settings.texture_search_folder else ""
    if not texture_root:
        prefs = get_addon_preferences(context)
        if prefs is not None and prefs.texture_search_folder:
            texture_root = os.path.abspath(prefs.texture_search_folder)
    
    # If still no texture_root, auto-determine based on BMD file location
    if not texture_root:
        texture_root = _get_texture_search_folder(filepath)

    for mesh_data in meshes:
        mesh_name = _safe_name(mesh_data.name, "BMDMesh")
        blender_mesh = bpy.data.meshes.new(mesh_name)

        vertices = [_axis_convert_import(v.pos) for v in mesh_data.vertices]
        faces = [
            (mesh_data.indices[i], mesh_data.indices[i + 2], mesh_data.indices[i + 1])
            for i in range(0, len(mesh_data.indices), 3)
        ]

        blender_mesh.from_pydata(vertices, [], faces)
        blender_mesh.update(calc_edges=True)

        if mesh_data.vertices and any(v.uv != (0.0, 0.0) for v in mesh_data.vertices):
            uv_layer = blender_mesh.uv_layers.new(name="UVMap")
            for loop in blender_mesh.loops:
                uv_layer.data[loop.index].uv = mesh_data.vertices[loop.vertex_index].uv

        if mesh_data.vertices and any(_vec_len(v.normal) > 1e-6 for v in mesh_data.vertices):
            if hasattr(blender_mesh, "use_auto_smooth"):
                blender_mesh.use_auto_smooth = True
            loop_normals = [
                Vector(_axis_convert_import(mesh_data.vertices[loop.vertex_index].normal)).normalized()
                for loop in blender_mesh.loops
            ]
            if hasattr(blender_mesh, "normals_split_custom_set"):
                blender_mesh.normals_split_custom_set(loop_normals)
            if hasattr(blender_mesh, "calc_normals_split"):
                blender_mesh.calc_normals_split()

        obj = bpy.data.objects.new(mesh_name, blender_mesh)
        collection.objects.link(obj)

        if mesh_data.texture:
            material_name = _path_filename(mesh_data.texture) or f"{mesh_name}_mat"
            material = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
            material.use_nodes = True
            nodes = material.node_tree.nodes
            links = material.node_tree.links
            bsdf = nodes.get("Principled BSDF") or nodes.new("ShaderNodeBsdfPrincipled")
            tex_node = nodes.new("ShaderNodeTexImage")
            
            # Store the texture path exactly as specified in the BMD file
            tex_node.label = mesh_data.texture
            
            # Try to load the texture from the search folder if specified
            if texture_root:
                texture_path = _resolve_texture_path(texture_root, mesh_data.texture)
                if os.path.exists(texture_path):
                    try:
                        image = bpy.data.images.load(texture_path, check_existing=True)
                        tex_node.image = image
                    except Exception:
                        pass
            
            tex_node.location = (-300, 300)
            bsdf.location = (0, 300)
            links.new(tex_node.outputs.get("Color"), bsdf.inputs.get("Base Color"))
            obj.data.materials.append(material)

        imported_meshes += 1
        imported_vertices += len(vertices)
        imported_faces += len(faces)

    return {
        "meshes": imported_meshes,
        "vertices": imported_vertices,
        "faces": imported_faces,
    }


def export_bmd(context, filepath: str, settings: BMDExportSettings) -> Dict[str, int]:
    reference = read_reference_defaults(settings.reference_path)
    meshes = collect_scene_meshes(context, settings, reference)
    write_bmd_file(filepath, meshes, settings, reference)
    return {
        "meshes": len(meshes),
        "vertices": sum(len(m.vertices) for m in meshes),
        "faces": sum(m.face_count for m in meshes),
    }


def get_addon_preferences(context) -> object:
    if bpy is None:
        return None
    addon = context.preferences.addons.get(ADDON_NAME)
    return getattr(addon, "preferences", None)


if bpy is not None:

    class ANGELICA2_BMD_Preferences(bpy.types.AddonPreferences):
        bl_idname = ADDON_NAME

        texture_search_folder: StringProperty(
            name="Texture Search Folder",
            description="Default folder used to resolve texture paths on import",
            default="",
            subtype="DIR_PATH",
        )

        def draw(self, context):
            layout = self.layout
            layout.prop(self, "texture_search_folder")


    class EXPORT_SCENE_OT_angelica2_bmd(bpy.types.Operator, ExportHelper):
        bl_idname = "export_scene.angelica2_bmd"
        bl_label = "Export Angelica2 BMD"
        bl_options = {"PRESET"}

        filename_ext = ".bmd"
        filter_glob: StringProperty(default="*.bmd", options={"HIDDEN"})

        use_selection: BoolProperty(
            name="Selected Objects Only",
            default=True,
        )
        apply_modifiers: BoolProperty(
            name="Apply Modifiers",
            default=True,
        )
        reference_path: StringProperty(
            name="Reference BMD",
            subtype="FILE_PATH",
            default=DEFAULT_REFERENCE,
        )
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
                ("IDENTITY", "Identity", "Bake scene positions into vertices and write identity model transform"),
                ("REFERENCE", "Reference", "Use reference model transform and compensate vertices with its inverse"),
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
        texture_folder: StringProperty(
            name="Texture Folder",
            description="Game-relative folder for exported texture paths; the texture file name is taken from the material",
            default="",
        )
        use_reference_texture: BoolProperty(
            name="Use Reference Texture If Missing",
            default=True,
        )
        use_reference_colors: BoolProperty(
            name="Use Reference Vertex Colors If Missing",
            default=True,
        )
        write_zero_hull: BoolProperty(
            name="Write Zero Hull Tail",
            default=True,
        )

        def draw(self, context):
            layout = self.layout
            layout.prop(self, "use_selection")
            layout.prop(self, "apply_modifiers")
            layout.prop(self, "reference_path")
            layout.prop(self, "mesh_version")
            layout.prop(self, "transform_mode")
            layout.prop(self, "axis_mode")
            layout.prop(self, "flip_winding")
            layout.prop(self, "flip_v")
            layout.prop(self, "texture_folder")
            layout.prop(self, "use_reference_texture")
            layout.prop(self, "use_reference_colors")
            layout.prop(self, "write_zero_hull")

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
            )
            try:
                stats = export_bmd(context, self.filepath, settings)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

            self.report(
                {"INFO"},
                f"Exported {stats['meshes']} BMD meshes, {stats['vertices']} verts, {stats['faces']} faces",
            )
            return {"FINISHED"}


    class IMPORT_SCENE_OT_angelica2_bmd(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.angelica2_bmd"
        bl_label = "Import Angelica2 BMD"
        bl_options = {"PRESET"}

        filename_ext = ".bmd"
        filter_glob: StringProperty(default="*.bmd", options={"HIDDEN"})

        texture_search_folder: StringProperty(
            name="Texture Search Folder",
            description="Base folder used to resolve texture paths from BMD mesh texture references",
            default="",
            subtype="DIR_PATH",
        )

        def invoke(self, context, event):
            prefs = get_addon_preferences(context)
            if prefs is not None:
                self.texture_search_folder = prefs.texture_search_folder
            return super().invoke(context, event)

        def draw(self, context):
            layout = self.layout
            layout.prop(self, "texture_search_folder")

        def execute(self, context):
            prefs = get_addon_preferences(context)
            if prefs is not None:
                prefs.texture_search_folder = self.texture_search_folder

            settings = BMDExportSettings(
                texture_search_folder=bpy.path.abspath(self.texture_search_folder) if self.texture_search_folder else "",
            )
            try:
                stats = import_bmd(context, self.filepath, settings)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

            self.report(
                {"INFO"},
                f"Imported {stats['meshes']} BMD meshes, {stats['vertices']} verts, {stats['faces']} faces",
            )
            return {"FINISHED"}


    def _menu_export(self, context):
        self.layout.operator(EXPORT_SCENE_OT_angelica2_bmd.bl_idname, text="Angelica2 BMD (.bmd)")

    def _menu_import(self, context):
        self.layout.operator(IMPORT_SCENE_OT_angelica2_bmd.bl_idname, text="Angelica2 BMD (.bmd)")


    def register():
        bpy.utils.register_class(ANGELICA2_BMD_Preferences)
        bpy.utils.register_class(EXPORT_SCENE_OT_angelica2_bmd)
        bpy.utils.register_class(IMPORT_SCENE_OT_angelica2_bmd)
        bpy.types.TOPBAR_MT_file_export.append(_menu_export)
        bpy.types.TOPBAR_MT_file_import.append(_menu_import)


    def unregister():
        bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
        bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
        bpy.utils.unregister_class(IMPORT_SCENE_OT_angelica2_bmd)
        bpy.utils.unregister_class(EXPORT_SCENE_OT_angelica2_bmd)
        bpy.utils.unregister_class(ANGELICA2_BMD_Preferences)


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[-1] if len(sys.argv) > 1 else DEFAULT_REFERENCE
    print(json.dumps(parse_bmd_summary(target), indent=2, default=lambda value: value.hex() if isinstance(value, bytes) else value))
