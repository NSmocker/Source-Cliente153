"""
BMD File Analyzer GUI - DearPyGui application for analyzing BMD (Angelica2 Engine) files.
Displays structured information about BMD file contents.
"""

import struct
import os
import dearpygui.dearpygui as dpg


# --- BMD Parsing Logic ---

class BMDVertex:
    def __init__(self, pos, diffuse, u, v):
        self.pos = pos
        self.diffuse = diffuse
        self.u = u
        self.v = v


class BMDMaterial:
    def __init__(self):
        self.name = ""
        self.ambient = (1.0, 1.0, 1.0, 1.0)
        self.diffuse = (1.0, 1.0, 1.0, 1.0)
        self.emissive = (0.0, 0.0, 0.0, 0.0)
        self.specular = (0.0, 0.0, 0.0, 1.0)
        self.power = 0.0
        self.two_sided = False


class BMDMesh:
    def __init__(self):
        self.version = 0
        self.name = ""
        self.texture = ""
        self.vert_count = 0
        self.face_count = 0
        self.has_extra_colors = False
        self.vertices = []
        self.indices = []
        self.normals = []
        self.day_colors = []
        self.night_colors = []
        self.day_colors_extra = []
        self.night_colors_extra = []
        self.aabb_center = (0, 0, 0)
        self.aabb_extents = (0, 0, 0)
        self.aabb_mins = (0, 0, 0)
        self.aabb_maxs = (0, 0, 0)
        self.material = None
        self.lm_coords = []


class BMDCollision:
    def __init__(self):
        self.num_hull = 0
        self.hull_mesh_lists = []
        self.collide_only = False


class BMDModel:
    def __init__(self):
        self.file_size = 0
        self.is_brush_building = False
        self.brush_version = 0
        self.collide_only = False
        self.magic = ""
        self.model_version = 0
        self.scale = (0, 0, 0)
        self.direction = (0, 0, 0)
        self.up = (0, 0, 0)
        self.position = (0, 0, 0)
        self.mesh_count = 0
        self.meshes = []
        self.lightmap_name = ""
        self.night_lightmap = ""
        self.collision = None
        self.model_data_size = 0
        self.remaining_after_model = 0


def read_u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def read_i32(data, offset):
    return struct.unpack_from("<i", data, offset)[0]


def read_u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def read_f32(data, offset):
    return struct.unpack_from("<f", data, offset)[0]


def read_vec3(data, offset):
    return struct.unpack_from("<fff", data, offset)


def read_color4f(data, offset):
    return struct.unpack_from("<ffff", data, offset)


def decode_string(raw_bytes):
    null_pos = raw_bytes.find(b"\0")
    if null_pos >= 0:
        raw_bytes = raw_bytes[:null_pos]
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw_bytes.decode("latin-1", errors="replace")


