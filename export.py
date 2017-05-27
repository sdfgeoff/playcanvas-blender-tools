#pylint: disable=too-few-public-methods,ungrouped-imports,wrong-import-position,import-error

bl_info = {  #pylint: disable=invalid-name
    "name": "Export Playcanavs (.json)",
    "author": "sdfgeoff",
    "version": (1, 1),
    "blender": (2, 71, 0),
    "location": "File > Export > Playcanvas (.json)",
    "description": "Export Playcanavs (.json)",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export"}

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


def do_export(context, file_name, mesh_path, mat_path, img_path, separate_objects=False):
    '''Runs the exporter on the scene. By default it will do selected objects,
    if there context is None it will do all of them. The parameters are:
       - filepath - to the main .json file
       - mesh_path - this is where the mesh json file goes
       - mat_path - this is where the material json files appear
       - img_path - All textures used will be compied to this folder
       - separate_objects - export parent root objects to separate files or not
    '''
    make_directories([mesh_path, mat_path, img_path])
    path_data = {
        'mesh':mesh_path,
        'mat':mat_path,
        'img':img_path,
        'name':file_name
    }
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

        iterate_list_display_progress(
            [(o, path_data) for o in self.obj_list],
            HeirachyExporter,
            'Exporting Heirachy(s)'
        )


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
        self.material_list = self.generate_material_list()

        # Materials
        iterate_list_display_progress(
            [(m, self.uv_list, path_data) for m in self.material_list],
            MaterialExporter,
            "Exporting Material(s)"
        )

        # Meshes
        mesh_list = self.generate_mesh_list()
        mapping_list = export_meshes(
            mesh_list,
            self.heirachy.name,
            path_data,
            self.uv_list
        )
        export_mappings(
            mapping_list,
            self.heirachy.name,
            path_data
        )

    def generate_material_list(self):
        '''Genreates a list of materials from a list of passed in objects'''
        materials = set()
        for obj in self.heirachy.objects:
            if obj.type == 'MESH':
                for mat in obj.data.materials:
                    materials.add(mat)
        return list(materials)

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


def separate_mesh_by_material(mesh, obj):
    '''Returns a list of b-mesh meshes separating a mesh by material.

    Returned list is in the form:
        [('mesh_name', bmesh, [instance_list]), ...]

    Also does any processing of the mesh required'''
    # Preprocess meshes as bpy.types.Mesh
    mesh.calc_normals_split()

    # Convert to bmesh, split by faces:
    old_mesh = bmesh.new()
    old_mesh.from_mesh(mesh)
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
                vert_list = list(face.verts)
                new_mesh.faces.remove(face)
                for vert in vert_list:
                    if vert.link_faces:
                        new_mesh.verts.remove(vert)

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

    # Anything to be done to bmeshes:
    for output_mesh in mesh_list:
        bmesh.ops.triangulate(output_mesh[1], faces=output_mesh[1].faces)

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


def children_recursive(root_node):
    '''Return all children nodes of a root node'''
    child_list = list()
    for child in root_node.children:
        child_list.append(child)
        child_list += children_recursive(child)
    return child_list


def iterate_list_display_progress(iterable, function, name):
    '''A ghetto status bar'''
    for counter, obj in enumerate(iterable):
        print("{} {}/{}".format(name, counter, len(iterable)), end='\r')
        function(*obj)
    print("{} Done".format(name), end='\n')


def export_mappings(mapping_list, name, path_data):
    '''Exports the mapping between meshes and materials'''
    output = {'mapping':list()}

    mesh_to_material_path = os.path.relpath(path_data['mat'], path_data['mesh'])
    for mesh_map in mapping_list:
        for face in mesh_map[1].faces:
            mat_id = face.material_index
            break
        if mesh_map[2][0].data.materials:
            mat_name = mesh_map[2][0].data.materials[mat_id].name
            new_mat_path = os.path.join(mesh_to_material_path, mat_name+'.json')
        else:
            new_mat_path = "None"

        output['mapping'].append({'path': new_mat_path})

    file_name = os.path.join(path_data['mesh'], name + '.mapping.json')
    json.dump(output, open(file_name, 'w'), indent=4, sort_keys=True)


def export_meshes(mesh_list, name, path_data, uv_list):
    '''Exports all the meshes'''
    node_data, parents = generate_node_data(mesh_list)
    vertex_data = generate_vertex_data(mesh_list, uv_list)
    mesh_data = generate_mesh_data(mesh_list)
    instance_data, mapping_list = generate_instance_data(mesh_list)
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
            'parents': [-1] + parents,     # Parent the root node to the scene
            'skins': [],         # Something to do with bones and animation

            # For each mesh, a collection of vertex positions and normals
            'vertices': vertex_data,

            # For each mesh, a description of how the vertices fit together
            'meshes': mesh_data,
            'meshInstances': instance_data  # Creating instances of each mesh
        }
    }
    new_mesh_path = os.path.join(path_data['mesh'], name + '.json')

    json.dump(output, open(new_mesh_path, 'w+'), indent=4, sort_keys=True)

    return mapping_list


def generate_vertex_data(mesh_list, uv_list):
    '''returns a playcanvas compatible list of vertex positions and normals'''
    vert_list = list()
    for mesh in mesh_list:
        percent = (mesh_list.index(mesh)+1) / len(mesh_list)
        print("Generating Vertex Data  {:3}%".format(int(percent*100)), end='\r')
        vert_list.append(extract_vert_data(mesh, uv_list))
    print('')
    return vert_list


