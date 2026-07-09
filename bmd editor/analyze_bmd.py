"""
BMD File Analyzer - Compare files with and without collision
"""

import struct
import os

def hex_dump(data: bytes, offset: int, length: int) -> str:
    """Create hex dump of data"""
    lines = []
    for i in range(0, length, 16):
        chunk = data[offset + i:offset + i + 16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset + i:08X}: {hex_str:<48s} {ascii_str}")
    return "\n".join(lines)


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def read_vec3(data: bytes, offset: int):
    return struct.unpack_from("<fff", data, offset)


def analyze_bmd(file_path: str):
    """Analyze BMD file structure"""
    print(f"\n{'='*80}")
    print(f"FILE: {os.path.basename(file_path)}")
    print(f"SIZE: {os.path.getsize(file_path)} bytes")
    print(f"{'='*80}")

    with open(file_path, "rb") as f:
        data = f.read()

    offset = 0

    # Check first bytes
    print(f"\n--- FIRST 64 BYTES ---")
    print(hex_dump(data, 0, min(64, len(data))))

    # Read magic
    magic = data[:4]
    print(f"\nMagic: {magic} ({' '.join(f'{b:02X}' for b in magic)})")

    if magic == b"MOXB":
        print("Standard BMD file (MOXB)")
        offset = 4
    elif magic == b"MOXT":
        print("Text MOX file (MOXT)")
        offset = 4
    else:
        # Check if it's a Brush Building
        first_dword = read_u32(data, 0)
        if first_dword == 0x80000001:
            print(f"BRUSH BUILDING detected! Version: 0x{first_dword:08X}")
            offset = 4
            collide_only = data[offset]
            offset += 1
            print(f"CollideOnly: {collide_only}")
        else:
            print(f"Unknown header: 0x{first_dword:08X}")
            offset = 0

    # Read model version
    model_version = read_u32(data, offset)
    print(f"\nModel Version: 0x{model_version:08X}")
    offset += 4

    # Read transforms
    scale = read_vec3(data, offset)
    offset += 12
    direction = read_vec3(data, offset)
    offset += 12
    up = read_vec3(data, offset)
    offset += 12
    position = read_vec3(data, offset)
    offset += 12

    print(f"Scale: {scale}")
    print(f"Direction: {direction}")
    print(f"Up: {up}")
    print(f"Position: {position}")

    # Read mesh count
    mesh_count = read_i32(data, offset)
    offset += 4
    print(f"\nMesh Count: {mesh_count}")

    # Analyze each mesh
    for i in range(mesh_count):
        print(f"\n--- MESH {i} ---")
        mesh_start = offset

        mesh_version = read_u32(data, offset)
        offset += 4
        print(f"  Version: 0x{mesh_version:08X}")

        # Read name (64 bytes)
        name_raw = data[offset:offset+64]
        name = name_raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        offset += 64
        print(f"  Name: {name}")

        # Read texture (256 bytes)
        tex_raw = data[offset:offset+256]
        texture = tex_raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        offset += 256
        print(f"  Texture: {texture}")

        # Vertex and face count
        vert_count = read_i32(data, offset)
        offset += 4
        face_count = read_i32(data, offset)
        offset += 4
        print(f"  Vertices: {vert_count}")
        print(f"  Faces: {face_count}")

        # Extra colors flag for v6
        has_extra = False
        if mesh_version == 0x10000006:
            has_extra = bool(data[offset])
            offset += 1
            print(f"  HasExtraColors: {has_extra}")

        # Calculate vertex data size
        vertex_size = 24  # pos(12) + diffuse(4) + uv(8)
        vertices_size = vert_count * vertex_size
        indices_size = face_count * 3 * 2  # uint16 indices
        normals_size = vert_count * 12

        # Skip vertices
        offset += vertices_size

        # Skip indices
        offset += indices_size

        # Skip normals
        offset += normals_size

        # Skip day/night colors if version >= 0x10000003
        if mesh_version >= 0x10000003:
            offset += vert_count * 4  # day colors
            offset += vert_count * 4  # night colors

        # Skip extra colors
        if mesh_version == 0x10000006 and has_extra:
            offset += vert_count * 4  # day extra
            offset += vert_count * 4  # night extra

        # Skip AABB (48 bytes)
        aabb_center = read_vec3(data, offset)
        offset += 12
        aabb_extents = read_vec3(data, offset)
        offset += 12
        aabb_mins = read_vec3(data, offset)
        offset += 12
        aabb_maxs = read_vec3(data, offset)
        offset += 12
        print(f"  AABB Center: {aabb_center}")
        print(f"  AABB Extents: {aabb_extents}")

        # Material if version >= 0x10000005
        if mesh_version >= 0x10000005:
            # Read material name (cstring)
            null_pos = data.index(b"\0", offset)
            mat_name = data[offset:null_pos].decode("utf-8", errors="replace")
            offset = null_pos + 1
            if mat_name.startswith("MATERIAL: "):
                mat_name = mat_name[10:]
            print(f"  Material: {mat_name}")

            # Skip material data (4 colors + power + twosided)
            offset += 16 * 4  # 4 colors
            offset += 4  # power
            offset += 1  # two_sided

        mesh_end = offset
        print(f"  Mesh size: {mesh_end - mesh_start} bytes")

    # LightMap names
    if model_version >= 0x10000100:
        lm_name = data[offset:offset+256].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        offset += 256
        print(f"\nLightMap Name: {lm_name}")

    if model_version >= 0x10000101:
        night_lm = data[offset:offset+260].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        offset += 260
        print(f"Night LightMap: {night_lm}")

    # Now check what's after the model
    remaining = len(data) - offset
    print(f"\n--- AFTER MODEL DATA ---")
    print(f"Current offset: {offset}")
    print(f"Remaining bytes: {remaining}")

    if remaining > 0:
        print(f"\n--- REMAINING DATA (first 256 bytes) ---")
        print(hex_dump(data, offset, min(256, remaining)))

        # Check if there's collision data
        if remaining >= 4:
            potential_num_hull = read_i32(data, offset)
            print(f"\nPotential num_hull value: {potential_num_hull}")

            if 0 < potential_num_hull < 1000:
                print(f"Looks like collision data! ({potential_num_hull} hulls)")
                offset += 4

                # Try to read hull mesh list
                print(f"\n--- HULL MESH LIST ---")
                for h in range(potential_num_hull):
                    if offset + 4 > len(data):
                        break
                    num_mesh = read_i32(data, offset)
                    offset += 4
                    mesh_ids = []
                    for m in range(num_mesh):
                        if offset + 4 > len(data):
                            break
                        mesh_id = read_i32(data, offset)
                        offset += 4
                        mesh_ids.append(mesh_id)
                    print(f"  Hull {h}: {num_mesh} meshes -> {mesh_ids}")

                # Show CD brush data
                print(f"\n--- CD BRUSH DATA (first 128 bytes) ---")
                print(hex_dump(data, offset, min(128, len(data) - offset)))
    else:
        print("No additional data after model.")

    # Final summary
    print(f"\n--- SUMMARY ---")
    print(f"Total file size: {len(data)} bytes")
    print(f"Model ends at: {offset}")
    print(f"Has collision data: {'YES' if remaining > 4 else 'NO'}")

    return offset


if __name__ == "__main__":
    folder = r"B:\Git\Source-Cliente153\bmd editor"

    print("=" * 80)
    print("BMD FILE ANALYZER - Collision Detection")
    print("=" * 80)

    # Analyze both files
    analyze_bmd(os.path.join(folder, "withCollision.bmd"))
    analyze_bmd(os.path.join(folder, "withoutCollision.bmd"))
