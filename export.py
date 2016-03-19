import os
import json
import math
import shutil

import bpy
import bmesh
import mathutils


def write_some_data(context, filepath, mesh_path, mat_path, img_path):
    print('------------')
    make_directories([mesh_path, mat_path, img_path])
    
    print("Preparing Scene:        ....", end='\r')
    ob_list = bpy.context.selected_objects
    mesh_list = generate_mesh_list(ob_list)
    prepare_meshes(mesh_list)
    mat_list = generate_material_list(ob_list)
    print("Preparing Scene:        Done")

    export_materials(mat_list, mat_path, img_path)
    mapping_list = export_meshes(mesh_list, filepath, mesh_path)
    export_mappings(mapping_list, filepath, mesh_path, mat_path)
    return {'FINISHED'}


def prepare_meshes(mesh_list):
    for mesh in mesh_list:
        bmesh.ops.triangulate(mesh[1], faces=mesh[1].faces)
        #bmesh.ops.split_edges(mesh[1], edges=mesh[1].edges)
        
def export_mappings(mapping_list, file_path, mesh_path, mat_path):
    output = {'mapping':list()}
    for mesh_map in mapping_list:
        for face in mesh_map[1].faces:
            mat_id = face.material_index
        mat_name = mesh_map[2][0].data.materials[mat_id].name
        new_mat_path = os.path.join(os.path.relpath(mat_path, mesh_path), mat_name+'.json')
        output['mapping'].append({'path':new_mat_path})
        
    file_name = os.path.split(file_path)[1].replace('.', '.mapping.')
    new_mesh_path = os.path.join(os.path.dirname(file_path), mesh_path, file_name)
    with open(new_mesh_path, 'w') as out_file:
        out_file.write(json.dumps(output))


def export_meshes(mesh_list, file_path, mesh_path):
    node_data, parents = generate_node_data(mesh_list)
    vertex_data = generate_vertex_data(mesh_list)
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
            'vertices': vertex_data,      # For each mesh, a collection of vertex positions and normals
            'meshes': mesh_data,        # For each mesh, a description of how the vertices fit together
            'meshInstances': instance_data  # Creating instances of each mesh
        }
    }
    file_name = os.path.split(file_path)[1]
    new_mesh_path = os.path.join(os.path.dirname(file_path), mesh_path, file_name)
    with open(new_mesh_path, 'w') as out_file:
        out_file.write(json.dumps(output))
        
    return mapping_list


def generate_vertex_data(mesh_list):
    '''returns a playcanvas compatible list of vertex positions and normals'''
    vert_list = list()
    for mesh in mesh_list:
        percent = (mesh_list.index(mesh)+1) / len(mesh_list)
        print("Generating Vertex Data  {:3}%".format(int(percent*100)), end='\r')
        vert_list.append(extract_vert_data(mesh))
    print('')
    return vert_list