def argb_to_tuple(color_u32):
    a = (color_u32 >> 24) & 0xFF
    r = (color_u32 >> 16) & 0xFF
    g = (color_u32 >> 8) & 0xFF
    b = color_u32 & 0xFF
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def parse_bmd(file_path):
    model = BMDModel()
    with open(file_path, "rb") as f:
        data = f.read()
    model.file_size = len(data)

    offset = 0

    # Check for Brush Building prefix
    if len(data) >= 4:
        first_dword = read_u32(data, 0)
        if first_dword == 0x80000001:
            model.is_brush_building = True
            model.brush_version = first_dword
            offset = 4
            if offset < len(data):
                model.collide_only = bool(data[offset])
                offset += 1

    # Read magic
    if offset + 4 <= len(data):
        model.magic = data[offset:offset + 4].decode("ascii", errors="replace")
        offset += 4
    else:
        model.magic = "N/A"

    # Read model version
    if offset + 4 <= len(data):
        model.model_version = read_u32(data, offset)
        offset += 4

    # Read transforms
    if offset + 48 <= len(data):
        model.scale = read_vec3(data, offset)
        offset += 12
        model.direction = read_vec3(data, offset)
        offset += 12
        model.up = read_vec3(data, offset)
        offset += 12
        model.position = read_vec3(data, offset)
        offset += 12

    # Read mesh count
    if offset + 4 <= len(data):
        model.mesh_count = read_i32(data, offset)
        offset += 4

    # Clamp mesh count to reasonable range
    if model.mesh_count < 0 or model.mesh_count > 10000:
        model.mesh_count = 0

    # Parse meshes
    for i in range(model.mesh_count):
        mesh = BMDMesh()
        mesh_start = offset

        # Version
        if offset + 4 > len(data):
            break
        mesh.version = read_u32(data, offset)
        offset += 4

        # Name (64 bytes)
        if offset + 64 > len(data):
            break
        mesh.name = decode_string(data[offset:offset + 64])
        offset += 64

        # Texture (256 bytes)
        if offset + 256 > len(data):
            break
        mesh.texture = decode_string(data[offset:offset + 256])
        offset += 256

        # Vertex and face count
        if offset + 8 > len(data):
            break
        mesh.vert_count = read_i32(data, offset)
        offset += 4
        mesh.face_count = read_i32(data, offset)
        offset += 4

        # Extra colors flag for v6
        if mesh.version == 0x10000006:
            if offset >= len(data):
                break
            mesh.has_extra_colors = bool(data[offset])
            offset += 1

        # Skip vertex data (24 bytes each)
        vert_data_size = mesh.vert_count * 24
        if offset + vert_data_size > len(data):
            break
        offset += vert_data_size

        # Skip indices (2 bytes each, face_count * 3)
        indices_size = mesh.face_count * 3 * 2
        if offset + indices_size > len(data):
            break
        offset += indices_size

        # Skip normals (12 bytes each)
        normals_size = mesh.vert_count * 12
        if offset + normals_size > len(data):
            break
        offset += normals_size

        # Day/night colors
        if mesh.version >= 0x10000003:
            color_size = mesh.vert_count * 4
            if offset + color_size * 2 > len(data):
                break
            offset += color_size  # day
            offset += color_size  # night

        # Extra colors
        if mesh.version == 0x10000006 and mesh.has_extra_colors:
            extra_size = mesh.vert_count * 4 * 2
            if offset + extra_size > len(data):
                break
            offset += extra_size

        # AABB (48 bytes)
        if offset + 48 > len(data):
            break
        mesh.aabb_center = read_vec3(data, offset)
        offset += 12
        mesh.aabb_extents = read_vec3(data, offset)
        offset += 12
        mesh.aabb_mins = read_vec3(data, offset)
        offset += 12
        mesh.aabb_maxs = read_vec3(data, offset)
        offset += 12

        # Material
        if mesh.version >= 0x10000005 and offset < len(data):
            mat = BMDMaterial()
            # Material name (C-string)
            null_pos = data.find(b"\0", offset)
            if null_pos == -1:
                null_pos = len(data)
            mat.name = decode_string(data[offset:null_pos])
            if mat.name.startswith("MATERIAL: "):
                mat.name = mat.name[10:]
            offset = null_pos + 1

            # 4 color values (4 floats each = 16 bytes each)
            if offset + 64 <= len(data):
                mat.ambient = read_color4f(data, offset)
                offset += 16
                mat.diffuse = read_color4f(data, offset)
                offset += 16
                mat.emissive = read_color4f(data, offset)
                offset += 16
                mat.specular = read_color4f(data, offset)
                offset += 16

            # Power (float)
            if offset + 4 <= len(data):
                mat.power = read_f32(data, offset)
                offset += 4

            # Two sided (bool)
            if offset < len(data):
                mat.two_sided = bool(data[offset])
                offset += 1

            mesh.material = mat

        model.meshes.append(mesh)

    model.model_data_size = offset

    # LightMap names
    if model.model_version >= 0x10000100 and offset + 256 <= len(data):
        model.lightmap_name = decode_string(data[offset:offset + 256])
        offset += 256

    if model.model_version >= 0x10000101 and offset + 260 <= len(data):
        model.night_lightmap = decode_string(data[offset:offset + 260])
        offset += 260

    model.remaining_after_model = len(data) - offset

    # Check for collision data
    if model.remaining_after_model >= 4:
        potential_num_hull = read_i32(data, offset)
        if 0 < potential_num_hull < 10000:
            collision = BMDCollision()
            collision.num_hull = potential_num_hull
            offset += 4

            # Hull mesh list
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
                collision.hull_mesh_lists.append(mesh_ids)

            model.collision = collision

    return model


# --- GUI ---

MODEL_VERSIONS = {
    0x10000001: "Model v1 (old)",
    0x10000002: "Model v2 (base)",
    0x10000100: "LightMap v1",
    0x10000101: "LightMap v2",
}

MESH_VERSIONS = {
    0x10000001: "Mesh v1 (deprecated)",
    0x10000002: "Mesh v2 (old, no day/night)",
    0x10000003: "Mesh v3 (day/night colors)",
    0x10000004: "Mesh v4 (new vertex format)",
    0x10000005: "Mesh v5 (materials)",
    0x10000006: "Mesh v6 (extra colors)",
    0x10000100: "Mesh LM (LightMap)",
}


def vec3_str(v):
    return f"({v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f})"


