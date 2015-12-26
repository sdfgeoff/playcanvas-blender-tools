'''
This file attempts to export a playcanas scene. It will export 
pretty much everything:
    - meshes
    - mesh instances
    - lights?
    - empties
    - parenting

I plan to support:
    - simple materials
    - image materials
     
It will only export selected objects.
And I hate BPY enough that I'm not writing a full export script.
If someone wants to make a wrapper around this to give it the nice
blender interface they're welcome to.

To use it:
1) edit the outfile parameter
2) select the objects to export
3) run this script

It will produce some files:
    - name.json
    - name.mapping.json (hopefully)
    and any materials/textures (hopefully)
     '''
     
NAME = 'test1'
PATH = './'
MAT_PATH = './materials'
IMAGE_PATH = './images'
    
     
import bpy
import bmesh
import json
import os
import shutil

mesh_list = []      #In the json, a mesh is stored by index. In blender to tell if they share a mesh, we have to compare their names
ob_list = []
mat_list = []

def start():
    export_model()
    #export_material()


def export_model():
    global mesh_list
    global obj_list
    global mat_list
    
    try:
        os.makedirs(bpy.path.abspath('//')+MAT_PATH)
    except OSError:
        pass
    try:
        os.makedirs(bpy.path.abspath('//')+IMAGE_PATH)
    except OSError:
        pass

    inf = float('inf')
    output = {'model':{
    'version':2,
    'nodes':[
        {"name":"RootNode", "position":[0,0,0], "rotation":[0,0,0], "scale":[1,1,1]}
    ],
    'parents':[-1],     #Parent the root node to the scene
    'skins':[],         #Something to do with bones and animation
    'vertices':[],      #For each mesh, a collection of vertex positions and normals
    'meshes':[],        #For each mesh, a description of how the vertices fit together
    'meshInstances':[]  #Creating instances of each mesh
    }}
    
    mapping_output = {"mapping":[], "area":0}

    print('------ new run ------')

      
    for ob in bpy.context.selected_objects:
        nodedict = {'name':ob.name,
                    'position': list(ob.location), #Relative to parent
                    'rotation': list(ob.delta_rotation_euler),
                    'scale':list(ob.delta_scale),
                    }

        output['model']['nodes'].append(nodedict)
        ob_list.append(ob.name)
        if ob.type == 'MESH':
            mesh_list.append(ob.data.name)
            mapping_output['mapping'].append({"path":MAT_PATH+"/"+ob.active_material.name+".json"})
            mat_list.append(ob.active_material)
    
    for mat in mat_list:
        exportMat(mat)
            
    for ob in bpy.context.selected_objects:
        
        # Create Parenting Relations
        if ob.parent in ob_list:
            parent = ob_list.index(ob.parent)
        else:
            parent = 0
        output['model']['parents'].append(parent)
        
        
        
        
        #Mesh Gubbage
        if ob.type == 'MESH':
            mesh_num = mesh_list.index(ob.data.name)
            ob_num = ob_list.index(ob.name)
            output['model']['meshInstances'].append({
                                    'node':ob_num,
                                    'mesh':mesh_num,})
            
            indices = []
            minpos = [inf, inf, inf]
            maxpos = [-inf, -inf, -inf]
            
            bm = bmesh.new()
            #Apply modifiers and triangulate.
            bm.from_mesh(ob.to_mesh(scene=bpy.context.scene, apply_modifiers=True, settings='PREVIEW'))
            bmesh.ops.triangulate(bm, faces=bm.faces, quad_method=1,ngon_method=1) #The 1's are undocumented quad_method and ngon_methodW
            
            #Store vertex and UV information
            numverts = len(bm.verts)
            vertposlist = numverts*3*[None]
            vertnormallist = numverts*3*[None]
            uvdata = numverts*2*[None]
            
            uv_lay = bm.loops.layers.uv.active
            for face in bm.faces:
                for loop in face.loops:
                    vert = loop.vert
                    
                    if uv_lay != None:
                        uv = loop[uv_lay].uv
                        uvdata[2*vert.index] = uv.x
                        uvdata[2*vert.index+1] = uv.y
                    
                    vertposlist[3*vert.index] = vert.co.x
                    vertposlist[3*vert.index+1] = vert.co.y
                    vertposlist[3*vert.index+2] = vert.co.z
                    minpos[0] = min(vert.co.x, minpos[0])
                    minpos[1] = min(vert.co.y, minpos[1])
                    minpos[2] = min(vert.co.z, minpos[2])
                    maxpos[0] = max(vert.co.x, minpos[0])
                    maxpos[1] = max(vert.co.y, minpos[1])
                    maxpos[2] = max(vert.co.z, minpos[2])
                    vertnormallist[3*vert.index] = vert.normal.x
                    vertnormallist[3*vert.index+1] = vert.normal.y
                    vertnormallist[3*vert.index+2] = vert.normal.z
                    
            #Link faces to vertices
            #facedata = ob.data.polygons.items()
            for face in bm.faces:
                #print(list(face[1].vertices))
                for vert in face.verts:
                    indices.append(vert.index)
            
            vertices = mesh_num
            typ = 'triangles'
            base = 0
            count = len(indices)

            vert_dict = {
                        'position':{'type':'float32', 'components':3, 'data':vertposlist},
                        'normal':{'type':'float32', 'components':3, 'data':vertnormallist},
                        }
            
            if uv_lay != None:
                vert_dict['texCoord0'] = {
                    'type':'float32', 'components':2, 'data':uvdata
                }

            output['model']['vertices'].append(vert_dict)



            mesh_dict = {
                        'aabb':{'min':minpos,'max':maxpos,},
                        'vertices':vertices,
                        'indices':indices,
                        'type':typ,
                        'base':base,
                        'count':count
                        }
            
            output['model']['meshes'].append(mesh_dict)
            bm.free
    with open(bpy.path.abspath('//')+PATH+NAME+'.json', 'w') as f:
        f.write(json.dumps(output))
    with open(bpy.path.abspath('//')+PATH+NAME+'.mapping.json', 'w') as f:
        f.write(json.dumps(mapping_output))

def exportMat(mat):
    mat_output = {"mapping_format": "path"}
    
    #Basic Material Properties:
    mat_output['opacity'] = mat.alpha
    mat_output['diffuse'] = list(mat.diffuse_color)
    mat_output['emissive'] = list(mat.diffuse_color * mat.emit)
    mat_output['specular'] = list(mat.specular_color * mat.specular_intensity)
    
    for tex in mat.texture_slots:
        if tex == None or tex.texture.type != 'IMAGE':
            continue
        
        old_image_path = tex.texture.image.filepath
        
        image_name = tex.name+'.'+old_image_path.split('.')[-1]
        image_path = IMAGE_PATH+'/'+image_name
        abs_image_path = bpy.path.abspath('//')+image_path
        #Copy file:
        print("Copying image to: "+image_path)
        shutil.copy2(old_image_path, abs_image_path)
        if tex.use_map_color_diffuse:
            mat_output['diffuseMap'] = '../'+image_path
        if tex.use_map_emission:
            mat_output['emissiveMap'] = '../'+image_path
        if tex.use_map_color_spec:
            mat_output['specularMap'] = '../'+image_path
            
    
    with open(bpy.path.abspath('//')+MAT_PATH+'/'+mat.name+'.json', 'w') as f:
        f.write(json.dumps(mat_output))

start()
print("Done")
