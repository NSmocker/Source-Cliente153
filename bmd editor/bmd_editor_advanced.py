"""
BMD Editor Advanced - Angelica2 Engine BMD File Editor
Enhanced version with comprehensive collision editing capabilities.
"""

import dearpygui.dearpygui as dpg
import struct
import os
import sys
import json
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, List, Optional, Tuple, Any
from pathlib import Path

# Import base classes from main editor
from bmd_editor import (
    BMDModel, BMDMesh, BMDVertex, BMDMaterial, CDBrush, HullMeshList,
    BMDParser, BMDWriter, BMDBinaryReader, Vec3, Color4,
    A3DLITMODEL_VERSIONS, A3DLITMESH_VERSIONS, ELBRUSHBUILDING_VERSION
)


class AdvancedBMDEditor:
    """Advanced BMD Editor with collision editing capabilities"""
    
    def __init__(self):
        self.source_model: Optional[BMDModel] = None
        self.target_model: Optional[BMDModel] = None
        self.source_path: str = ""
        self.target_path: str = ""
        
        # UI state
        self.selected_source_mesh_idx: int = 0
        self.selected_target_mesh_idx: int = 0
        self.selected_source_hull_idx: int = 0
        self.selected_target_hull_idx: int = 0
        self.selected_brush_idx: int = 0
        
        # Clipboard for copy/paste
        self.clipboard_brushes: List[CDBrush] = []
        self.clipboard_hull_mesh_list: List[HullMeshList] = []
        self.clipboard_mesh: Optional[BMDMesh] = None
        
        dpg.create_context()
        self._setup_ui()
    
    def _setup_ui(self):
        with dpg.window(tag="main_window"):
            with dpg.menu_bar():
                with dpg.menu(label="File"):
                    dpg.add_menu_item(label="Open Source Model", callback=self._open_source)
                    dpg.add_menu_item(label="Open Target Model", callback=self._open_target)
                    dpg.add_separator()
                    dpg.add_menu_item(label="Save Target", callback=self._save_target)
                    dpg.add_menu_item(label="Save Target As...", callback=self._save_target_as)
                    dpg.add_separator()
                    dpg.add_menu_item(label="Exit", callback=lambda: dpg.stop_dearpygui())
                
                with dpg.menu(label="Edit"):
                    dpg.add_menu_item(label="Copy Collision (All)", callback=self._copy_all_collision)
                    dpg.add_menu_item(label="Copy Selected Hull", callback=self._copy_selected_hull)
                    dpg.add_menu_item(label="Copy All Meshes", callback=self._copy_all_meshes)
                    dpg.add_menu_item(label="Copy Selected Mesh", callback=self._copy_selected_mesh)
                    dpg.add_separator()
                    dpg.add_menu_item(label="Paste Collision", callback=self._paste_collision)
                    dpg.add_menu_item(label="Paste Mesh", callback=self._paste_mesh)
                
                with dpg.menu(label="Collision"):
                    dpg.add_menu_item(label="Add Hull", callback=self._add_hull)
                    dpg.add_menu_item(label="Remove Selected Hull", callback=self._remove_hull)
                    dpg.add_separator()
                    dpg.add_menu_item(label="Clear All Collision", callback=self._clear_collision)
                
                with dpg.menu(label="View"):
                    dpg.add_menu_item(label="Export Collision Info", callback=self._export_collision_info)
                    dpg.add_menu_item(label="Import Collision Info", callback=self._import_collision_info)
                
                with dpg.menu(label="Help"):
                    dpg.add_menu_item(label="About", callback=self._show_about)
                    dpg.add_menu_item(label="BMD Format Info", callback=self._show_format_info)
            
            with dpg.group(horizontal=True):
                # Source panel
                with dpg.child_window(width=400, height=-1, label="Source Model"):
                    dpg.add_text("No model loaded", tag="source_info")
                    dpg.add_separator()

                    dpg.add_text("File Path:")
                    dpg.add_input_text(tag="source_path_input", width=-1, hint="Paste full path to .bmd file here...")
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Load from Path", callback=self._load_source_from_path)
                        dpg.add_button(label="Browse...", callback=self._open_source)
                    dpg.add_separator()

                    # Source meshes
                    dpg.add_text("Meshes:")
                    with dpg.child_window(tag="source_meshes_panel", height=200):
                        dpg.add_text("No meshes loaded")

                    dpg.add_separator()

                    # Source collision hulls
                    dpg.add_text("Collision Hulls:")
                    with dpg.child_window(tag="source_hulls_panel", height=200):
                        dpg.add_text("No collision data")

                # Target panel
                with dpg.child_window(width=400, height=-1, label="Target Model"):
                    dpg.add_text("No model loaded", tag="target_info")
                    dpg.add_separator()

                    dpg.add_text("File Path:")
                    dpg.add_input_text(tag="target_path_input", width=-1, hint="Paste full path to .bmd file here...")
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Load from Path", callback=self._load_target_from_path)
                        dpg.add_button(label="Browse...", callback=self._open_target)
                    dpg.add_separator()

                    # Target meshes
                    dpg.add_text("Meshes:")
                    with dpg.child_window(tag="target_meshes_panel", height=200):
                        dpg.add_text("No meshes loaded")

                    dpg.add_separator()

                    # Target collision hulls
                    dpg.add_text("Collision Hulls:")
                    with dpg.child_window(tag="target_hulls_panel", height=200):
                        dpg.add_text("No collision data")
            
            # Details panel
            with dpg.child_window(tag="details_panel", width=-1, height=300):
                with dpg.group(horizontal=True):
                    # Source details
                    with dpg.child_window(width=-1, height=-1):
                        dpg.add_text("Source Details", tag="source_details_title")
                        dpg.add_separator()
                        with dpg.child_window(tag="source_details_content"):
                            dpg.add_text("Select a mesh or hull to see details")
                    
                    # Target details
                    with dpg.child_window(width=-1, height=-1):
                        dpg.add_text("Target Details", tag="target_details_title")
                        dpg.add_separator()
                        with dpg.child_window(tag="target_details_content"):
                            dpg.add_text("Select a mesh or hull to see details")
    
    def _open_source(self, sender, app_data):
        file_path = self._file_dialog("Open Source BMD", "*.bmd")
        if file_path:
            self._load_model_from_path(file_path, is_source=True)

    def _load_source_from_path(self, sender, app_data):
        file_path = dpg.get_value("source_path_input").strip()
        if not file_path:
            dpg.set_value("source_info", "Error: No path entered!")
            return
        self._load_model_from_path(file_path, is_source=True)

    def _open_target(self, sender, app_data):
        file_path = self._file_dialog("Open Target BMD", "*.bmd")
        if file_path:
            self._load_model_from_path(file_path, is_source=False)

    def _load_target_from_path(self, sender, app_data):
        file_path = dpg.get_value("target_path_input").strip()
        if not file_path:
            dpg.set_value("target_info", "Error: No path entered!")
            return
        self._load_model_from_path(file_path, is_source=False)

    def _load_model_from_path(self, file_path: str, is_source: bool):
        if not os.path.isfile(file_path):
            msg = f"Error: File not found: {file_path}"
            if is_source:
                dpg.set_value("source_info", msg)
            else:
                dpg.set_value("target_info", msg)
            return

        try:
            model = BMDParser.parse(file_path)
            if is_source:
                self.source_model = model
                self.source_path = file_path
                dpg.set_value("source_path_input", file_path)
                self._update_source_panel()
            else:
                self.target_model = model
                self.target_path = file_path
                dpg.set_value("target_path_input", file_path)
                self._update_target_panel()
        except Exception as e:
            msg = f"Error parsing: {str(e)}"
            if is_source:
                dpg.set_value("source_info", msg)
            else:
                dpg.set_value("target_info", msg)

    def _save_target(self, sender, app_data):
        if self.target_model and self.target_path:
            try:
                BMDWriter.write(self.target_model, self.target_path)
                dpg.set_value("target_info", f"Saved: {os.path.basename(self.target_path)}")
            except Exception as e:
                dpg.set_value("target_info", f"Error saving: {str(e)}")
    
    def _save_target_as(self, sender, app_data):
        if self.target_model:
            file_path = self._file_dialog("Save Target BMD", "*.bmd", save=True)
            if file_path:
                try:
                    BMDWriter.write(self.target_model, file_path)
                    self.target_path = file_path
                    dpg.set_value("target_info", f"Saved: {os.path.basename(file_path)}")
                except Exception as e:
                    dpg.set_value("target_info", f"Error saving: {str(e)}")
    
    def _copy_all_collision(self, sender, app_data):
        if not self.source_model or not self.target_model:
            return
        
        if not self.source_model.has_brush_header:
            dpg.set_value("source_info", "Source model has no collision data!")
            return
        
        self.target_model.has_brush_header = True
        self.target_model.collide_only = self.source_model.collide_only
        self.target_model.num_hull = self.source_model.num_hull
        self.target_model.hull_mesh_list = [HullMeshList(mesh_ids=hml.mesh_ids.copy()) 
                                           for hml in self.source_model.hull_mesh_list]
        self.target_model.cd_brushes = [CDBrush(
            planes=[(Vec3(n.x, n.y, n.z), d) for n, d in brush.planes],
            vertices=[Vec3(v.x, v.y, v.z) for v in brush.vertices],
            triangles=brush.triangles.copy(),
            flags=brush.flags
        ) for brush in self.source_model.cd_brushes]
        
        self._update_target_panel()
        dpg.set_value("target_info", "All collision data copied!")
    
    def _copy_selected_hull(self, sender, app_data):
        if not self.source_model or not self.target_model:
            return
        
        if not self.source_model.has_brush_header:
            dpg.set_value("source_info", "Source model has no collision data!")
            return
        
        if self.selected_source_hull_idx >= len(self.source_model.cd_brushes):
            return
        
        # Copy to clipboard
        brush = self.source_model.cd_brushes[self.selected_source_hull_idx]
        self.clipboard_brushes = [CDBrush(
            planes=[(Vec3(n.x, n.y, n.z), d) for n, d in brush.planes],
            vertices=[Vec3(v.x, v.y, v.z) for v in brush.vertices],
            triangles=brush.triangles.copy(),
            flags=brush.flags
        )]
        
        if self.selected_source_hull_idx < len(self.source_model.hull_mesh_list):
            hml = self.source_model.hull_mesh_list[self.selected_source_hull_idx]
            self.clipboard_hull_mesh_list = [HullMeshList(mesh_ids=hml.mesh_ids.copy())]
        
        dpg.set_value("source_details_title", f"Source Hull {self.selected_source_hull_idx} copied to clipboard")
    
    def _copy_selected_mesh(self, sender, app_data):
        if not self.source_model:
            return
        
        if self.selected_source_mesh_idx >= len(self.source_model.meshes):
            return
        
        mesh = self.source_model.meshes[self.selected_source_mesh_idx]
        
        # Deep copy the mesh
        self.clipboard_mesh = BMDMesh(
            name=mesh.name,
            texture=mesh.texture,
            version=mesh.version,
            vertices=[BMDVertex(
                pos=Vec3(v.pos.x, v.pos.y, v.pos.z),
                normal=Vec3(v.normal.x, v.normal.y, v.normal.z),
                diffuse=v.diffuse,
                day_color=v.day_color,
                night_color=v.night_color,
                day_color_extra=v.day_color_extra,
                night_color_extra=v.night_color_extra,
                uv=v.uv,
                lm_uv=v.lm_uv
            ) for v in mesh.vertices],
            indices=mesh.indices.copy(),
            material=BMDMaterial(
                name=mesh.material.name,
                ambient=Color4(mesh.material.ambient.r, mesh.material.ambient.g, 
                              mesh.material.ambient.b, mesh.material.ambient.a),
                diffuse=Color4(mesh.material.diffuse.r, mesh.material.diffuse.g,
                              mesh.material.diffuse.b, mesh.material.diffuse.a),
                emissive=Color4(mesh.material.emissive.r, mesh.material.emissive.g,
                               mesh.material.emissive.b, mesh.material.emissive.a),
                specular=Color4(mesh.material.specular.r, mesh.material.specular.g,
                               mesh.material.specular.b, mesh.material.specular.a),
                power=mesh.material.power,
                two_sided=mesh.material.two_sided
            ),
            has_extra_colors=mesh.has_extra_colors,
            aabb_center=Vec3(mesh.aabb_center.x, mesh.aabb_center.y, mesh.aabb_center.z),
            aabb_extents=Vec3(mesh.aabb_extents.x, mesh.aabb_extents.y, mesh.aabb_extents.z),
            aabb_mins=Vec3(mesh.aabb_mins.x, mesh.aabb_mins.y, mesh.aabb_mins.z),
            aabb_maxs=Vec3(mesh.aabb_maxs.x, mesh.aabb_maxs.y, mesh.aabb_maxs.z)
        )
        
        dpg.set_value("source_details_title", f"Source Mesh '{mesh.name}' copied to clipboard")
    
    def _paste_collision(self, sender, app_data):
        if not self.target_model:
            return
        
        if not self.clipboard_brushes:
            dpg.set_value("target_info", "No collision data in clipboard!")
            return
        
        self.target_model.has_brush_header = True
        self.target_model.num_hull += len(self.clipboard_brushes)
        
        # Add brushes
        for brush in self.clipboard_brushes:
            self.target_model.cd_brushes.append(CDBrush(
                planes=[(Vec3(n.x, n.y, n.z), d) for n, d in brush.planes],
                vertices=[Vec3(v.x, v.y, v.z) for v in brush.vertices],
                triangles=brush.triangles.copy(),
                flags=brush.flags
            ))
        
        # Add hull mesh list entries
        for hml in self.clipboard_hull_mesh_list:
            self.target_model.hull_mesh_list.append(HullMeshList(mesh_ids=hml.mesh_ids.copy()))
        
        self._update_target_panel()
        dpg.set_value("target_info", f"Pasted {len(self.clipboard_brushes)} collision hull(s)")
    
    def _paste_mesh(self, sender, app_data):
        if not self.target_model or not self.clipboard_mesh:
            dpg.set_value("target_info", "No mesh in clipboard!")
            return
        
        # Add mesh to target
        self.target_model.meshes.append(self.clipboard_mesh)
        
        self._update_target_panel()
        dpg.set_value("target_info", f"Pasted mesh '{self.clipboard_mesh.name}'")
    
    def _add_hull(self, sender, app_data):
        if not self.target_model:
            return
        
        self.target_model.has_brush_header = True
        self.target_model.num_hull += 1
        self.target_model.cd_brushes.append(CDBrush())
        self.target_model.hull_mesh_list.append(HullMeshList())
        
        self._update_target_panel()
        dpg.set_value("target_info", "Added new empty hull")
    
    def _remove_hull(self, sender, app_data):
        if not self.target_model or not self.target_model.has_brush_header:
            return
        
        if self.selected_target_hull_idx >= len(self.target_model.cd_brushes):
            return
        
        # Remove hull
        self.target_model.cd_brushes.pop(self.selected_target_hull_idx)
        if self.selected_target_hull_idx < len(self.target_model.hull_mesh_list):
            self.target_model.hull_mesh_list.pop(self.selected_target_hull_idx)
        
        self.target_model.num_hull = len(self.target_model.cd_brushes)
        
        self._update_target_panel()
        dpg.set_value("target_info", f"Removed hull {self.selected_target_hull_idx}")
    
    def _clear_collision(self, sender, app_data):
        if not self.target_model:
            return
        
        self.target_model.has_brush_header = False
        self.target_model.num_hull = 0
        self.target_model.cd_brushes = []
        self.target_model.hull_mesh_list = []
        
        self._update_target_panel()
        dpg.set_value("target_info", "Cleared all collision data")
    
    def _copy_all_meshes(self, sender, app_data):
        if not self.source_model or not self.target_model:
            return
        
        # Deep copy all meshes
        self.target_model.meshes = []
        for mesh in self.source_model.meshes:
            new_mesh = BMDMesh(
                name=mesh.name,
                texture=mesh.texture,
                version=mesh.version,
                vertices=[BMDVertex(
                    pos=Vec3(v.pos.x, v.pos.y, v.pos.z),
                    normal=Vec3(v.normal.x, v.normal.y, v.normal.z),
                    diffuse=v.diffuse,
                    day_color=v.day_color,
                    night_color=v.night_color,
                    day_color_extra=v.day_color_extra,
                    night_color_extra=v.night_color_extra,
                    uv=v.uv,
                    lm_uv=v.lm_uv
                ) for v in mesh.vertices],
                indices=mesh.indices.copy(),
                material=BMDMaterial(
                    name=mesh.material.name,
                    ambient=Color4(mesh.material.ambient.r, mesh.material.ambient.g,
                                  mesh.material.ambient.b, mesh.material.ambient.a),
                    diffuse=Color4(mesh.material.diffuse.r, mesh.material.diffuse.g,
                                  mesh.material.diffuse.b, mesh.material.diffuse.a),
                    emissive=Color4(mesh.material.emissive.r, mesh.material.emissive.g,
                                   mesh.material.emissive.b, mesh.material.emissive.a),
                    specular=Color4(mesh.material.specular.r, mesh.material.specular.g,
                                   mesh.material.specular.b, mesh.material.specular.a),
                    power=mesh.material.power,
                    two_sided=mesh.material.two_sided
                ),
                has_extra_colors=mesh.has_extra_colors,
                aabb_center=Vec3(mesh.aabb_center.x, mesh.aabb_center.y, mesh.aabb_center.z),
                aabb_extents=Vec3(mesh.aabb_extents.x, mesh.aabb_extents.y, mesh.aabb_extents.z),
                aabb_mins=Vec3(mesh.aabb_mins.x, mesh.aabb_mins.y, mesh.aabb_mins.z),
                aabb_maxs=Vec3(mesh.aabb_maxs.x, mesh.aabb_maxs.y, mesh.aabb_maxs.z)
            )
            self.target_model.meshes.append(new_mesh)
        
        self.target_model.model_version = self.source_model.model_version
        
        self._update_target_panel()
        dpg.set_value("target_info", f"Copied {len(self.source_model.meshes)} meshes from source")
    
    def _export_collision_info(self, sender, app_data):
        if not self.target_model or not self.target_model.has_brush_header:
            return
        
        file_path = self._file_dialog("Export Collision Info", "*.json", save=True)
        if file_path:
            collision_info = {
                "num_hull": self.target_model.num_hull,
                "hull_mesh_list": [hml.mesh_ids for hml in self.target_model.hull_mesh_list],
                "brushes": []
            }
            
            for i, brush in enumerate(self.target_model.cd_brushes):
                brush_info = {
                    "index": i,
                    "num_planes": len(brush.planes),
                    "planes": [(list(n.to_tuple()), d) for n, d in brush.planes],
                    "num_vertices": len(brush.vertices),
                    "vertices": [list(v.to_tuple()) for v in brush.vertices],
                    "num_triangles": len(brush.triangles),
                    "triangles": brush.triangles,
                    "flags": brush.flags
                }
                collision_info["brushes"].append(brush_info)
            
            with open(file_path, "w") as f:
                json.dump(collision_info, f, indent=2)
            
            dpg.set_value("target_info", f"Exported collision info to {os.path.basename(file_path)}")
    
    def _import_collision_info(self, sender, app_data):
        if not self.target_model:
            return
        
        file_path = self._file_dialog("Import Collision Info", "*.json")
        if file_path:
            try:
                with open(file_path, "r") as f:
                    collision_info = json.load(f)
                
                self.target_model.has_brush_header = True
                self.target_model.num_hull = collision_info["num_hull"]
                
                # Import hull mesh list
                self.target_model.hull_mesh_list = []
                for mesh_ids in collision_info["hull_mesh_list"]:
                    self.target_model.hull_mesh_list.append(HullMeshList(mesh_ids=mesh_ids))
                
                # Import brushes
                self.target_model.cd_brushes = []
                for brush_info in collision_info["brushes"]:
                    brush = CDBrush()
                    brush.planes = [(Vec3(*n), d) for n, d in brush_info["planes"]]
                    brush.vertices = [Vec3(*v) for v in brush_info["vertices"]]
                    brush.triangles = [tuple(t) for t in brush_info["triangles"]]
                    brush.flags = brush_info["flags"]
                    self.target_model.cd_brushes.append(brush)
                
                self._update_target_panel()
                dpg.set_value("target_info", f"Imported collision from {os.path.basename(file_path)}")
            except Exception as e:
                dpg.set_value("target_info", f"Error importing: {str(e)}")
    
    def _show_about(self, sender, app_data):
        with dpg.window(label="About BMD Editor Advanced", modal=True, width=400, height=200, tag="about_window"):
            dpg.add_text("BMD Editor Advanced v1.0")
            dpg.add_text("Enhanced Angelica2 BMD File Editor")
            dpg.add_text("Built with DearPyGui")
            dpg.add_separator()
            dpg.add_button(label="Close", callback=lambda: dpg.delete_item("about_window"))
    
    def _show_format_info(self, sender, app_data):
        with dpg.window(label="BMD Format Info", modal=True, width=600, height=400, tag="format_window"):
            dpg.add_text("BMD File Format Information")
            dpg.add_separator()
            dpg.add_text("File Magic: MOXB (0x42584F4D)")
            dpg.add_text("Brush Building Version: 0x80000001")
            dpg.add_separator()
            dpg.add_text("Model Versions:")
            for ver, desc in A3DLITMODEL_VERSIONS.items():
                dpg.add_text(f"  0x{ver:08X}: {desc}")
            dpg.add_separator()
            dpg.add_text("Mesh Versions:")
            for ver, desc in A3DLITMESH_VERSIONS.items():
                dpg.add_text(f"  0x{ver:08X}: {desc}")
            dpg.add_separator()
            dpg.add_button(label="Close", callback=lambda: dpg.delete_item("format_window"))
    
    def _file_dialog(self, title: str, file_types: str, save: bool = False) -> Optional[str]:
        with dpg.file_dialog(
            directory_selector=False,
            show=True,
            callback=self._file_dialog_callback,
            tag="file_dialog",
            width=700,
            height=400
        ):
            dpg.add_file_extension(".*")
            dpg.add_file_extension(file_types)
        
        while dpg.is_item_visible("file_dialog"):
            dpg.render_dearpygui()
        
        if hasattr(self, '_selected_file'):
            return self._selected_file
        return None
    
    def _file_dialog_callback(self, sender, app_data):
        if app_data and 'file_path_name' in app_data:
            self._selected_file = app_data['file_path_name']
        else:
            self._selected_file = None
        dpg.delete_item("file_dialog")
    
    def _update_source_panel(self):
        if not self.source_model:
            return
        
        info_text = f"Source: {os.path.basename(self.source_path)}\n"
        info_text += f"Version: {A3DLITMODEL_VERSIONS.get(self.source_model.model_version, 'Unknown')}\n"
        info_text += f"Meshes: {len(self.source_model.meshes)}\n"
        info_text += f"Has Collision: {self.source_model.has_brush_header}\n"
        if self.source_model.has_brush_header:
            info_text += f"Hulls: {self.source_model.num_hull}"
        
        dpg.set_value("source_info", info_text)
        
        # Update mesh list
        dpg.delete_item("source_meshes_panel", children_only=True)
        with dpg.group(parent="source_meshes_panel"):
            for i, mesh in enumerate(self.source_model.meshes):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label=f"{i}: {mesh.name}",
                        callback=lambda s, a, u: self._select_source_mesh(u),
                        user_data=i
                    )
                    dpg.add_text(f"({len(mesh.vertices)}v)")
        
        # Update hull list
        dpg.delete_item("source_hulls_panel", children_only=True)
        if self.source_model.has_brush_header:
            with dpg.group(parent="source_hulls_panel"):
                for i in range(self.source_model.num_hull):
                    brush = self.source_model.cd_brushes[i] if i < len(self.source_model.cd_brushes) else None
                    hml = self.source_model.hull_mesh_list[i] if i < len(self.source_model.hull_mesh_list) else None
                    
                    info = f"Hull {i}"
                    if brush:
                        info += f" ({len(brush.vertices)}v, {len(brush.triangles)}t)"
                    if hml:
                        info += f" meshes:{hml.mesh_ids}"
                    
                    dpg.add_button(
                        label=info,
                        callback=lambda s, a, u: self._select_source_hull(u),
                        user_data=i
                    )
        else:
            with dpg.group(parent="source_hulls_panel"):
                dpg.add_text("No collision data")
    
    def _update_target_panel(self):
        if not self.target_model:
            return
        
        info_text = f"Target: {os.path.basename(self.target_path)}\n"
        info_text += f"Version: {A3DLITMODEL_VERSIONS.get(self.target_model.model_version, 'Unknown')}\n"
        info_text += f"Meshes: {len(self.target_model.meshes)}\n"
        info_text += f"Has Collision: {self.target_model.has_brush_header}\n"
        if self.target_model.has_brush_header:
            info_text += f"Hulls: {self.target_model.num_hull}"
        
        dpg.set_value("target_info", info_text)
        
        # Update mesh list
        dpg.delete_item("target_meshes_panel", children_only=True)
        with dpg.group(parent="target_meshes_panel"):
            for i, mesh in enumerate(self.target_model.meshes):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label=f"{i}: {mesh.name}",
                        callback=lambda s, a, u: self._select_target_mesh(u),
                        user_data=i
                    )
                    dpg.add_text(f"({len(mesh.vertices)}v)")
        
        # Update hull list
        dpg.delete_item("target_hulls_panel", children_only=True)
        if self.target_model.has_brush_header:
            with dpg.group(parent="target_hulls_panel"):
                for i in range(self.target_model.num_hull):
                    brush = self.target_model.cd_brushes[i] if i < len(self.target_model.cd_brushes) else None
                    hml = self.target_model.hull_mesh_list[i] if i < len(self.target_model.hull_mesh_list) else None
                    
                    info = f"Hull {i}"
                    if brush:
                        info += f" ({len(brush.vertices)}v, {len(brush.triangles)}t)"
                    if hml:
                        info += f" meshes:{hml.mesh_ids}"
                    
                    dpg.add_button(
                        label=info,
                        callback=lambda s, a, u: self._select_target_hull(u),
                        user_data=i
                    )
        else:
            with dpg.group(parent="target_hulls_panel"):
                dpg.add_text("No collision data")
    
    def _select_source_mesh(self, mesh_idx: int):
        if not self.source_model or mesh_idx >= len(self.source_model.meshes):
            return
        
        self.selected_source_mesh_idx = mesh_idx
        mesh = self.source_model.meshes[mesh_idx]
        
        dpg.set_value("source_details_title", f"Source Mesh: {mesh.name}")
        dpg.delete_item("source_details_content", children_only=True)
        
        with dpg.group(parent="source_details_content"):
            dpg.add_text(f"Name: {mesh.name}")
            dpg.add_text(f"Texture: {mesh.texture}")
            dpg.add_text(f"Version: 0x{mesh.version:08X} ({A3DLITMESH_VERSIONS.get(mesh.version, 'Unknown')})")
            dpg.add_text(f"Vertices: {len(mesh.vertices)}")
            dpg.add_text(f"Faces: {mesh.face_count}")
            dpg.add_text(f"Has Extra Colors: {mesh.has_extra_colors}")
            
            dpg.add_separator()
            dpg.add_text("AABB:")
            dpg.add_text(f"  Center: ({mesh.aabb_center.x:.3f}, {mesh.aabb_center.y:.3f}, {mesh.aabb_center.z:.3f})")
            dpg.add_text(f"  Extents: ({mesh.aabb_extents.x:.3f}, {mesh.aabb_extents.y:.3f}, {mesh.aabb_extents.z:.3f})")
            
            if mesh.material:
                dpg.add_separator()
                dpg.add_text(f"Material: {mesh.material.name}")
                dpg.add_text(f"  Two Sided: {mesh.material.two_sided}")
                dpg.add_text(f"  Power: {mesh.material.power:.2f}")
    
    def _select_source_hull(self, hull_idx: int):
        if not self.source_model or not self.source_model.has_brush_header:
            return
        
        if hull_idx >= self.source_model.num_hull:
            return
        
        self.selected_source_hull_idx = hull_idx
        
        brush = self.source_model.cd_brushes[hull_idx] if hull_idx < len(self.source_model.cd_brushes) else None
        hml = self.source_model.hull_mesh_list[hull_idx] if hull_idx < len(self.source_model.hull_mesh_list) else None
        
        dpg.set_value("source_details_title", f"Source Hull: {hull_idx}")
        dpg.delete_item("source_details_content", children_only=True)
        
        with dpg.group(parent="source_details_content"):
            if brush:
                dpg.add_text(f"Hull Index: {hull_idx}")
                dpg.add_text(f"Planes: {len(brush.planes)}")
                dpg.add_text(f"Vertices: {len(brush.vertices)}")
                dpg.add_text(f"Triangles: {len(brush.triangles)}")
                dpg.add_text(f"Flags: 0x{brush.flags:08X}")
                
                if hml:
                    dpg.add_separator()
                    dpg.add_text(f"Mesh IDs: {hml.mesh_ids}")
            else:
                dpg.add_text("No brush data available")
    
    def _select_target_mesh(self, mesh_idx: int):
        if not self.target_model or mesh_idx >= len(self.target_model.meshes):
            return
        
        self.selected_target_mesh_idx = mesh_idx
        mesh = self.target_model.meshes[mesh_idx]
        
        dpg.set_value("target_details_title", f"Target Mesh: {mesh.name}")
        dpg.delete_item("target_details_content", children_only=True)
        
        with dpg.group(parent="target_details_content"):
            dpg.add_text(f"Name: {mesh.name}")
            dpg.add_text(f"Texture: {mesh.texture}")
            dpg.add_text(f"Version: 0x{mesh.version:08X} ({A3DLITMESH_VERSIONS.get(mesh.version, 'Unknown')})")
            dpg.add_text(f"Vertices: {len(mesh.vertices)}")
            dpg.add_text(f"Faces: {mesh.face_count}")
            dpg.add_text(f"Has Extra Colors: {mesh.has_extra_colors}")
            
            dpg.add_separator()
            dpg.add_text("AABB:")
            dpg.add_text(f"  Center: ({mesh.aabb_center.x:.3f}, {mesh.aabb_center.y:.3f}, {mesh.aabb_center.z:.3f})")
            dpg.add_text(f"  Extents: ({mesh.aabb_extents.x:.3f}, {mesh.aabb_extents.y:.3f}, {mesh.aabb_extents.z:.3f})")
            
            if mesh.material:
                dpg.add_separator()
                dpg.add_text(f"Material: {mesh.material.name}")
                dpg.add_text(f"  Two Sided: {mesh.material.two_sided}")
                dpg.add_text(f"  Power: {mesh.material.power:.2f}")
    
    def _select_target_hull(self, hull_idx: int):
        if not self.target_model or not self.target_model.has_brush_header:
            return
        
        if hull_idx >= self.target_model.num_hull:
            return
        
        self.selected_target_hull_idx = hull_idx
        
        brush = self.target_model.cd_brushes[hull_idx] if hull_idx < len(self.target_model.cd_brushes) else None
        hml = self.target_model.hull_mesh_list[hull_idx] if hull_idx < len(self.target_model.hull_mesh_list) else None
        
        dpg.set_value("target_details_title", f"Target Hull: {hull_idx}")
        dpg.delete_item("target_details_content", children_only=True)
        
        with dpg.group(parent="target_details_content"):
            if brush:
                dpg.add_text(f"Hull Index: {hull_idx}")
                dpg.add_text(f"Planes: {len(brush.planes)}")
                dpg.add_text(f"Vertices: {len(brush.vertices)}")
                dpg.add_text(f"Triangles: {len(brush.triangles)}")
                dpg.add_text(f"Flags: 0x{brush.flags:08X}")
                
                if hml:
                    dpg.add_separator()
                    dpg.add_text(f"Mesh IDs: {hml.mesh_ids}")
            else:
                dpg.add_text("No brush data available")
    
    def run(self):
        dpg.create_viewport(title="BMD Editor Advanced - Angelica2", width=1400, height=900)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("main_window", True)
        dpg.start_dearpygui()
        dpg.destroy_context()


def main():
    editor = AdvancedBMDEditor()
    editor.run()


if __name__ == "__main__":
    main()