def color_f_str(c):
    return f"({c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}, {c[3]:.3f})"


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def build_analysis_window(model, file_path):
    """Build the analysis UI inside the existing window."""
    # Clear previous content
    children = dpg.get_item_children("analysis_group", 1)
    if children:
        for child in children:
            dpg.delete_item(child)

    with dpg.group(parent="analysis_group"):
        # --- File Info ---
        dpg.add_text(f"File: {os.path.basename(file_path)}")
        dpg.add_text(f"Size: {format_size(model.file_size)} ({model.file_size:,} bytes)")
        dpg.add_separator()

        # --- File Type ---
        dpg.add_text("FILE TYPE", color=(108, 255, 160))
        if model.is_brush_building:
            dpg.add_text(f"  Type: Brush Building (collision data present)")
            dpg.add_text(f"  Brush Version: 0x{model.brush_version:08X}")
            dpg.add_text(f"  Collide Only: {model.collide_only}")
        else:
            dpg.add_text(f"  Type: Standard BMD")
        dpg.add_separator()

        # --- Model Header ---
        dpg.add_text("MODEL HEADER", color=(108, 140, 255))
        dpg.add_text(f"  Magic: {model.magic}")
        ver_desc = MODEL_VERSIONS.get(model.model_version, f"Unknown (0x{model.model_version:08X})")
        dpg.add_text(f"  Version: 0x{model.model_version:08X} - {ver_desc}")
        dpg.add_separator()

        # --- Transform ---
        dpg.add_text("TRANSFORM", color=(108, 140, 255))
        dpg.add_text(f"  Scale:     {vec3_str(model.scale)}")
        dpg.add_text(f"  Direction: {vec3_str(model.direction)}")
        dpg.add_text(f"  Up:        {vec3_str(model.up)}")
        dpg.add_text(f"  Position:  {vec3_str(model.position)}")
        dpg.add_separator()

        # --- Meshes ---
        dpg.add_text(f"MESHES ({model.mesh_count})", color=(108, 140, 255))

        for idx, mesh in enumerate(model.meshes):
            ver_label = MESH_VERSIONS.get(mesh.version, f"0x{mesh.version:08X}")
            header = f"  [{idx}] {mesh.name}"
            dpg.add_text(header, color=(255, 200, 108))

            dpg.add_text(f"Version:     0x{mesh.version:08X} ({ver_label})")
            dpg.add_text(f"Texture:     {mesh.texture if mesh.texture else '(none)'}")
            dpg.add_text(f"Vertices:    {mesh.vert_count}")
            dpg.add_text(f"Faces:       {mesh.face_count}")

            if mesh.version == 0x10000006:
                dpg.add_text(f"ExtraColors: {mesh.has_extra_colors}")

            # AABB
            dpg.add_text(f"AABB Center:  {vec3_str(mesh.aabb_center)}")
            dpg.add_text(f"AABB Extents: {vec3_str(mesh.aabb_extents)}")
            dpg.add_text(f"AABB Mins:    {vec3_str(mesh.aabb_mins)}")
            dpg.add_text(f"AABB Maxs:    {vec3_str(mesh.aabb_maxs)}")

            # Material
            if mesh.material:
                mat = mesh.material
                dpg.add_text(f"Material:     {mat.name if mat.name else '(unnamed)'}", color=(255, 108, 140))
                dpg.add_text(f"  Ambient:  {color_f_str(mat.ambient)}")
                dpg.add_text(f"  Diffuse:  {color_f_str(mat.diffuse)}")
                dpg.add_text(f"  Emissive: {color_f_str(mat.emissive)}")
                dpg.add_text(f"  Specular: {color_f_str(mat.specular)}")
                dpg.add_text(f"  Power:    {mat.power:.2f}")
                dpg.add_text(f"  TwoSided: {mat.two_sided}")

            dpg.add_spacer(height=4)

        # --- LightMap ---
        if model.model_version >= 0x10000100:
            dpg.add_separator()
            dpg.add_text("LIGHTMAP", color=(108, 140, 255))
            dpg.add_text(f"  Day LightMap:   {model.lightmap_name if model.lightmap_name else '(none)'}")
            if model.model_version >= 0x10000101:
                dpg.add_text(f"  Night LightMap: {model.night_lightmap if model.night_lightmap else '(none)'}")

        # --- Collision ---
        if model.collision:
            dpg.add_separator()
            dpg.add_text("COLLISION DATA", color=(255, 108, 140))
            dpg.add_text(f"  Hull Count: {model.collision.num_hull}")
            for h_idx, hull_meshes in enumerate(model.collision.hull_mesh_lists):
                mesh_names = []
                for mid in hull_meshes:
                    if 0 <= mid < len(model.meshes):
                        mesh_names.append(f"{mid}:{model.meshes[mid].name}")
                    else:
                        mesh_names.append(f"{mid}:???")
                dpg.add_text(f"  Hull {h_idx}: {hull_meshes} meshes -> [{', '.join(mesh_names)}]")

        # --- Summary ---
        dpg.add_separator()
        dpg.add_text("SUMMARY", color=(108, 255, 160))

        total_verts = sum(m.vert_count for m in model.meshes)
        total_faces = sum(m.face_count for m in model.meshes)
        total_with_material = sum(1 for m in model.meshes if m.material)
        total_with_lm = sum(1 for m in model.meshes if m.version == 0x10000100)

        dpg.add_text(f"  Total Vertices:    {total_verts:,}")
        dpg.add_text(f"  Total Faces:       {total_faces:,}")
        dpg.add_text(f"  Meshes with Material: {total_with_material}")
        if model.model_version >= 0x10000100:
            dpg.add_text(f"  Meshes with LightMap: {total_with_lm}")
        dpg.add_text(f"  Model Data Size:   {format_size(model.model_data_size)}")
        if model.remaining_after_model > 0:
            dpg.add_text(f"  Extra Data After:  {format_size(model.remaining_after_model)} (collision?)")
        if model.collision:
            dpg.add_text(f"  Collision Hulls:   {model.collision.num_hull}")