def extract_vert_data(mesh_data, uv_list):
    '''Cretes a playcanvas compatible dict of vertex positions, normals, uv-maps etc '''
    _mesh_name, mesh, _instances = mesh_data

    numverts = len(mesh.verts)
    vertposlist = numverts*3*[None]
    vertnormallist = numverts*3*[None]
    print(mesh.loops.layers.uv)
    uvdata = {i:numverts*2*[None].copy() for i in mesh.loops.layers.uv.keys()}
    for face in mesh.faces:
        for loop in face.loops:
            vert = loop.vert

            for uv_lay in mesh.loops.layers.uv.keys():
                uv = loop[mesh.loops.layers.uv[uv_lay]].uv
                uvdata[uv_lay][2*vert.index] = uv.x
                uvdata[uv_lay][2*vert.index+1] = uv.y

            vertposlist[3*vert.index] = vert.co.x
            vertposlist[3*vert.index+1] = vert.co.y
            vertposlist[3*vert.index+2] = vert.co.z
            vertnormallist[3*vert.index] = vert.normal.x
            vertnormallist[3*vert.index+1] = vert.normal.y
            vertnormallist[3*vert.index+2] = vert.normal.z

    vert_dict = {
        'position': {'type': 'float32', 'components': 3, 'data': vertposlist},
        'normal': {'type': 'float32', 'components': 3, 'data': vertnormallist},
    }

    for uv_name in uvdata:
        uv_index = uv_list.index(uv_name)
        vert_dict['texCoord{}'.format(uv_index)] = {
            'type': 'float32', 'components': 2, 'data': uvdata[uv_name]
        }
    return vert_dict


def generate_mesh_data(mesh_list):
    '''returns a playcanvas compatible dict of what vertex id's make up faces'''
    mesh_data_list = list()
    for mesh in mesh_list:
        percent = (mesh_list.index(mesh)+1) / len(mesh_list)
        print("Generating Object Data  {:3}%".format(int(percent*100)), end='\r')
        mesh_data_list.append(extract_mesh_data(mesh, mesh_list))
    print('')
    return mesh_data_list


def extract_mesh_data(mesh_data, mesh_list):
    '''Converts a mesh into a dict'''
    _mesh_name, mesh, _instances = mesh_data

     # Where the vertex data is in the mesh_list
    vertices = mesh_list.index(mesh_data)

    indices = list()  # What vertices make up a face
    for face in mesh.faces:
        for vert in face.verts:
            indices.append(vert.index)

    typ = 'triangles'
    base = 0
    count = len(indices)

    minpos = [float('inf'), float('inf'), float('inf')].copy()
    maxpos = [float('inf'), float('inf'), float('inf')].copy()
    for face in mesh.faces:
        for loop in face.loops:
            vert = loop.vert
            minpos[0] = min(vert.co.x, minpos[0])
            minpos[1] = min(vert.co.y, minpos[1])
            minpos[2] = min(vert.co.z, minpos[2])
            maxpos[0] = max(vert.co.x, minpos[0])
            maxpos[1] = max(vert.co.y, minpos[1])
            maxpos[2] = max(vert.co.z, minpos[2])

    mesh_dict = {
        'aabb': {'min': minpos, 'max': maxpos},
        'vertices': vertices,
        'indices': indices,
        'type': typ,
        'base': base,
        'count': count
    }

    return mesh_dict


def generate_node_data(mesh_list):
    '''returns a playcanvas compatible list of positions and locations of the various nodes'''
    node_data = list()
    parent_list = list()
    for mesh in mesh_list:
        percent = (mesh_list.index(mesh)+1) / len(mesh_list)
        print("Generating Node Data    {:3}%".format(int(percent*100)))

        for instance in mesh[2]:
            corrected_rotation = mathutils.Vector(instance.rotation_euler) * 180 / math.pi
            node_dict = {
                'name': instance.name,
                'position': list(instance.location),  # Relative to parent
                'rotation': list(corrected_rotation),
                'scale': list(instance.scale),
            }
            node_data.append(node_dict)
    print('')

    node_name_list = [n['name'] for n in node_data]
    for mesh in mesh_list:
        for instance in mesh[2]:
            if instance.parent is not None and instance.parent.name in node_name_list:
                parent_list.append(node_name_list.index(instance.parent.name)+1)
            else:
                parent_list.append(0)

    return node_data, parent_list


def generate_instance_data(mesh_list):
    '''returns a playcanvas compatible list linking meshes to instances'''
    instance_data = list()
    mapping_list = list()
    node_id = 1  # Not zero because there is a root node without a mesh
    for mesh in mesh_list:
        percent = (mesh_list.index(mesh)+1) / len(mesh_list)
        print("Generating Node Data    {:3}%".format(int(percent*100)))

        for _instance in mesh[2]:

            mesh_num = mesh_list.index(mesh)
            ob_num = node_id
            instance_dict = {
                'node': ob_num,
                'mesh': mesh_num
            }
            instance_data.append(instance_dict)
            mapping_list.append(mesh)
            node_id += 1
    print('')
    return instance_data, mapping_list


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
            print("Making Directory {}".format(full_path))
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
    """Playcanvas is an HTML5 game engine that works using a JSON file format
    for storing materials and meshes"""
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
        return do_export(
            context,
            self.filepath, self.mesh_path, self.mat_path, self.image_path
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