def extract_vert_data(mesh_data):
    '''Cretes a playcanvas compatible dict of vertex positions, normals, uv-maps etc '''
    mesh_name, mesh, instances = mesh_data
    uv_lay = mesh.loops.layers.uv.active
    
    numverts = len(mesh.verts)
    vertposlist = numverts*3*[None]
    vertnormallist = numverts*3*[None]
    uvdata = numverts*2*[None]
    for face in mesh.faces:
        for loop in face.loops:
            vert = loop.vert

            if uv_lay is not None:
                uv = loop[uv_lay].uv
                uvdata[2*vert.index] = uv.x
                uvdata[2*vert.index+1] = uv.y

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
                
    if uv_lay is not None:
        vert_dict['texCoord0'] = {
            'type': 'float32', 'components': 2, 'data': uvdata
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
    mesh_name, mesh, instances = mesh_data
    vertices = mesh_list.index(mesh_data)  # Where the vertex data is in the mesh_list
    
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
    node_id = 1  # Not zero because there is a root node without a mesh
    for mesh in mesh_list:
        percent = (mesh_list.index(mesh)+1) / len(mesh_list)
        print("Generating Node Data    {:3}%".format(int(percent*100)), end='\r')
        
        for instance in mesh[2]:
            node_dict = {
                'name': instance.name,
                'position': list(instance.location),  # R elative to parent
                'rotation': list(mathutils.Vector(instance.rotation_euler) * 180/math.pi),
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
        print("Generating Node Data    {:3}%".format(int(percent*100)), end='\r')
        
        for instance in mesh[2]:

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


def export_material(mat, mat_path, img_path):
    '''Exports a single material'''
    mat_output = {"mapping_format": "path"}

    # Basic Material Properties:
    mat_output['diffuse'] = list(mat.diffuse_color)
    mat_output['specular'] = list(mat.specular_color * mat.specular_intensity)
    
    if mat.alpha != 1.0:
        mat_output['opacity'] = mat.alpha
    if mat.emit != 0.0:
        mat_output['emissive'] = list(mat.diffuse_color * mat.emit)

    for tex in mat.texture_slots:
        if tex is None or tex.texture.type != 'IMAGE':
            continue
        image_path = copy_image(tex, img_path)

        if tex.use_map_color_diffuse:
            mat_output['diffuseMap'] = os.path.relpath(image_path, mat_path)
        if tex.use_map_emission:
            mat_output['emissiveMap'] = os.path.relpath(image_path, mat_path)
        if tex.use_map_color_spec:
            mat_output['specularMap'] = os.path.relpath(image_path, mat_path)

    with open(bpy.path.abspath('//')+mat_path+'/'+mat.name+'.json', 'w') as output_file:
        output_file.write(json.dumps(mat_output))

def copy_image(tex, img_path):
    '''Copies an image from a texture to the specified path, returning the new file path'''
    old_path = bpy.path.abspath(tex.texture.image.filepath)

    image_name = tex.name+'.'+old_path.split('.')[-1]
    image_path = os.path.join(img_path, image_name)
    abs_image_path = os.path.join(bpy.path.abspath('//'),image_path)
    # Copy file:
    shutil.copy2(old_path, abs_image_path)
    
    return image_path
    

def export_materials(mat_list, mat_path, img_path):
    '''Exports a list of materials'''
    for mat in mat_list:
        mat_num = mat_list.index(mat)+1
        mat_percent = mat_num / len(mat_list)
        print("Exporting materials:    {:3}%".format(int(mat_percent*100), mat.name), end='\r')
        export_material(mat, mat_path, img_path)
    print("")
        

def generate_material_list(obj_list):
    '''Genreates a list of materials from a list of passed in objects'''
    materials = set()
    for obj in obj_list:
        for mat in obj.data.materials:
            materials.add(mat)
    return list(materials)


def generate_mesh_list(ob_list):
    '''Generates a list of meshes. Splits meshes into ones with single-materials
    
    Mesh list is in the form: [('name', bmesh_obj, [instance_list]), ...]
    This is so that the location of multiple instances of objects can be preserved
    '''
    raw_meshes = dict()
    for ob in ob_list:
        if ob.type == 'MESH':
            if ob.data.name not in raw_meshes:  # We want to build a dict of {'mesh_name', [instance1, instance2 ...], 'mesh_name2'[...])
                raw_meshes[ob.data.name] = [ob]
            else:
                raw_meshes[ob.data.name].append(ob)
    mesh_list = list()
    for mesh_name in raw_meshes:
        # Split the meshes by material and convert them to bmesh
        mesh = bpy.data.meshes[mesh_name]
        meshes = separate_mesh_by_material(mesh, raw_meshes[mesh_name])
        mesh_list += meshes
    return mesh_list


def separate_mesh_by_material(mesh, ob):
    '''Returns a list of b-mesh meshes separating a mesh by material.
    
    Returned list is in the form:
        [('mesh_name', bmesh, [instance_list]), ...]'''
    old_mesh = bmesh.new()
    old_mesh.from_mesh(mesh)
    mesh_list = list()
    for mat in enumerate(mesh.materials):
        new_mesh = old_mesh.copy()
        face_remove_list = list()
        for face in new_mesh.faces:
            if face.material_index != mat[0]:
                face_remove_list.append(face)
        for face in face_remove_list:
        #bmesh.ops.delete(new_mesh, geom=face_remove_list)
            vert_list = list(face.verts)
            new_mesh.faces.remove(face)
            for vert in vert_list:
                if len(vert.link_faces) == 0:
                #if vert.is_wire:
                    new_mesh.verts.remove(vert)

        if len(mesh.materials) == 1:
            mesh_name = mesh.name
        else:
            mesh_name = mesh.name + '.' + mat[1].name
        mesh_list.append((mesh_name, new_mesh, ob))
    
    return mesh_list


def make_directories(dir_list):
    '''Creates the listed directories if they do not exist'''
    for dir in dir_list:
        if not os.path.isdir(bpy.path.abspath('//')+dir):
            os.makedirs(bpy.path.abspath('//')+dir)

                
############################# BLENDER UI THINGS ##################################


# ExportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator


class ExportPlaycanvas(Operator, ExportHelper):
    """Playcanvas is an HTML5 game engine that works using a JSON file format for storing materials and meshes"""
    bl_idname = "export_test.some_data"  # important since its how bpy.ops.import_test.some_data is constructed
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
        return write_some_data(context, self.filepath, self.mesh_path, self.mat_path, self.image_path)


# Only needed if you want to add into a dynamic menu
def menu_func_export(self, context):
    self.layout.operator(ExportPlaycanvas.bl_idname, text="Export Playcanvas (.json)")


def register():
    bpy.utils.register_class(ExportPlaycanvas)
    bpy.types.INFO_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_class(ExportPlaycanvas)
    bpy.types.INFO_MT_file_export.remove(menu_func_export)


if __name__ == "__main__":
    register()
    # test call
    bpy.ops.export_test.some_data('INVOKE_DEFAULT')