def main():
    dpg.create_context()

    # Theme
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (15, 17, 23))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (26, 29, 39))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (30, 33, 45))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (224, 224, 232))
            dpg.add_theme_color(dpg.mvThemeCol_Separator, (42, 45, 58))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (20, 22, 30))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (25, 28, 38))
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)

    dpg.bind_theme(global_theme)

    # File dialog
    with dpg.file_dialog(directory_selector=False, show=False, callback=open_file_callback,
                         id="file_dialog", width=700, height=400, modal=True):
        dpg.add_file_extension(".bmd", color=(108, 140, 255))
        dpg.add_file_extension(".lmd", color=(108, 140, 255))
        dpg.add_file_extension(".*")

    # Main window
    with dpg.window(tag="main_window", label="BMD File Analyzer", width=900, height=700,
                     on_close=lambda: dpg.stop_dearpygui()):
        with dpg.group():
            dpg.add_text("BMD File Analyzer - Angelica2 Engine", color=(108, 140, 255))
            dpg.add_text("Select a .bmd file to analyze its structure and contents.", color=(136, 136, 152))
            dpg.add_spacer(height=8)

            with dpg.group(horizontal=True):
                dpg.add_button(label="Open BMD File", callback=lambda: dpg.show_item("file_dialog"),
                               width=180, height=35)
                dpg.add_button(label="withCollision.bmd",
                               callback=lambda: quick_load(os.path.join(r"B:\Git\Source-Cliente153\bmd editor", "withCollision.bmd")),
                               width=180, height=35)
                dpg.add_button(label="withoutCollisionTest.bmd",
                               callback=lambda: quick_load(os.path.join(r"B:\Git\Source-Cliente153\bmd editor", "withoutCollisionTest.bmd")),
                               width=230, height=35)

            dpg.add_spacer(height=8)
            dpg.add_separator()
            dpg.add_spacer(height=4)

            with dpg.child_window(tag="analysis_group", autosize_x=True, autosize_y=True):
                dpg.add_text("No file loaded. Click 'Open BMD File' to begin.",
                             color=(136, 136, 152))

    dpg.create_viewport(title="BMD Analyzer", width=920, height=720)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    dpg.start_dearpygui()
    dpg.destroy_context()


def open_file_callback(sender, app_data):
    file_path = app_data["file_path_name"]
    if file_path and os.path.isfile(file_path):
        try:
            model = parse_bmd(file_path)
            build_analysis_window(model, file_path)
        except Exception as e:
            children = dpg.get_item_children("analysis_group", 1)
            if children:
                for child in children:
                    dpg.delete_item(child)
            with dpg.group(parent="analysis_group"):
                dpg.add_text(f"Error parsing file: {e}", color=(255, 108, 108))


def quick_load(file_path):
    if not os.path.isfile(file_path):
        return
    try:
        model = parse_bmd(file_path)
        build_analysis_window(model, file_path)
    except Exception as e:
        children = dpg.get_item_children("analysis_group", 1)
        if children:
            for child in children:
                dpg.delete_item(child)
        with dpg.group(parent="analysis_group"):
            dpg.add_text(f"Error parsing file: {e}", color=(255, 108, 108))


if __name__ == "__main__":
    main()
