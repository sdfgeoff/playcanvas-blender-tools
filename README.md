# playcanvas-blender-tools
Tools for going from blender to playcanvas game engine

About
======
This repository provides tools for using playcanvas without it's online editor. 
While it's online editor is very god for simple projects and for learning, when
doing big projects or if you simply don't have a good internet connection, 
offline alternatives must be used.

Components
======
Model Exporter
----
First and foremost amongs offline tools is the model exporter. This script is
designed to be run from blender and will export the selected objects and their
materials.

Features:
 * Export models, meshes and the active UV map
 * Export simple material properties (eg diffuse color, specular color)
 * Export image textures linked to diffuse, specular and emit
 
Planned Features:
 * Export of light and empy data into a (non-playcanvas) json file
 * Export multiple UV maps
 * Export more complete set of material features (eg culling)
 * Neater code!
 
Planned Components
----
* Model Viewer - A HTML file that can be used to browse and view models
* Material Editor - A HTML file that extends that allows editing of materials.
