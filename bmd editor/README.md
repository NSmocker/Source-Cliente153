# BMD Editor

Angelica2 Engine BMD File Editor - A DearPyGui-based application for viewing and editing BMD 3D model files.

## Editors

### V2 Editor (bmd_editor_v2.py) - RECOMMENDED
Each model opens in its own window with full editing:
- **Separate Windows**: Each model in its own editable window
- **Category Tabs**: Header, Meshes, Collision
- **All Fields Editable**: Name, texture, transforms, materials, colors, vertices
- **Material Editing**: Two-sided, power, ambient/diffuse/emissive/specular colors
- **Collision Management**: Add/remove hulls, edit flags
- **Vertex Editor**: Edit individual vertex position, normal, UV, colors

### Basic Editor (bmd_editor.py)
- Load and view BMD files
- Copy collision data between models
- Copy all meshes between models
- View mesh details (vertices, faces, materials, AABB)

### Advanced Editor (bmd_editor_advanced.py)
All features of the basic editor plus:
- **Selective Copy/Copy**: Copy individual hulls or meshes
- **Clipboard Support**: Copy to clipboard and paste
- **Hull Management**: Add/remove collision hulls
- **Collision Import/Export**: Export collision data to JSON
- **Detailed View**: Separate details panels for source and target

## Features

- **Load BMD Files**: Open and view BMD model files
- **View Mesh Details**: See vertices, faces, materials, and AABB information
- **Copy Collision**: Transfer collision data between models
- **Copy All Meshes**: Copy entire mesh data between models
- **Save Changes**: Save edited models back to BMD format
- **Collision Editing**: Add, remove, and modify collision hulls
- **JSON Export/Import**: Save and load collision data as JSON

## Supported BMD Versions

- Model v1 (0x10000001)
- Model v2 (0x10000002)
- LightMap v1 (0x10000100)
- LightMap v2 (0x10000101)

### Mesh Versions

- Mesh v2 (0x10000002)
- Mesh v3 (0x10000003) - day/night colors
- Mesh v4 (0x10000004) - new vertex format
- Mesh v5 (0x10000005) - materials
- Mesh v6 (0x10000006) - extra colors
- Mesh LM (0x10000100) - LightMap

## Installation

### Prerequisites

- Python 3.8 or higher
- pip

### Setup

1. Navigate to the `bmd editor` folder
2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate the virtual environment:
   ```bash
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Editor

#### V2 Editor (Recommended)
Windows: Double-click `run_editor_v2.bat` or run:
```bash
venv\Scripts\activate
python bmd_editor_v2.py
```

#### Basic Editor
Windows: Double-click `run_editor.bat` or run:
```bash
venv\Scripts\activate
python bmd_editor.py
```

#### Advanced Editor
Windows: Double-click `run_editor_advanced.bat` or run:
```bash
venv\Scripts\activate
python bmd_editor_advanced.py
```

#### Linux/Mac
```bash
source venv/bin/activate
python bmd_editor_v2.py  # V2 (recommended)
python bmd_editor.py  # Basic
python bmd_editor_advanced.py  # Advanced
```

## Usage

### V2 Editor - Opening Files

1. Click **File > Open Model** or use the **Quick Open** field
2. Paste the full path and click **Open**
3. A new window opens with the model data

### V2 Editor - Editing Model

Each model window has three categories:

#### Header
- Model version (read-only)
- Scale, Direction, Up, Position vectors (editable)
- LightMap names (if applicable)

#### Meshes
- Click on a mesh to expand
- Edit: Name, Texture path, Extra Colors flag
- Edit: AABB (Center, Extents, Mins, Maxs)
- Edit: Material (Name, Two Sided, Power, Colors)
- View/Edit vertices (click to open vertex editor)

#### Collision
- View hull count and mesh associations
- Add/Remove hulls
- Edit hull flags

### V2 Editor - Saving

- Click **File > Save** in the model window
- Or **File > Save As...** to save to a new location

### Basic/Advanced Editors - Opening Files

1. Click **File > Open Source Model** to load the source BMD file
2. Click **File > Open Target Model** to load the target BMD file

### Copying Data

#### Copy Collision (All)
1. Load a source model with collision data (Brush Building)
2. Load a target model
3. Click **Edit > Copy Collision (All)**
4. All collision data will be copied to the target model

#### Copy Selected Hull (Advanced)
1. Select a hull in the source panel
2. Click **Edit > Copy Selected Hull**
3. Click **Edit > Paste Collision** in target

#### Copy All Meshes
1. Load a source model
2. Load a target model
3. Click **Edit > Copy All Meshes**
4. All mesh data will be copied to the target model

#### Copy Selected Mesh (Advanced)
1. Select a mesh in the source panel
2. Click **Edit > Copy Selected Mesh**
3. Click **Edit > Paste Mesh** in target

### Collision Management (Advanced)

#### Add Hull
1. Click **Collision > Add Hull**
2. A new empty hull is added to the target model

#### Remove Hull
1. Select a hull in the target panel
2. Click **Collision > Remove Selected Hull**

#### Export/Import Collision
1. Click **View > Export Collision Info** to save collision as JSON
2. Click **View > Import Collision Info** to load collision from JSON

### Saving Files

1. Click **File > Save Target** to overwrite the target file
2. Click **File > Save Target As...** to save to a new location

## BMD File Structure

BMD files consist of:
- **File Header**: Magic bytes (MOXB) and model version
- **Model Transform**: Scale, direction, up, position vectors
- **Meshes**: Array of mesh data (vertices, indices, normals, colors, materials)
- **LightMap Names**: Optional lightmap texture paths
- **Collision Data**: Optional convex hull brushes (for Brush Building files)

## Collision System

The BMD collision system uses Convex Hulls:
- **CELBrushBuilding**: Wrapper containing the model and collision data
- **CCDBrush**: Individual convex hull for collision detection
- **Hull Mesh List**: Maps hulls to mesh indices

## Technical Details

### Vertex Format (v4+)
- Position: 3 floats (12 bytes)
- Diffuse Color: uint32 (4 bytes)
- UV Coordinates: 2 floats (8 bytes)
- Total: 24 bytes per vertex

### Color Format
- ARGB format (uint32)
- Day/Night color interpolation based on DNFactor

## License

This tool is provided as-is for BMD file editing purposes.
