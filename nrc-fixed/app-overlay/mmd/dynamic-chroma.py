"""Build a portable, frame-driven Blender scene from a serialized PMX.

The PMX remains an ordinary exchange model. Only the derived .blend carries
these Blender materials. Source: NRC chroma-core.mjs; UE refraction and random
neighbour-cell sparkle lookup are not reproduced.
"""
import json
import math
import shutil
from pathlib import Path

import bpy
from mathutils import Vector


def build_material(material, base_image, mask_image, preset, assets):
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links

    def node(kind, label):
        n = nodes.new(kind)
        n.label = label
        n.name = label
        return n

    def connect(value, socket):
        if hasattr(value, 'node'):
            links.new(value, socket)
        else:
            socket.default_value = value

    def math_node(operation, a, b=0):
        n = node('ShaderNodeMath', operation)
        n.operation = operation
        connect(a, n.inputs[0]); connect(b, n.inputs[1])
        return n.outputs[0]

    def rgb(value):
        n = node('ShaderNodeRGB', 'Palette')
        n.outputs[0].default_value = (*value, 1)
        return n.outputs[0]

    def scale(color, amount):
        n = node('ShaderNodeVectorMath', 'Color scale'); n.operation = 'SCALE'
        connect(color,n.inputs[0]); connect(amount,n.inputs[3])
        return n.outputs[0]

    def mix(a,b,factor):
        n = node('ShaderNodeMixRGB', 'Mix'); n.blend_type = 'MIX'; n.use_clamp = False
        connect(factor,n.inputs[0]);connect(a,n.inputs[1]);connect(b,n.inputs[2])
        return n.outputs[0]

    def add(a,b):
        n = node('ShaderNodeVectorMath','Add color'); n.operation='ADD'
        connect(a,n.inputs[0]);connect(b,n.inputs[1]);return n.outputs[0]

    def clamp(value):
        return math_node('MINIMUM',math_node('MAXIMUM',value,0),1)

    uv = node('ShaderNodeTexCoord','UV').outputs['UV']
    time = node('ShaderNodeValue','NRC time (seconds)')
    driver = time.outputs[0].driver_add('default_value').driver
    driver.expression='(frame-1)*base/fps'
    for name, data_path in [('fps','render.fps'),('base','render.fps_base')]:
        variable=driver.variables.new();variable.name=name;variable.type='SINGLE_PROP'
        variable.targets[0].id_type='SCENE';variable.targets[0].id=bpy.context.scene
        variable.targets[0].data_path=data_path
    seconds_output=time.outputs[0]

    def coords(tiling, speed=(0,0), clock=None):
        n=node('ShaderNodeVectorMath','UV tiling');n.operation='SCALE'
        connect(uv,n.inputs[0]);n.inputs[3].default_value=float(tiling)
        offset=node('ShaderNodeCombineXYZ','UV flow')
        for i in range(2):connect(math_node('MULTIPLY',seconds_output if clock is None else clock,float(speed[i])),offset.inputs[i])
        plus=node('ShaderNodeVectorMath','Flow + UV');plus.operation='ADD'
        connect(n.outputs[0],plus.inputs[0]);connect(offset.outputs[0],plus.inputs[1])
        return plus.outputs[0]

    def texture(image, vector, label):
        n=node('ShaderNodeTexImage',label);n.image=image;n.extension='REPEAT';n.interpolation='Linear'
        connect(vector,n.inputs['Vector']);return n

    def image(relative):
        img=bpy.data.images.load(str(assets/relative),check_existing=True)
        img.colorspace_settings.name='Non-Color';return img

    base=texture(base_image,uv,'Original diffuse')
    mask=texture(mask_image,uv,'Chroma coverage (R)')
    def channels(socket):
        n=node('ShaderNodeSeparateColor','Channels');n.mode='RGB';connect(socket,n.inputs[0]);return n.outputs
    coverage=clamp(channels(mask.outputs['Color'])[0])
    pattern=texture(image(preset['pattern']),coords(preset.get('tiling',1),preset.get('flow',[0,0])),'Flow pattern')
    weights=channels(pattern.outputs['Color'])
    denominator=math_node('MAXIMUM',math_node('ADD',weights[0],weights[1]),0.0001)
    palette=scale(add(scale(rgb(preset['mat_color_1']),weights[0]),scale(rgb(preset['mat_color_2']),weights[1])),math_node('DIVIDE',1,denominator))
    dot=node('ShaderNodeVectorMath','Linear luminance');dot.operation='DOT_PRODUCT'
    connect(base.outputs['Color'],dot.inputs[0]);dot.inputs[1].default_value=(0.2126,0.7152,0.0722)
    lightness=dot.outputs['Value']
    color=mix(base.outputs['Color'],scale(palette,lightness),coverage)
    ornament=preset.get('ornament') or {}
    if ornament.get('texture'):
        star_image=image(ornament['texture'])
        star=channels(texture(star_image,coords(ornament.get('tiling',4)),'Anchored ornament').outputs['Color'])
        theta=math_node('MULTIPLY',seconds_output,math.tau/4)
        sine=math_node('MULTIPLY',math_node('ABSOLUTE',math_node('SINE',theta)),1.1)
        cosine=math_node('MULTIPLY',math_node('ABSOLUTE',math_node('COSINE',theta)),1.1)
        # GLSL mix of scalar sine/cosine by packed G.
        reveal=math_node('ADD',math_node('MULTIPLY',sine,math_node('SUBTRACT',1,star[1])),math_node('MULTIPLY',cosine,star[1]))
        phase=math_node('MULTIPLY',clamp(reveal),3)
        colors=[rgb(c) for c in ornament.get('colors',[[1,1,1]]*4)]
        tint=mix(colors[0],colors[1],clamp(phase))
        tint=mix(tint,colors[2],clamp(math_node('SUBTRACT',phase,1)))
        tint=mix(tint,colors[3],clamp(math_node('SUBTRACT',phase,2)))
        threshold=math_node('MULTIPLY',star[2],math_node('SUBTRACT',reveal,star[0]))
        t=clamp(math_node('DIVIDE',math_node('SUBTRACT',threshold,0.01),0.04))
        smooth=math_node('MULTIPLY',math_node('MULTIPLY',t,t),math_node('SUBTRACT',3,math_node('MULTIPLY',2,t)))
        layer=scale(tint,math_node('MULTIPLY',math_node('MULTIPLY',smooth,float(ornament.get('intensity',0))),lightness))
        color=mix(color,layer,math_node('MULTIPLY',coverage,smooth))
        intensity=min(max(float(ornament.get('sparkle_intensity',0))/10,0),1)
        if intensity:
            glitter=channels(texture(star_image,coords(max(float(ornament.get('sparkle_density',8))*float(ornament.get('sparkle_tiling',1)),1),(0.0056,0.25),math_node('MODULO',seconds_output,4)),'Scrolling sparkle').outputs['Color'])
            angle=math_node('MULTIPLY',math_node('ADD',math_node('MULTIPLY',seconds_output,0.5),glitter[1]),math.tau)
            twinkle=math_node('ADD',0.55,math_node('MULTIPLY',0.45,math_node('SINE',angle)))
            brightness=math_node('MULTIPLY',math_node('MULTIPLY',glitter[2],twinkle),math_node('MULTIPLY',coverage,intensity))
            color=add(color,scale(mix(rgb([1,1,1]),palette,0.3),brightness))
    shader=node('ShaderNodeBsdfPrincipled','Blender chroma surface')
    connect(color,shader.inputs['Base Color']);connect(base.outputs['Alpha'],shader.inputs['Alpha'])
    shader.inputs['Roughness'].default_value=0.45
    shader.inputs['Coat Weight'].default_value=0.25
    output=node('ShaderNodeOutputMaterial','Output');links.new(shader.outputs[0],output.inputs[0])
    material['nrc_dynamic_chroma']=True
    # Lay out for inspection without depending on an external add-on.
    for i,n in enumerate(nodes):n.location=((i%8)*220,-(i//8)*180)


def build_scene(pmx_file, recipe_file):
    pmx=Path(pmx_file).resolve();recipe_path=Path(recipe_file).resolve();folder=recipe_path.parent
    recipe=json.loads(recipe_path.read_text(encoding='utf-8-sig'))
    preset=recipe['preset'];source_root=Path(recipe.get('model_root',folder))
    material_map=recipe['materials']
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import addon_utils
    addon_utils.enable('bl_ext.user_default.mmd_tools',default_set=True)
    bpy.ops.mmd_tools.import_model(filepath=str(pmx),scale=0.08,clean_model=True,remove_doubles=False,fix_ik_links=True)
    scene=bpy.context.scene;scene.render.fps=30;scene.render.fps_base=1
    scene.frame_start=1;scene.frame_end=120
    changed=[];portable={}
    for material in list(bpy.data.materials):
        name=getattr(getattr(material,'mmd_material',None),'name_j','') or material.name
        entry=material_map.get(name.lower())
        if not entry:continue
        url=entry['mask']
        mask=Path(url) if not url.startswith('/models/') else source_root/url[len('/models/'):]
        if not mask.is_absolute():mask=folder/mask
        if not mask.is_file():raise FileNotFoundError(f'Chroma mask missing: {mask}')
        base=next((n.image for n in material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and n.name=='mmd_base_tex'),None)
        if base is None:raise ValueError(f'No diffuse texture for {name}')
        target=folder/'Chroma'/mask.name;target.parent.mkdir(exist_ok=True)
        if mask.resolve()!=target.resolve():shutil.copy2(mask,target)
        mask_image=bpy.data.images.load(str(target),check_existing=True);mask_image.colorspace_settings.name='Non-Color'
        build_material(material,base,mask_image,preset,folder)
        changed.append(name);portable[name.lower()]={'mask':target.relative_to(folder).as_posix()}
    if not changed:raise ValueError('Selected model has no supported chroma material')
    recipe.pop('model_root',None);recipe['materials']=portable
    recipe['limits']=['Blender-only dynamic material; ordinary PMX stays original color.','UE refraction and full shader lighting are not reproduced.','Sparkle uses NRC preview approximation without random neighbour-cell lookup.']
    recipe_path.write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding='utf-8')
    scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=900;scene.render.resolution_percentage=100
    scene.view_settings.view_transform='Standard'
    points=[obj.matrix_world@Vector(p) for obj in scene.objects if obj.type=='MESH' and obj.find_armature() for p in obj.bound_box]
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)));high=Vector(tuple(max(p[i] for p in points) for i in range(3)));center=(low+high)/2
    bpy.ops.object.camera_add(location=(center.x,center.y-4,center.z))
    camera=bpy.context.object;camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=(high.z-low.z)*1.15;scene.camera=camera
    world=bpy.data.worlds.new('Chroma studio');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(0.32,0.32,0.32,1);scene.world=world
    bpy.ops.object.light_add(type='AREA',location=(2,-3,4));bpy.context.object.data.energy=400;bpy.context.object.data.shape='DISK';bpy.context.object.data.size=4
    scene.frame_set(1)
    scene['nrc_chroma_preset']=str(preset['id']);scene['nrc_chroma_materials']=json.dumps(changed)
    bpy.ops.file.pack_all()
    blend=pmx.with_name(pmx.stem+'-动态炫彩.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    (folder/'动态炫彩-使用说明.txt').write_text('打开同目录的动态炫彩.blend，播放或拖动时间轴查看效果。默认30fps，1—120帧。\n通过MMD Tools导入VMD后仍按场景帧率驱动；物理需另从静止缓冲帧构建并烘焙。\nPMX本身保留原色，不执行Blender节点。贴图已pack，Chroma与炫彩参数.json保留便于编辑。\n光泽是Blender近似，未复原UE折射和完整游戏shader。\n',encoding='utf-8')
    return {'revision':1,'blend':str(blend),'preset':preset['id'],'materials':changed,'packed':True,'fps':30,'limits':recipe['limits']}
