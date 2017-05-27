# pylint: disable=too-few-public-methods,import-error
"""
This file exports models for playcanvas. It can either be set to export a single
file for an entire scene or to export each root parent object into a separate
file.

The re-write supports multiple UV layers. Hopefully it will also support
flat shading, but that is yet to be seen.

"""

import os
import json
import math
import shutil
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty
from bpy.types import Operator
import bpy
import bmesh
import mathutils

bl_info = {  # pylint: disable=invalid-name
    "name": "Export Playcanavs (.json)",
    "author": "sdfgeoff",
    "version": (1, 1),
    "blender": (2, 71, 0),
    "location": "File > Export > Playcanvas (.json)",
    "description": "Export Playcanavs (.json)",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export"}


def do_export(context, path_data, separate_objects=False):
    '''Runs the exporter on the scene. By default it will do selected objects,
    if there context is None it will do all of them. The parameters are:
       - filepath - to the main .json file
       - mesh_path - this is where the mesh json file goes
       - mat_path - this is where the material json files appear
       - img_path - All textures used will be compied to this folder
       - separate_objects - export parent root objects to separate files or not
    '''
    make_directories([path_data['mat'], path_data['mesh'], path_data['img']])

    SceneExporter(context, path_data, separate_objects)
    return {'FINISHED'}


class SceneExporter(object):
    '''Runs the exporter on the scene. By default it will do selected objects,
    if there context is None it will do all of them. The parameters are:
       - filepath - to the main .json file
       - mesh_path - this is where the mesh json file goes
       - mat_path - this is where the material json files appear
       - img_path - All textures used will be compied to this folder
       - separate_objects - export parent root objects to separate files or not
    '''
    def __init__(self, context, path_data, separate_objects=False):

        if context is not None:
            obj_list = bpy.data.selected_objects
        else:
            obj_list = bpy.data.objects

        obj_list = [o for o in obj_list if o.type == 'MESH']

        self.obj_list = list()
        if not separate_objects:
            obj = ObjectHeirachy(path_data['name'])
            obj.objects = obj_list
            self.obj_list.append(obj)
        else:
            for obj in obj_list:
                if obj.parent is None:
                    # Add the root node to the heirachy
                    self.obj_list.append(ObjectHeirachy(obj.name, obj))

        for counter, heirachy in enumerate(self.obj_list):
            info("Exporting Heirachy {}/{}".format(
                counter + 1, len(self.obj_list)
            ))
            HeirachyExporter(heirachy, path_data)


class ObjectHeirachy(object):
    '''This contains a list of objects that will be exported to a single json
    file and the name of that file'''
    def __init__(self, name, root_obj=None):
        self.objects = list()
        self.name = name
        if root_obj is not None:
            self.objects = children_recursive(root_obj)
            self.objects.append(root_obj)

    def __repr__(self):
        return "Heirachy {}: {}".format(self.name, self.objects)


class HeirachyExporter(object):
    '''Exports all the data required for a list of objects. THe objects mesh
    data will end up in a single file'''
    def __init__(self, heirachy, path_data):
        self.heirachy = heirachy

        self.uv_list = self.generate_uv_list()

        # Meshes
        info("Generating Meshes .....")
        self.mesh_list = self.generate_mesh_list()
        mesh_data_list = list()
        for mesh_id, mesh in enumerate(self.mesh_list):
            mesh_data_list.append(MeshParser(mesh, mesh_id, self.uv_list))

        node_data, parents = self.generate_node_data()

        info("Exporting Mappings ...")
        material_list = self.export_mappings(path_data)

        info("Exporting Materials ...")
        for mat in material_list:
            MaterialExporter(mat, self.uv_list, path_data)

        info("Exporting Main file")
        output = {
            'model': {
                'version': 2,
                'nodes': [
                    {
                        "name": "RootNode",
                        "position": [0, 0, 0],
                        "rotation": [0, 0, 0],
                        "scale": [1, 1, 1],
                    }
                ] + node_data,

                # Parent the root node to the scene
                'parents': [-1] + parents,

                # Something to do with bones and animation
                'skins': [],

                # For each mesh, a collection of vertex positions and normals
                'vertices': [m.vert_data for m in mesh_data_list],

                # For each mesh, a description of how the vertices fit together
                'meshes': mesh_data_list,

                # What mesh links to what node
                'meshInstances': self.generate_instance_data()
            }
        }
        new_mesh_path = os.path.join(
            path_data['mesh'],
            self.heirachy.name + '.json'
        )
        json.dump(output, open(new_mesh_path, 'w+'), indent=4, sort_keys=True)

    def generate_uv_list(self):
        '''A list that makes sure UV maps end up in the right place'''
        layer_names = list()
        for obj in self.heirachy.objects:
            for layer in obj.data.uv_layers:
                layer_names.append(layer.name)
        return layer_names

    def generate_mesh_list(self):
        '''Generates a list of meshes. Splits meshes into ones with single-materials

        Mesh list is in the form: [('name', bmesh_obj, [instance_list]), ...]
        This is so that the location of multiple instances of objects can be
        preserved
        '''
        raw_meshes = dict()
        for obj in self.heirachy.objects:
            # We want to build a dict of:
            # {'mesh_name', [instance1, instance2 ...], 'mesh_name2'[...])
            if obj.data.name not in raw_meshes:
                raw_meshes[obj.data.name] = [obj]
            else:
                raw_meshes[obj.data.name].append(obj)

        mesh_list = list()
        for mesh_name in raw_meshes:
            # Split the meshes by material and convert them to bmesh
            mesh = bpy.data.meshes[mesh_name]
            meshes = separate_mesh_by_material(mesh, raw_meshes[mesh_name])
            mesh_list += meshes

        return mesh_list

    def export_mappings(self, path_data):
        '''Exports the mapping between meshes and materials'''
        output = {'mapping': list()}

        materials = dict()

        # The mapping list is a list of instances in order of appearance in
        # the instances list that contains the mesh used. It is essentially
        # an inversion of mesh_list
        mapping_list = list()
        for mesh in self.mesh_list:
            for _instance in mesh[2]:
                mapping_list.append(mesh)

        mesh_to_material_path = os.path.relpath(
            path_data['mat'],
            path_data['mesh']
        )
        for mesh_map in mapping_list:
            for face in mesh_map[1].faces:
                mat_id = face.material_index
                break
            if mesh_map[2][0].data.materials:
                # If there is a material in the mesh, export it's path
                mat = mesh_map[2][0].data.materials[mat_id]
                new_mat_path = os.path.join(
                    mesh_to_material_path, mat.name+'.json'
                )
                # Store the material so we know which are used so we don't
                # export unnecesssary ones
                materials[mat.name] = mat
            else:
                new_mat_path = "None"

            output['mapping'].append({'path': new_mat_path})

        file_name = os.path.join(
            path_data['mesh'],
            self.heirachy.name + '.mapping.json'
        )
        json.dump(output, open(file_name, 'w'), indent=4, sort_keys=True)

        return [materials[m] for m in materials]

    def generate_instance_data(self):
        '''returns a playcanvas compatible list linking meshes to instances'''
        instance_data = list()
        node_id = 1  # Not zero because there is a root node without a mesh
        for mesh_id, mesh in enumerate(self.mesh_list):
            for _instance in mesh[2]:
                ob_num = node_id
                instance_dict = {
                    'node': ob_num,
                    'mesh': mesh_id
                }
                instance_data.append(instance_dict)
                node_id += 1
        return instance_data

    def generate_node_data(self):
        '''returns a playcanvas compatible list of positions and locations of the
        various nodes'''
        node_data = list()
        for mesh in self.mesh_list:
            for instance in mesh[2]:
                corrected_rotation = mathutils.Vector(instance.rotation_euler)
                corrected_rotation *= 180 / math.pi
                node_dict = {
                    'name': instance.name,
                    'position': list(instance.location),  # Relative to parent
                    'rotation': list(corrected_rotation),
                    'scale': list(instance.scale),
                }
                node_data.append(node_dict)

        parent_list = list()
        node_name_list = [n['name'] for n in node_data]
        for mesh in self.mesh_list:
            for instance in mesh[2]:
                if instance.parent is not None and \
                        instance.parent.name in node_name_list:
                    parent_id = node_name_list.index(instance.parent.name)+1
                    parent_list.append(parent_id)
                else:
                    parent_list.append(0)

        return node_data, parent_list


class MeshParser(dict):
    '''Parses a single mesh, and provides access to it's face indices,
    and vertex data'''
    def __init__(self, mesh, id_num, uv_list):
        super().__init__()
        self.mesh = mesh[1]
        self.uv_list = uv_list

        # This isn't really dealt with at this point, and has more to do with
        # when you append all of the vertices together into the vertex list
        # But keeping it the order of the meshes makes sense, and is the easiest
        self['vertices'] = id_num

        self['indices'] = None

        self['aabb'] = self.calculate_bounding_box()

        # These are always the same
        self['type'] = 'triangles'
        self['base'] = 0

        self.update_mesh_data()
        self.update_vertex_data()

    def calculate_bounding_box(self):
        '''Get's the mesh extents'''
        minpos = [float('inf'), float('inf'), float('inf')].copy()
        maxpos = [float('inf'), float('inf'), float('inf')].copy()
        for face in self.mesh.faces:
            for loop in face.loops:
                vert = loop.vert
                minpos[0] = min(vert.co.x, minpos[0])
                minpos[1] = min(vert.co.y, minpos[1])
                minpos[2] = min(vert.co.z, minpos[2])
                maxpos[0] = max(vert.co.x, minpos[0])
                maxpos[1] = max(vert.co.y, minpos[1])
                maxpos[2] = max(vert.co.z, minpos[2])

        return {'min': minpos, 'max': maxpos}

    def update_mesh_data(self):
        '''Converts a mesh into a dict'''
        self['indices'] = list()  # What vertices make up a face
        for face in self.mesh.faces:
            for vert in face.verts:
                self['indices'].append(vert.index)
        self['count'] = len(self['indices'])

    def update_vertex_data(self):
        '''Extracts normals and UV's'''
        numverts = len(self.mesh.verts)
        vertposlist = numverts*3*[None]
        vertnormallist = numverts*3*[None]

        uv_layers = self.mesh.loops.layers.uv
        uvdata = {i: numverts*2*[None].copy() for i in uv_layers.keys()}
        for face in self.mesh.faces:
            for loop in face.loops:
                vert = loop.vert

                for uv_lay in uv_layers.keys():
                    uv_coords = loop[uv_layers[uv_lay]].uv
                    uvdata[uv_lay][2*vert.index] = uv_coords.x
                    uvdata[uv_lay][2*vert.index+1] = uv_coords.y
                vertposlist[3*vert.index] = vert.co.x
                vertposlist[3*vert.index+1] = vert.co.y
                vertposlist[3*vert.index+2] = vert.co.z
                vertnormallist[3*vert.index] = vert.normal.x
                vertnormallist[3*vert.index+1] = vert.normal.y
                vertnormallist[3*vert.index+2] = vert.normal.z

        self.vert_data = {
            'position': {
                'type': 'float32',
                'components': 3,
                'data': vertposlist
            },
            'normal': {
                'type': 'float32',
                'components': 3,
                'data': vertnormallist
            },
        }

        for uv_name in uvdata:
            uv_index = self.uv_list.index(uv_name)
            self.vert_data['texCoord{}'.format(uv_index)] = {
                'type': 'float32', 'components': 2, 'data': uvdata[uv_name]
            }


def separate_mesh_by_material(mesh, obj):
    '''Returns a list of b-mesh meshes separating a mesh by material.

    Returned list is in the form:
        [('mesh_name', bmesh, [instance_list]), ...]

    Also does any processing of the mesh required'''

    # Convert to bmesh, split by faces:
    old_mesh = bmesh.new()
    old_mesh.from_mesh(mesh)

    # OPERATIONS ON BMESH TO PREPARE GEOMETRY
    bmesh.ops.triangulate(old_mesh, faces=old_mesh.faces)

    mesh_list = list()
    if mesh.materials:
        for mat_id, mat in enumerate(mesh.materials):
            # Duplicate the mesh
            new_mesh = old_mesh.copy()
            face_remove_list = list()
            for face in new_mesh.faces:
                if face.material_index != mat_id:
                    face_remove_list.append(face)
            # Remove faces that aren't part of this material
            for face in face_remove_list:
                new_mesh.faces.remove(face)

            # Remove isolated verts
            vert_remove_list = list()
            for vert in new_mesh.verts:
                vert_remove_list.append(vert)
                for face in new_mesh.faces:
                    if vert in face.verts and vert in vert_remove_list:
                        vert_remove_list.remove(vert)
            for vert in vert_remove_list:
                new_mesh.verts.remove(vert)
            new_mesh.verts.index_update()

            # Give it a sensible name
            if len(mesh.materials) == 1:
                mesh_name = mesh.name
            else:
                mesh_name = mesh.name + '.' + mat.name
            mesh_list.append((mesh_name, new_mesh, obj))
    else:
        # No materials, let's just hope things turn out good....
        warn("No materials in mesh {}".format(mesh.name))
        mesh_list.append((mesh.name, old_mesh, obj))

    return mesh_list


class MaterialExporter(dict):
    '''Exports a single material'''
    def __init__(self, material, uv_list, path_data):
        super().__init__()
        self.material = material
        self.uv_list = uv_list

        self["mapping_format"] = "path"
        self['name'] = self.material.name

        self._parse_basic_properties()
        self._parse_images(path_data)

    def _parse_basic_properties(self):
        '''Basic Material Properties such as diffuse color'''
        mat = self.material
        spec_color = mat.specular_color * mat.specular_intensity
        emit_color = mat.diffuse_color * mat.emit

        self['diffuse'] = list(mat.diffuse_color)
        self['specular'] = list(spec_color)
        self['emissive'] = list(emit_color)

        if mat.alpha != 1.0:
            self['opacity'] = mat.alpha

        if not mat.game_settings.use_backface_culling:
            self['cull'] = 0

    def _parse_images(self, path_data):
        '''Look through textures for image paths'''
        path_to_image_dir = os.path.relpath(path_data['img'], path_data['mat'])

        for tex_id, tex in enumerate(self.material.texture_slots):
            if tex is None or tex.texture.type != 'IMAGE':
                # Ignore empty texture slots or ones that aren't images
                continue

            if not self.material.use_textures[tex_id]:
                # Ignore texture slots that are disabled
                continue
            image_path = copy_image(tex, path_data['img'])
            image_path = os.path.split(image_path)[1]
            image_path = os.path.join(path_to_image_dir, image_path)

            if tex.uv_layer != '':
                uv_layer = self.uv_list.index(tex.uv_layer)
            else:
                warn("Unspecific UV reference in texture {}".format(tex.name))
                uv_layer = 0

            if tex.use_map_color_diffuse:
                self['diffuseMap'] = image_path
                self['diffuseMapUv'] = uv_layer
            if tex.use_map_emission:
                self['emissiveMap'] = image_path
                self['emissiveMapUv'] = uv_layer
            if tex.use_map_color_spec:
                self['specularMap'] = image_path
                self['specularMapUv'] = uv_layer
            if tex.use_map_normal:
                self['normalMap'] = image_path
                self['bumpMapFactor'] = tex.normal_factor
                self['normalMapUv'] = uv_layer

        mat_file_name = self.material.name + '.json'
        file_path = os.path.join(path_data['mat'], mat_file_name)
        json.dump(self, open(file_path, 'w'), indent=4, sort_keys=True)


def warn(message):
    '''Display a warning message'''
    print("Warning: {}".format(message))


def info(message):
    '''Displays an info message'''
    print("Info: {}".format(message))


def children_recursive(root_node):
    '''Return all children nodes of a root node'''
    child_list = list()
    for child in root_node.children:
        child_list = child_list + children_recursive(child)
        child_list.append(child)
    return child_list


def copy_image(tex, img_path):
    '''Copies an image from a texture to the specified path, returning the new
    file path'''
    old_path = bpy.path.abspath(tex.texture.image.filepath)

    image_name = tex.name+'.'+old_path.split('.')[-1]
    image_path = os.path.join(img_path, image_name)
    # Copy file:
    shutil.copy2(old_path, image_path)

    return image_path


def make_directories(dir_list):
    '''Creates the listed directories if they do not exist'''
    for direct in dir_list:
        full_path = get_full_path(direct)
        if not os.path.isdir(full_path):
            warn("Making Directory {}".format(full_path))
            os.makedirs(full_path)


def get_full_path(slug):
    '''Makes sure all paths start at the same place'''
    if slug.startswith('.'):
        return bpy.path.abspath('//')+slug
    return slug

# ----------------------------- BLENDER UI THINGS -----------------------------


# ExportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.


class ExportPlaycanvas(Operator, ExportHelper):
    '''Playcanvas is an HTML5 game engine that works using a JSON file format
    for storing materials and meshes'''
    # important since its how bpy.ops.import_test.some_data is constructed
    bl_idname = "export_test.some_data"
    bl_label = "Export Playcanavs (.json)"

    # ExportHelper mixin class uses this
    filename_ext = ".json"

    filter_glob = StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    # List of operator properties, the attributes will be assigned
    # to the class instance from the operator settings before calling.
    mesh_path = StringProperty(
        name="Mesh Path",
        description="Put mesh files into this folder",
        default="./Meshes",
    )
    mat_path = StringProperty(
        name="Material Path",
        description="Put materials in a subfolder with this name",
        default="./Materials",
    )
    image_path = StringProperty(
        name="Image Path",
        description="Copy images into a subfolder with this name",
        default="./Images",
    )

    def execute(self, context):
        '''Actually does the export'''
        path_data = {
            'mesh': self.mesh_path,
            'mat': self.mat_path,
            'img': self.img_path,
            'name': self.file_name
        }
        return do_export(
            context,
            path_data,
        )


def menu_func(self, _context):
    '''Only needed if you want to add into a dynamic menu'''
    self.layout.operator(
        ExportPlaycanvas.bl_idname,
        text="Export Playcanvas (.json)"
    )


def register():
    '''Add to UI'''
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_file_export.append(menu_func)


def unregister():
    '''Remove from UI'''
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_export.remove(menu_func)


if __name__ == "__main__":
    register()
    # test call
    bpy.ops.export_test.some_data('INVOKE_DEFAULT')
