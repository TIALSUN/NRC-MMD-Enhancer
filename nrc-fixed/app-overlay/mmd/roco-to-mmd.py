"""导出一个 MMD 能直接用的 PMX：改名 → 层级重构 → T-pose → IK → 贴图 → 导出。

用法（PowerShell，按件导出，一次一个模型）：
  & 'D:\\Blender_\\blender.exe' -b -noaudio --factory-startup `
      --python <本文件> -- `
      --body  "<导出根>\\PC2\\SKM_PC2.gltf" `
      --clothes "<导出根>\\PC2\\Avatar\\Cup\\2071090101\\SKM_PC2_Cup_2071090101.gltf" `
      --out "<输出目录>\\PC2_Cup_2071090101.pmx"

默认行为：按 outputs\\MMD转换-骨骼映射.csv 改名、建 グルーブ/下半身、手臂改水平（T-pose）、
建 足ＩＫ/つま先ＩＫ，按材质名自动找 T_*_D.png 贴图，PMX 缩放 12.5（Blender 米 → MMD 单位）。
"""

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_physics import REVISION, build_native_plan, pmx_spring_parameters, validate_weighted_bones

import addon_utils
import bpy
from mathutils import Matrix, Vector

ADDON = "bl_ext.user_default.mmd_tools"
PROJECT = Path(__file__).resolve().parents[3]
DEFAULT_MAPPING = PROJECT / "outputs" / "MMD转换-骨骼映射.csv"
DEFAULT_ITEM_CONF = PROJECT / "workflow-tools" / "compatible-data" / "FASHION_ITEM_CONF.json"

# 骨名体系：miku = 左腕/左ひじ（Miku 标准）；suffix = 腕.L/ひじ.L（另一套常见命名）
NAMING_STYLE = "miku"


def bn(name: str) -> str:
    """按当前命名体系输出骨名（输入始终写 Miku 式）。"""
    if NAMING_STYLE != "suffix" or not name or name[0] not in ("左", "右"):
        return name
    if name == "両目":
        return name
    side = "L" if name[0] == "左" else "R"
    return f"{name[1:]}.{side}"

# 配置表 type_name -> 身体网格上对应部位的材质代号。
# 依据 FASHION_ITEM_CONF：连衣同时带 fashion_tops_tag 与 fashion_bottoms_tag，
# 所以一件连衣要同时替换身体自带的上衣(Cup)和裤子(Ps)。
SLOT_TOKENS = {
    "上衣": ["Cup"],
    "连衣": ["Cup", "Ps"],
    "下装": ["Ps"],
    "袜子": ["So"],
    "鞋子": ["Se"],
    "手饰": ["Ge"],
    "背包": ["Bg"],
    "帽子": ["Ht"],
    "头饰": ["Hi"],
    "面饰": ["Fi"],
    "口罩": ["Ms"],
    "头套": ["Hg", "Hp"],
    "玩偶服": ["Wh", "Cup", "Ps"],
    "包挂饰": [],
    "法杖": [],
}

# 游戏 morph target → MMD 标准表情名（这样主流 VMD 的表情轨才会驱动它）。
# 面板：EYE=目、MOUTH=口、EYEBROW=眉、OTHER=其他。
EXPRESSION_MAP = {
    # 整脸/口型（Fe_*）
    "Fe_jing": ("びっくり", "surprised", "EYE"),
    "Fe_huangluan": ("慌て", "panicked", "EYE"),
    "Fe_shangxin": ("困る", "troubled", "MOUTH"),
    "Fe_xiaodanxin": ("心配", "worried", "MOUTH"),
    "Fe_danu": ("怒り", "angry", "MOUTH"),
    "Fe_qi": ("ムッ", "pout", "MOUTH"),
    "Fe_daxi": ("笑い", "laugh", "MOUTH"),
    "Fe_zhongxi": ("にっこり", "smile", "MOUTH"),
    "Fe_ziyaxiao": ("笑顔", "grin", "MOUTH"),
    "Fe_ziyatong": ("牙", "teeth", "MOUTH"),
    "Fe_minzui": ("い", "i", "MOUTH"),
    "Fe_weizhangzui": ("あ", "a", "MOUTH"),
    "Fe_waizui": ("う", "u", "MOUTH"),
    "Fe_o": ("お", "o", "MOUTH"),
    # 单眼（Et_*_L / Et_*_R）
    "Et_biyan": ("まばたき", "blink", "EYE"),
    "Et_miyan": ("じと目", "narrow eyes", "EYE"),
    "Et_jinbi": ("閉眼", "closed eyes", "EYE"),
    "Et_jing": ("びっくり", "surprised", "EYE"),
    "Et_huangluan": ("慌て", "panicked", "EYE"),
    "Et_shangxin": ("困る", "troubled", "EYE"),
    "Et_danu": ("怒り", "angry", "EYE"),
    "Et_qi": ("ムッ", "pout", "EYE"),
    "Et_zhongxi": ("にっこり", "smile", "EYE"),
    "Et_ziyaxiao": ("笑顔", "grin", "EYE"),
    "Et_weizhang": ("微張", "slightly open", "EYE"),
}

# 大小写不敏感查找表（游戏在不同性别里大小写不一致：Fe_danu / FE_danu）
EXPRESSION_MAP_LOWER = {key.lower(): value for key, value in EXPRESSION_MAP.items()}

# 整脸 Fe_biyan/Fe_jinbi/Fe_miyan 实测不带动眼睛（眼白纹丝不动），不能当 MMD 的
# まばたき/閉眼/じと目。真正的闭眼是单眼 Et_*_L/R（会带动眼睑、盖住眼白），所以用
# 左右单眼合成“双眼”版本；游戏没有 え/ん 两个音也按顶点插值补上。
SYNTHETIC_EXPRESSIONS = {
    "まばたき": (("まばたき_L", 1.0), ("まばたき_R", 1.0)),
    "閉眼": (("閉眼_L", 1.0), ("閉眼_R", 1.0)),
    "じと目": (("じと目_L", 1.0), ("じと目_R", 1.0)),
    "え": (("い", 0.5), ("お", 0.5)),
    "ん": (("い", 0.4),),
}

# 表情面板里的推荐顺序（不在表里的按原顺序排在后面）
MORPH_ORDER = [
    "まばたき", "まばたき_L", "まばたき_R", "じと目", "じと目_L", "じと目_R",
    "笑い", "笑顔", "にっこり", "あ", "い", "う", "え", "お", "ん",
    "怒り", "ムッ", "困る", "心配", "びっくり", "慌て", "閉眼", "牙",
]

# 动作 VMD 里常见、但游戏没有的表情名 → 用本模型已有的表情顶上（做成「组表情」）
MORPH_ALIASES = {
    "ウィンク": ("まばたき_L", 1.0),
    "ウィンク右": ("まばたき_R", 1.0),
    "にこり": ("にっこり", 1.0),
    "あ２": ("あ", 1.0),
    "ワ": ("あ", 1.0),
    "口角上げ": ("笑い", 1.0),
    "笑い目": ("じと目", 1.0),
    "悲い目": ("困る", 1.0),
    "怒り左": ("怒り_L", 1.0),
    "怒り右": ("怒り_R", 1.0),
    "びっくり左": ("びっくり_L", 1.0),
    "びっくり右": ("びっくり_R", 1.0),
    "困る左": ("困る_L", 1.0),
    "困る右": ("困る_R", 1.0),
    "にこり左": ("にっこり_L", 1.0),
    "にこり右": ("にっこり_R", 1.0),
    "口角上げ左": ("にっこり_L", 1.0),
    "口角上げ右": ("にっこり_R", 1.0),
    "口角下げ": ("ムッ", 1.0),
    "口角下げ左": ("ムッ_L", 1.0),
    "口角下げ右": ("ムッ_R", 1.0),
    "口横広げ": ("あ", 1.0),
    "口横広げ左": ("あ", 1.0),
    "口横広げ右": ("あ", 1.0),
    "口横狭げ": ("い", 1.0),
    "口横狭げ左": ("い", 1.0),
    "口横狭げ右": ("い", 1.0),
    "口上": ("あ", 1.0),
    "口下": ("い", 1.0),
    "口左": ("う", 1.0),
    "口右": ("う", 1.0),
}

IK_BONES = [
    # (IK 骨名, 约束所在骨, 目标骨, 链长)
    ("左足ＩＫ", "左足首", "左つま先", 2),
    ("右足ＩＫ", "右足首", "右つま先", 2),
    ("左つま先ＩＫ", "左つま先", None, 1),
    ("右つま先ＩＫ", "右つま先", None, 1),
]


def log(*parts):
    print("[roco2mmd]", *parts, flush=True)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--body", required=True)
    parser.add_argument("--native-expressions-manifest", default=None,
                        help="原生表情 v1 来源清单；校验修复模型并登记静态原生表情预设")
    parser.add_argument("--clothes", action="append", default=[])
    parser.add_argument("--hair-mesh", default=None,
                        help="可选的帽子适配发型网格；替换身体默认 Hr，用于同源外观验证")
    parser.add_argument('--eye-avatar-id', type=int, default=None)
    parser.add_argument("--item", action="append", default=[],
                        help="按配置表里的物品 ID 穿戴（例 2071090101），自动决定替换哪些身体部位")
    parser.add_argument("--item-conf", default=str(DEFAULT_ITEM_CONF))
    parser.add_argument("--out", required=True)
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    parser.add_argument("--pmx-scale", type=float, default=12.5)
    parser.add_argument("--target-height", type=float, default=None,
                        help="按目标 PMX 总高自动换算 --pmx-scale（单位：MMD 单位）")
    parser.add_argument("--texture-root", default=None)
    parser.add_argument("--part-root", default=None,
                        help="服装部位网格所在根目录（默认同身体；身体来自带 morph 的库时用它指向原库）")
    parser.add_argument("--no-textures", action="store_true")
    parser.add_argument("--hair-color", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--brow-color", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--no-ik", action="store_true")
    parser.add_argument("--keep-native-arm-weights", action="store_true", help="保留原生辅助骨权重，用于接触修正对照")
    parser.add_argument("--no-eye-rewire", action="store_true",
                        help="不把眼睛顶点改绑到 左目/右目（默认改绑，便于视线轨生效）")
    parser.add_argument("--naming", choices=("miku", "suffix"), default="miku",
                        help="骨名体系：miku=左腕/左ひじ（默认），suffix=腕.L/ひじ.L")
    parser.add_argument("--physics", action="store_true",
                        help="生成 MMD 刚体与关节（裙摆 / 头发 / 背包）")
    parser.add_argument("--knee-limit", action="store_true", help="给 ひざ 加 X 轴 IK 限制（默认不加）")
    parser.add_argument("--arm-pose", choices=("a", "t"), default="a",
                        help="静止手臂姿势：a=保留模型的 A 字下垂（默认，与 MMD 惯例一致，"
                             "网格和骨本来就在这个姿势下对齐）；t=把手臂摆平（会把姿势烘进网格）")
    parser.add_argument("--keep-a-pose", action="store_true",
                        help="兼容旧参数，等价于 --arm-pose a")
    parser.add_argument("--double-sided", action="store_true")
    parser.add_argument("--no-strip", action="store_true",
                        help="保留身体自带的默认服装（默认会删掉被穿戴物品覆盖的部位）")
    parser.add_argument("--no-edge", action="store_true", help="不启用 PMX 輪郭")
    parser.add_argument("--dynamic-chroma", default=None)
    parser.add_argument("--tex-override", default=None,
                        help="贴图覆写映射 JSON：{ 材质名(去 .001 后缀) -> 覆写后的贴图路径 }（炫彩烘焙、眼窝柔化等）")
    parser.add_argument("--no-eye-socket-fix", action="store_true",
                        help="不柔化脸贴图的暗红眼窝（默认会柔化，去掉闭眼黑块）")
    parser.add_argument("--adduv2-vertex-color", action="store_true",
                        help="把顶点色写成追加UV2（供 MME 使用，默认关闭）")
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)
    if args.report is None:
        args.report = str(Path(args.out).with_suffix(".report.json"))
    return args


# ---------------------------------------------------------------- 骨架工具

def bone_world(arm, name):
    return arm.matrix_world @ arm.pose.bones[name].head


def rotate_about_point(arm, name, axis, angle, pivot):
    pose_bone = arm.pose.bones[name]
    matrix = arm.matrix_world @ pose_bone.matrix
    rotation = Matrix.Rotation(angle, 4, axis)
    offset = Matrix.Translation(pivot)
    world = offset @ rotation @ offset.inverted() @ matrix
    pose_bone.matrix = arm.matrix_world.inverted() @ world
    bpy.context.view_layer.update()


def straighten_segment(arm, upper, tip):
    """把 upper→tip 这一段摆成水平（消除 A-pose 的下垂），返回消除的角度。"""
    head = bone_world(arm, upper)
    tail = bone_world(arm, tip)
    current = tail - head
    if current.length < 1e-6:
        return None
    target = Vector((current.x, current.y, 0.0))
    if target.length < 1e-6:
        return None
    axis = current.cross(target)
    if axis.length < 1e-9:
        return 0.0
    angle = current.angle(target)
    rotate_about_point(arm, upper, axis.normalized(), angle, head)
    return math.degrees(angle)


def measure_arm_angle(arm, upper, tip):
    current = bone_world(arm, tip) - bone_world(arm, upper)
    horizontal = Vector((current.x, current.y, 0.0))
    if horizontal.length < 1e-9:
        return 90.0
    return math.degrees(math.atan2(abs(current.z), horizontal.length))


def bake_pose_into_meshes(meshes):
    """把当前姿势造成的形变写回网格顶点（Basis 与所有表情一起平移）。

    只改骨不改网格会让网格和骨错位：源模型的手臂是下垂 34° 的 A 字，
    把骨摆平而网格不动，手、手套、袖子就会挂在离自己骨骼 30cm 的地方，
    动作一转手指网格就被拉成尖锥。这里把姿势烘进网格，
    再 armature_apply 成新静止姿势，网格与骨才重新对齐。
    表情是相对 Basis 的位移，因此所有 shape key 必须同步平移，否则表情会被掰歪。
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    baked = {}
    for mesh in meshes:
        evaluated = mesh.evaluated_get(depsgraph)
        temporary = evaluated.to_mesh()
        baked[mesh.name] = [vertex.co.copy() for vertex in temporary.vertices]
        evaluated.to_mesh_clear()

    counts = {}
    for mesh in meshes:
        coordinates = baked.get(mesh.name)
        if coordinates is None or len(coordinates) != len(mesh.data.vertices):
            raise RuntimeError(f"{mesh.name} 烘焙后顶点数不一致，无法安全回写")
        keys = list(mesh.data.shape_keys.key_blocks) if mesh.data.shape_keys else []
        for index, coordinate in enumerate(coordinates):
            delta = coordinate - mesh.data.vertices[index].co
            if delta.length < 1e-9:
                continue
            mesh.data.vertices[index].co = coordinate
            for key in keys[1:]:
                key.data[index].co = key.data[index].co + delta
        mesh.data.update()
        counts[mesh.name] = len(coordinates)
    return counts


# ---------------------------------------------------------------- 各步骤

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable(ADDON, default_set=True)


def import_gltf(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [o for o in bpy.context.scene.objects if o not in before]


def uses_any_armature(obj, armatures):
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object in armatures:
            return True
    parent = obj.parent
    while parent is not None:
        if parent in armatures:
            return True
        parent = parent.parent
    return False


def merge_missing_bones(body_arm, clothing_armatures):
    """Keep accessory rest bones and ancestors before replacing their armature modifiers."""
    added = []
    for source in sorted(clothing_armatures, key=lambda a: a.name):
        if source == body_arm or source.get("nrc_skip_bone_merge"):
            continue
        missing = [b for b in source.data.bones if b.name not in body_arm.data.bones]
        if not missing:
            continue
        # Bone matrices are armature-local; clothing can have a different object transform.
        transform = body_arm.matrix_world.inverted_safe() @ source.matrix_world
        bpy.ops.object.select_all(action="DESELECT")
        body_arm.select_set(True)
        bpy.context.view_layer.objects.active = body_arm
        bpy.ops.object.mode_set(mode="EDIT")
        edit = body_arm.data.edit_bones
        for bone in missing:
            target = edit.new(bone.name)
            target.matrix = transform @ bone.matrix_local
            target.length = max((transform.to_3x3() @ (bone.tail_local - bone.head_local)).length, 0.00001)
            target.use_deform = bone.use_deform
            added.append(bone.name)
        for bone in missing:
            if bone.parent:
                edit[bone.name].parent = edit.get(bone.parent.name)
            edit[bone.name].use_connect = False
        bpy.ops.object.mode_set(mode="OBJECT")
    return added


def merge_into_body(body_arm, clothing_objects, strip_parts=True, strip_tokens=None):
    """把服装网格挂到身体骨架上并合并；返回被删除的服装骨架。

    只处理真正用新骨架蒙皮的网格，跳过 glTF 导入器自带的骨骼显示形状（Icosphere）。
    strip_tokens 由配置表给出（物品占哪些槽位）；不给时退化为从材质名推断。
    物品网格自带的皮肤（By）就是穿这套衣服时该显示的皮肤，必须保留。
    """
    import_armatures = {o for o in clothing_objects if o.type == "ARMATURE"}
    mesh_objects = [o for o in clothing_objects if o.type == "MESH" and uses_any_armature(o, import_armatures)]
    orphan_armatures = set(import_armatures)
    added_bones = merge_missing_bones(body_arm, import_armatures)
    if added_bones:
        log("保留服装附加骨:", added_bones)

    body_mesh = next((o for o in body_arm.children if o.type == "MESH"), None)
    if body_mesh is None:
        raise RuntimeError("身体骨架下没有网格")

    stripped = []
    item_tokens = set()
    for obj in mesh_objects:
        for material in obj.data.materials:
            if material is None:
                continue
            token = material_token(material.name)
            if token:
                item_tokens.add(token)
    if strip_parts and mesh_objects:
        wanted = set(strip_tokens) if strip_tokens is not None else item_tokens
        stripped = drop_materials(body_mesh, wanted)

    for obj in mesh_objects:
        world = obj.matrix_world.copy()
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE":
                modifier.object = body_arm
        obj.parent = body_arm
        obj.matrix_world = world

    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects:
        obj.select_set(True)
    body_mesh.select_set(True)
    bpy.context.view_layer.objects.active = body_mesh
    if mesh_objects:
        bpy.ops.object.join()

    removed = []
    for arm in orphan_armatures:
        if arm is body_arm or arm.name not in bpy.data.objects:
            continue
        removed.append(arm.name)
        bpy.data.objects.remove(arm, do_unlink=True)
    return body_mesh, removed, stripped, sorted(item_tokens)


def original_gltf_anchor(path, name):
    import struct
    from mathutils import Quaternion
    raw = Path(path).read_bytes()
    doc = json.loads(raw[20:20 + struct.unpack_from('<I', raw, 12)[0]]) if raw[:4] == b'glTF' else json.loads(raw)
    parents = {child: i for i, node in enumerate(doc['nodes']) for child in node.get('children', [])}
    def world(index):
        node = doc['nodes'][index]
        if 'matrix' in node:
            flat = node['matrix'];local = Matrix([flat[i:i+4] for i in range(0,16,4)]).transposed()
        else:
            q = node.get('rotation', [0,0,0,1])
            local = Matrix.LocRotScale(Vector(node.get('translation', [0,0,0])), Quaternion((q[3],q[0],q[1],q[2])), Vector(node.get('scale', [1,1,1])))
        return world(parents[index]) @ local if index in parents else local
    index = next(i for i,node in enumerate(doc['nodes']) if node.get('name') == name)
    conversion = Matrix.Rotation(math.pi / 2, 4, 'X')
    return conversion @ world(index) @ conversion.inverted()


def game_fit_matrix(value):
    from mathutils import Quaternion
    translation, rotation, scale = [[float(v) for v in field.split(',')] for field in value.split('|')]
    pitch, yaw, roll = [v * math.pi / 360 for v in rotation]
    sp,cp,sy,cy,sr,cr = math.sin(pitch),math.cos(pitch),math.sin(yaw),math.cos(yaw),math.sin(roll),math.cos(roll)
    qx,qy,qz,qw = cr*sp*sy-sr*cp*cy, -cr*sp*cy-sr*cp*sy, cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy
    matrix = Matrix.LocRotScale(Vector((translation[0]*.01,translation[2]*.01,translation[1]*.01)), Quaternion((qw,-qx,-qz,-qy)), Vector((scale[0],scale[2],scale[1])))
    conversion = Matrix.Rotation(math.pi/2,4,'X')
    return conversion @ matrix @ conversion.inverted()


def resolve_headwear_fit(headwear, hair, tables):
    kind=next((r for r in tables.get('HEADWEAR_TYPE_CONF',[]) if r['HeadWearName']==headwear),{})
    hairstyle=next((r for r in tables.get('HEADWEAR_HAIR_CONF',[]) if r['HairName']==hair),None)
    if not hairstyle:return None
    wear_type=kind.get('HeadWearType',0)
    info=next((r for r in hairstyle.get('Info',[]) if r.get('WearType',0)==wear_type),None)
    if not info:return None
    pair=next((r for r in tables.get('HEADWEAR_OFFSET_CONF',[]) if r['HeadWearName']==headwear),{})
    index=pair.get('HairName',[]).index(hair) if hair in pair.get('HairName',[]) else -1
    return {'bone':info['BoneName'],'wear_type':wear_type,'base':info['offset'],'extra':pair.get('Offset',[])[index] if index>=0 else None}


def prepare_wearable(armature, objects, part, report):
    """Preserve selected color IDs and bind authored static head accessories."""
    geometry_id = part.get('geometry_id', part['id'])
    asset_id = part.get('asset_id', part['id'])
    armatures = {o for o in objects if o.type == 'ARMATURE'}
    slot_match=re.match(r'(?:SKM|SM)_PC[123]_([A-Za-z]+)_',Path(part['mesh']).stem)
    slot=slot_match.group(1) if slot_match else Path(part['mesh']).parent.parent.name
    if 'PC3' in Path(part['mesh']).parts and slot in {'Bi','Mw'}:
        anchor = 'locator_right_hand' if slot == 'Mw' else 'Bone_Bag_root'
        mode = 'authored_upright_at_native_anchor'
        placement = Matrix.Translation(original_gltf_anchor(armature['nrc_body_source'], anchor).translation)
        if slot == 'Bi':
            bag = next((Path(p['mesh']).stem for p in report['parts'] if '_Bg_' in Path(p['mesh']).stem),None)
            fit_path = Path(__file__).with_name('BAGWEAR_OFFSET_CONF.json')
            fits = json.loads(fit_path.read_text(encoding='utf-8-sig')).get('RocoDataRows',{}) if fit_path.is_file() else {}
            fit = next((v for v in fits.values() if v['BagWearName'] == bag),None)
            if fit:
                anchor = 'Bone_Bag_20'
                placement = original_gltf_anchor(armature['nrc_body_source'],anchor) @ game_fit_matrix(fit['Offset'])
                mode = 'BAGWEAR_OFFSET_CONF'
            else:
                body = next(o for o in armature.children if o.type=='MESH')
                vertices = {i for p in body.data.polygons if body.data.materials[p.material_index] and material_token(body.data.materials[p.material_index].name)=='Bg' for i in p.vertices}
                if vertices:
                    points = [body.matrix_world @ body.data.vertices[i].co for i in vertices]
                    lo = Vector([min(p[i] for p in points) for i in range(3)]);hi = Vector([max(p[i] for p in points) for i in range(3)])
                    placement = Matrix.Translation(Vector((lo.x+.75*(hi.x-lo.x),hi.y+.015,lo.z+.65*(hi.z-lo.z))))
                else:
                    placement.translation += Vector((0,.18,0))
                mode = 'preview_bbox_fallback_requires_visual_review'
        names = {};roots=[]
        for source in armatures:
            for bone in list(source.data.bones):
                old = bone.name;new = f'A{part["id"]}_{old}';names[old]=new
                if bone.parent is None:roots.append(new)
                bone.name = new
        for obj in objects:
            if obj.type == 'MESH':
                for group in obj.vertex_groups:
                    if group.name in names:group.name=names[group.name]
        object_set = set(objects)
        for obj in objects:
            if obj.parent not in object_set:obj.matrix_world=placement @ obj.matrix_world
        part['attachment_anchor']=anchor;part['attachment_roots']=roots
        report.setdefault('independent_attachments',[]).append({'id':part['id'],'anchor':anchor,'mode':mode,'source_bone_name_map':names,'roots':roots,'placement_matrix':[list(r) for r in placement]})
    static = [o for o in objects if o.type == 'MESH' and not armatures]
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for index, mat in enumerate(obj.data.materials):
            if mat and geometry_id != asset_id and re.search(r'_' + re.escape(geometry_id) + r'(?:_OP)?(?:\.\d+)?$', mat.name):
                replacement = mat.copy()
                replacement.name = mat.name.replace('_' + geometry_id, '_' + asset_id)
                obj.data.materials[index] = replacement
    if static:
        slot = Path(part['mesh']).parent.parent.name
        bone_name = 'Bip001-Head' if slot in {'Hi', 'Fi', 'Ms', 'Hg', 'Hp'} else None
        if bone_name is None or bone_name not in armature.data.bones:
            raise RuntimeError(f'Static attachment requires verified anchor/offset: {part["id"]} {slot}')
        fit=None
        tables=globals().get('_HEADWEAR_TABLES')
        if tables is None:
            tables={}
            for table in ('HEADWEAR_TYPE_CONF','HEADWEAR_HAIR_CONF','HEADWEAR_OFFSET_CONF'):
                source=Path(__file__).with_name(table+'.json')
                tables[table]=list(json.loads(source.read_text(encoding='utf-8-sig')).get('RocoDataRows',{}).values()) if source.is_file() else []
            globals()['_HEADWEAR_TABLES']=tables
        hair_path=report.get('headwear_hair',{}).get('model') or report.get('hair_mesh')
        if hair_path:hair_name=Path(hair_path).stem
        else:
            body=next(o for o in armature.children if o.type=='MESH')
            hair_match=next((MATERIAL_PATTERN.match(SUFFIX_PATTERN.sub('',m.name)) for m in body.data.materials if m and material_token(m.name)=='Hr'),None)
            who=Path(armature['nrc_body_source']).parent.name
            hair_slot='Hr_Ht' if report.get('desired_has_hat') else 'Hr'
            hair_name=f'SKM_{who}_{hair_slot}_{hair_base_id(hair_match.group(3))}' if hair_match else ''
        fit=resolve_headwear_fit(Path(part['mesh']).stem,hair_name,tables)
        if fit:bone_name=fit['bone']
        anchor_source=armature['nrc_body_source']
        try:anchor=original_gltf_anchor(anchor_source,bone_name)
        except StopIteration:
            if not hair_path:raise RuntimeError(f'Headwear anchor unavailable: {bone_name}')
            anchor=original_gltf_anchor(hair_path,bone_name)
        if fit:
            anchor=anchor @ game_fit_matrix(fit['base'])
            if fit['extra']:anchor=anchor @ game_fit_matrix(fit['extra'])
        for obj in static:
            authored = obj.matrix_world.copy()
            # Blender reorients bone axes on import. Attachment uses original
            # glTF node axes, exactly as the game's/preview's bone parent does.
            obj.matrix_world = anchor @ authored
            group = obj.vertex_groups.new(name=bone_name)
            group.add(list(range(len(obj.data.vertices))), 1.0, 'REPLACE')
            modifier = obj.modifiers.new('NRC static attachment', 'ARMATURE');modifier.object = armature
        # merge_into_body recognizes meshes by the armature modifier.
        objects = list(objects) + [armature]
        report.setdefault('static_attachments', []).append({'id':part['id'], 'bone':bone_name, 'meshes':len(static),'headwear_fit':fit,'hair':hair_name})
    return objects


def strip_helper_objects(keep_armature, keep_meshes):
    """删除 glTF 导入器创建的辅助对象（骨骼显示用 Icosphere 及其隐藏集合）。"""
    removed = []
    special = bpy.data.collections.get("glTF_not_exported")
    if special is not None:
        for obj in list(special.objects):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(special)
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH" or obj in keep_meshes:
            continue
        if not uses_any_armature(obj, {keep_armature}):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return removed


def load_mapping(path):
    import csv
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source, target, action = row["源骨"], row["目标骨名"], row["动作"]
            if source == "（无）" or "/" in target or "（" in target:
                continue
            if not action.startswith("改名"):
                continue
            rows.append((source, target))
    return rows


def eye_model_id(character, avatar_id):
    gender = int(character[-1])
    index, remainder = divmod(int(avatar_id) - (gender * 10000000 + 3000000), 1000)
    if remainder or not 0 <= index < 15:
        raise ValueError(f'Invalid {character} eye avatar: {avatar_id}')
    return str(gender * 10000000 + 400001 + index * 100)


def modular_eye_target_fallbacks(available):
    return {f'Et_ziyaxiao_{side}': f'Et_zhayanxiao_{side}' for side in ('L','R')
            if f'Et_ziyaxiao_{side}' not in available and f'Et_zhayanxiao_{side}' in available}


def replace_modular_head(armature, body_mesh, part_root, character, avatar_id, report):
    model_id = eye_model_id(character, avatar_id)
    packaged = Path(__file__).parent / 'eye-expression-v1' / character
    face_id = '10200001' if character == 'PC1' else '20200001'
    entries = [('Fe', face_id), ('Et', model_id)]
    paths = []
    for slot, item in entries:
        path = packaged / f'SKM_{character}_{slot}_{item}.glb'
        manifest = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['model_sha256']:
            raise RuntimeError(f'Modular expression asset hash mismatch: {path}')
        paths.append(path)
    for slot, item in [('Es', '10500001' if character == 'PC1' else '20500001'), ('Er', '10600001' if character == 'PC1' else '20600001')]:
        path = find_part_mesh(part_root, character, slot, item)
        if path is None:
            raise RuntimeError(f'Modular head component missing: {slot} {item}')
        paths.append(path)
    # Whole-body Et includes the face and ears; replace the complete component set.
    removed = drop_materials(body_mesh, {'Et', 'Es', 'Fe', 'Er'})
    eye_targets = set()
    for path in paths:
        objects = import_gltf(str(path))
        if path.stem == f'SKM_{character}_Et_{model_id}':
            eye_targets = {key.name for obj in objects if obj.type == 'MESH' and obj.data.shape_keys for key in obj.data.shape_keys.key_blocks}
        for obj in objects:
            if obj.type != 'MESH':
                continue
            lr_slots = [i for i,m in enumerate(obj.data.materials) if m and '_Es_' in m.name and '_LR' in m.name]
            for old in lr_slots:
                source = obj.data.materials[old]
                indices = {}
                for side in ('L', 'R'):
                    mat = source.copy();mat.name = f'MI_PC_Es_A_{side}'
                    indices[side] = len(obj.data.materials);obj.data.materials.append(mat)
                for poly in obj.data.polygons:
                    if poly.material_index != old:
                        continue
                    x = sum((obj.matrix_world @ obj.data.vertices[v].co).x for v in poly.vertices)
                    poly.material_index = indices['L' if x > 0 else 'R']
                    for loop in poly.loop_indices:
                        obj.data.uv_layers.active.data[loop].uv.x *= 2
        merge_into_body(armature, objects, strip_parts=False)
    fallbacks = modular_eye_target_fallbacks(eye_targets)
    keys = body_mesh.data.shape_keys
    for destination, source in fallbacks.items():
        basis = keys.key_blocks[0]
        target = keys.key_blocks.get(destination)
        if target is None:
            target = body_mesh.shape_key_add(name=destination, from_mix=False)
        for index, point in enumerate(keys.key_blocks[source].data):
            target.data[index].co = point.co
    if fallbacks:
        report['eye_semantic_fallbacks'] = {'targets': fallbacks, 'note': 'Derived MMD grin uses authored blink-smile when this eye asset has no teeth-smile target. Distinct source targets and baked native presets remain preserved.'}
    report['eye_selection'] = {'avatar_id': avatar_id, 'model_id': model_id, 'components': [str(p) for p in paths], 'removed_materials': removed}


def item_geometry_ids(item_id, transforms):
    asset_id = str(transforms.get(str(item_id), item_id))
    base = asset_id[:-2] + '01' if len(asset_id) == 8 else asset_id[:-4] + '0101' if len(asset_id) == 10 else asset_id
    return asset_id, list(dict.fromkeys((asset_id, base)))


def resolve_item(item_id, item_conf, export_root):
    """按配置表解析一件物品：占哪些槽位、对应的网格文件在哪。"""
    import json

    conf_path = Path(item_conf)
    rows = json.loads(conf_path.read_text(encoding="utf-8-sig")).get("RocoDataRows", {})
    entry = rows.get(str(item_id))
    if entry is None:
        raise RuntimeError(f"配置表里没有物品 {item_id}（{conf_path}）")

    type_name = entry.get("type_name")
    tokens = SLOT_TOKENS.get(type_name)
    if tokens is None:
        raise RuntimeError(f"物品 {item_id} 的部位 {type_name!r} 还没有对应规则")

    gender = entry.get("gender")
    character = f"PC{gender}" if gender in (1, 2) else None
    transforms = {}
    transform_path = conf_path.with_name('ITEM_TRANS_CONF.json')
    if transform_path.is_file():
        trans_rows = json.loads(transform_path.read_text(encoding='utf-8-sig')).get('RocoDataRows', {})
        transforms = {str(v['id']): str(v['trans_id']) for v in trans_rows.values()}
    asset_id, geometry_ids = item_geometry_ids(item_id, transforms)
    root = Path(export_root).resolve()
    caches = globals().setdefault('_ITEM_MESH_INDEX', {})
    cache_key = str(root).casefold()
    if cache_key not in caches:
        index = {}
        for ext in ('gltf', 'glb'):
            for path in root.rglob(f'*.{ext}'):
                if path.name.startswith(('SKM_', 'SM_')) and path.parent.name.isdigit():
                    relative = path.relative_to(root)
                    index.setdefault((relative.parts[0], path.parent.name, path.name.split('_')[0]), []).append(path)
        caches[cache_key] = index
    index = caches[cache_key]
    candidates = []
    geometry_id = None
    for geometry_id in geometry_ids:
        for who in list(dict.fromkeys(([character] if character else []) + ['PC3', '*'])):
            for prefix in ('SKM', 'SM'):
                candidates = sorted(p for (g, model, kind), paths in index.items() if model == geometry_id and kind == prefix and (who == '*' or g == who) for p in paths)
                if candidates:
                    break
            if candidates:
                break
        if candidates:
            break
    if not candidates:
        raise RuntimeError(f"在 {export_root} 下找不到物品 {item_id} 的 SKM 网格")

    return {
        "id": str(item_id),
        "asset_id": asset_id,
        "geometry_id": geometry_id,
        "name": entry.get("name"),
        "type_name": type_name,
        "tokens": tokens,
        "gender": gender,
        "suits_id": entry.get("suits_id"),
        "toms_tag": entry.get("fashion_tops_tag"),
        "bottoms_tag": entry.get("fashion_bottoms_tag"),
        "mesh": str(candidates[0]),
        "conf": str(conf_path),
    }


def explicit_clothing_part(path):
    import struct,re
    path=Path(path);raw=path.read_bytes()
    doc=json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]]) if raw[:4]==b'glTF' else json.loads(raw)
    tokens=set()
    for material in doc.get('materials',[]):
        match=re.match(r'MI_[^_]+_([A-Za-z]+)_',material.get('name',''))
        if match and match.group(1) in set(PART_SLOTS)|{'Ht','Hi','Fi','Ms','Hg','Hp','Wh'}:tokens.add(match.group(1))
    match=re.match(r'(?:SKM|SM)_(PC[123])_([A-Za-z]+)_(\d+)',path.stem)
    item=match.group(3) if match else path.stem
    return {'slot':match.group(2) if match else 'explicit','id':item,'asset_id':item,'geometry_id':item,'mesh':str(path),'tokens':sorted(tokens),'source':'explicit source mesh'}


def wardrobe_strip_tokens(selected):
    result={BODY_SKIN_TOKEN}|set(PART_SLOTS)|set(selected)
    if set(selected)&{'Ht','Hi'}:result.update({'Ht','Hi'})
    return result


def replace_default_hat_hair(armature, body_mesh, character, has_hat, report):
    match=next((MATERIAL_PATTERN.match(SUFFIX_PATTERN.sub('',m.name)) for m in body_mesh.data.materials if m and material_token(m.name)=='Hr'),None)
    if not match:
        raise RuntimeError('Cannot determine native default hair for headwear replacement')
    base=hair_base_id(match.group(3));slot='Hr_Ht' if has_hat else 'Hr'
    path=Path(__file__).parent/'eye-expression-v1'/character/f'SKM_{character}_{slot}_{base}.glb'
    manifest=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['model_sha256']:raise RuntimeError('Default headwear hair hash mismatch')
    drop_materials(body_mesh,{'Hr'});merge_into_body(armature,import_gltf(str(path)),strip_parts=False)
    report['headwear_hair']={'has_hat':has_hat,'model':str(path),'native_presets':len(manifest['native_presets'])}


def resolve_requested_items(ids, item_conf, export_root):
    import json
    configured = json.loads(Path(item_conf).read_text(encoding='utf-8-sig')).get('RocoDataRows', {})
    resolved, skipped = [], []
    for item_id in ids:
        try:
            resolved.append(resolve_item(item_id, item_conf, export_root))
        except RuntimeError as exc:
            if str(item_id) in configured:
                raise RuntimeError(f'Configured wardrobe item cannot be exported: {item_id}: {exc}') from exc
            skipped.append({'id': str(item_id), 'reason': str(exc)})
    return resolved, skipped


def default_part_ids(base_mesh):
    """从 SKM_PC2 的材质名读出「默认款」各槽位的物品 ID（MI_PC2_Cup_20700101 -> Cup: 20700101）。"""
    ids = {}
    for material in base_mesh.data.materials:
        if material is None:
            continue
        match = MATERIAL_PATTERN.match(SUFFIX_PATTERN.sub("", material.name))
        if not match:
            continue
        _, token, item = match.groups()
        if token in PART_SLOTS and token not in ids:
            ids[token] = item
    return ids


def find_part_mesh(export_root, character, slot, item):
    """找某个槽位某 ID 的部位网格（网格可能不在同 ID 目录里，所以全槽位递归找）。

    兼容 .gltf（UModel 库）与 .glb（CUE4Parse 带 morph 的库）两种后缀。
    """
    avatar = Path(export_root) / character / "Avatar" / slot
    if not avatar.is_dir():
        return None
    for pattern in (f"{item}/SKM_*.gl*", f"**/SKM_*_{slot}_{item}.gl*", f"**/SKM_*_{item}.gl*"):
        found = sorted(avatar.glob(pattern))
        if found:
            return found[0]
    return None


def rename_bones(armature, pairs):
    bones = armature.data.bones
    done, missing = [], []
    for source, target in pairs:
        bone = bones.get(source)
        if bone is None:
            missing.append(source)
            continue
        if bone.name == target:
            done.append((source, target))
            continue
        bone.name = target
        if bones.get(target) is not None:
            done.append((source, target))
        else:
            missing.append(source)
    return done, missing


def sync_vertex_groups(mesh, pairs):
    """Blender 改名通常会同步顶点组，这里再显式保证一次。"""
    mapping = dict(pairs)
    changed = 0
    for group in mesh.vertex_groups:
        if group.name in mapping:
            group.name = mapping[group.name]
            changed += 1
    return changed


def restructure(armature):
    """建 グルーブ/下半身 并把 腰、足.* 接回标准层级。"""
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    edit = armature.data.edit_bones
    created = []

    center = edit.get("センター")
    waist = edit.get("腰")
    if center is None or waist is None:
        bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError("缺少 センター 或 腰，改名步骤可能失败")

    if edit.get("グルーブ") is None:
        groove = edit.new("グルーブ")
        groove.head = center.head.copy()
        groove.tail = center.tail.copy()
        groove.parent = center
        groove.use_connect = False
        created.append("グルーブ")
    else:
        groove = edit["グルーブ"]
    waist.parent = groove

    if edit.get("下半身") is None:
        lower = edit.new("下半身")
        lower.head = waist.head.copy()
        lower.tail = waist.head + Vector((0.0, 0.0, -0.12))
        lower.parent = waist
        lower.use_connect = False
        created.append("下半身")
    else:
        lower = edit["下半身"]

    for name in (bn("左足"), bn("右足")):
        bone = edit.get(name)
        if bone is not None and bone.parent is not lower:
            bone.parent = lower
            bone.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    return created


EYE_MATERIAL_TOKENS = ("MI_PC_Es_A_L", "MI_PC_Es_A_R")


def add_standard_bones(armature, report):
    """补準標準骨：肩P / 腕捩 / 手捩 / 足先EX / 両目+左右目 / 足D 变形链。"""
    from mathutils import Vector

    if armature.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    edit = armature.data.edit_bones
    created = []

    def make(name, head, tail, parent):
        bone = edit.new(name)
        bone.head = head
        bone.tail = tail
        bone.parent = parent
        bone.use_connect = False
        created.append(name)
        return bone

    for side in ("左", "右"):
        shoulder, upper = edit.get(bn(f"{side}肩")), edit.get(bn(f"{side}腕"))
        elbow, wrist = edit.get(bn(f"{side}ひじ")), edit.get(bn(f"{side}手首"))
        ankle, toe = edit.get(bn(f"{side}足首")), edit.get(bn(f"{side}つま先"))
        ik = edit.get(bn(f"{side}足ＩＫ"))
        if shoulder is not None and edit.get(bn(f"{side}肩P")) is None:
            holder = make(bn(f"{side}肩P"), shoulder.head.copy(), shoulder.tail.copy(), shoulder.parent)
            shoulder.parent = holder
        if upper is not None and elbow is not None and edit.get(bn(f"{side}腕捩")) is None:
            controller = make(bn(f"{side}腕捩"), upper.head.copy(), elbow.head.copy(), upper)
            elbow.parent = controller
        if elbow is not None and wrist is not None and edit.get(bn(f"{side}手捩")) is None:
            controller = make(bn(f"{side}手捩"), elbow.head.copy(), wrist.head.copy(), elbow)
            wrist.parent = controller
        if ankle is not None and toe is not None and edit.get(bn(f"{side}足先EX")) is None:
            holder = make(bn(f"{side}足先EX"), toe.head.copy(), toe.tail.copy(), ankle)
        parent = edit.get(bn(f"{side}足")).parent if edit.get(bn(f"{side}足")) else None
        for dname, source in ((bn(f"{side}足D"), bn(f"{side}足")), (bn(f"{side}ひざD"), bn(f"{side}ひざ")),
                              (bn(f"{side}足首D"), bn(f"{side}足首")), (bn(f"{side}つま先D"), bn(f"{side}つま先"))):
            source_bone = edit.get(source)
            if parent is not None and source_bone is not None and edit.get(dname) is None:
                parent = make(dname, source_bone.head.copy(), source_bone.tail.copy(), parent)

    # Highlight IDs are reversed between PC1 and PC2; never use them as eye pivots.
    # Native Eye_SkinJNT pivots sit behind the matching eye surface on both bodies.
    head = edit.get("頭")
    left_eye = edit.get("Bone_Left_Eye_SkinJNT")
    right_eye = edit.get("Bone_Right_Eye_SkinJNT")
    if head is not None and left_eye is not None and right_eye is not None and edit.get(bn("両目")) is None:
        center = (left_eye.head + right_eye.head) / 2
        both = make(bn("両目"), center.copy(), center + Vector((0.0, 0.0, -0.01)), head)
        forward = (center - head.head).normalized() * 0.01 if (center - head.head).length else Vector((0.0, -0.01, 0.0))
        make(bn("左目"), left_eye.head.copy(), left_eye.head + forward, both)
        make(bn("右目"), right_eye.head.copy(), right_eye.head + forward, both)

    bpy.ops.object.mode_set(mode="OBJECT")
    return created


def native_twist_coefficients(segment):
    # Native sampled quaternion ranges: upperarm _2/_1 ~= 0.5;
    # forearm _2/_1 ~= 2.0. MMD approximation, not a reconstruction of UE solvers.
    return (1.0, 0.5) if segment == "upperarm" else (0.5, 1.0)


def harmonize_arm_influences(weights, projection, source_names, parent, twist):
    """Use the same longitudinal twist field for skin and clothing."""
    result = dict(weights)
    total = sum(result.pop(name, 0.0) for name in source_names)
    if total <= 1e-12:
        return result
    non_arm = [name for name, value in result.items() if value > 1e-12]
    factor = max(0.0, min(1.0, projection))
    if len(non_arm) >= 3:
        # PMX stores at most four influences.  Folding the arm domain into
        # its parent still keeps the total weight and avoids discarding mass.
        target = parent if len(non_arm) == 3 else max(non_arm, key=result.get)
        result[target] = result.get(target, 0.0) + total
        return result
    if total * (1.0 - factor) > 1e-12:
        result[parent] = total * (1.0 - factor)
    if total * factor > 1e-12:
        result[twist] = total * factor
    return result


def conform_arm_skinning(armature, meshes):
    changes = []
    for side, suffix in (("左", "l"), ("右", "r")):
        for segment, start, end, twist_name in (("upperarm", f"{side}腕", f"{side}ひじ", f"{side}腕捩"),
                                                 ("forearm", f"{side}ひじ", f"{side}手首", f"{side}手捩")):
            parent, distal, twist = bn(start), bn(end), bn(twist_name)
            if any(armature.data.bones.get(name) is None for name in (parent, distal, twist)):
                continue
            head = armature.data.bones[parent].head_local
            axis = armature.data.bones[distal].head_local - head
            length2 = axis.length_squared
            if length2 < 1e-10:
                continue
            count = 0
            for mesh in meshes:
                source = {g.name for g in mesh.vertex_groups if re.fullmatch(rf"Bone_{segment}_{suffix}_[0-9]+", g.name)} | {parent, twist}
                if not any(mesh.vertex_groups.get(name) for name in source):
                    continue
                for name in (parent, twist):
                    if mesh.vertex_groups.get(name) is None:
                        mesh.vertex_groups.new(name=name)
                names = {g.index: g.name for g in mesh.vertex_groups}
                transform = armature.matrix_world.inverted_safe() @ mesh.matrix_world
                for vertex in mesh.data.vertices:
                    weights = {names[g.group]: g.weight for g in vertex.groups}
                    total = sum(weights.get(name, 0.0) for name in source)
                    if total <= 1e-12:
                        continue
                    position = transform @ vertex.co
                    projection = (position - head).dot(axis) / length2
                    result = harmonize_arm_influences(weights, projection, source, parent, twist)
                    for name in source:
                        if name in weights:
                            mesh.vertex_groups[name].remove([vertex.index])
                    for name in (parent, twist):
                        if result.get(name, 0.0) > 1e-12:
                            mesh.vertex_groups[name].add([vertex.index], result[name], "REPLACE")
                    count += 1
            changes.append({"segment": segment, "side": side, "vertices": count, "parent": parent, "twist": twist})
    return {"revision": 1, "segments": changes,
            "note": "MMD-derived coherent skin/cloth twist field; original GLB weights remain unchanged."}


def inset_covered_arm_skin(armature, meshes, report):
    """Inset only skin with a garment hit along the outward bone radial.

    Proximity alone does not establish coverage (open sleeves and shoulder
    ornaments can be close to bare arms). Never delete source skin faces.
    """
    from mathutils.bvhtree import BVHTree
    segment_bones = {}
    for side, letter in [("左", "l"), ("右", "r")]:
        for names, ends in [
            ([bn(side+"腕"), bn(side+"腕捩"), *[f"Bone_upperarm_{letter}_{i}" for i in range(1,5)]], (bn(side+"腕"),bn(side+"ひじ"))),
            ([bn(side+"ひじ"), bn(side+"手捩"), *[f"Bone_forearm_{letter}_{i}" for i in range(1,5)]], (bn(side+"ひじ"),bn(side+"手首"))),
        ]:
            for name in names: segment_bones[name] = ends
    summary = []
    for mesh in meshes:
        names = {g.index:g.name for g in mesh.vertex_groups}
        candidates=set();cloth_faces=[]
        for face in mesh.data.polygons:
            mat=mesh.data.materials[face.material_index]
            if mat is None: continue
            arm_weight=sum(g.weight for i in face.vertices for g in mesh.data.vertices[i].groups if names[g.group] in segment_bones)
            if material_token(mat.name)==BODY_SKIN_TOKEN and arm_weight>.15:
                candidates.update(face.vertices)
            elif material_token(mat.name)=="Cup" and arm_weight>.2:
                cloth_faces.append(tuple(face.vertices))
        if not candidates or not cloth_faces: continue
        tree=BVHTree.FromPolygons([v.co.copy() for v in mesh.data.vertices],cloth_faces,all_triangles=False)
        to_mesh=mesh.matrix_world.inverted_safe() @ armature.matrix_world
        offsets={};transfers=0
        for index in candidates:
            vertex=mesh.data.vertices[index]
            segments={}
            for group in vertex.groups:
                segment=segment_bones.get(names[group.group])
                if segment: segments[segment]=segments.get(segment,0)+group.weight
            if not segments: continue
            head_name,tail_name=max(segments,key=segments.get)
            if head_name not in armature.data.bones or tail_name not in armature.data.bones:continue
            head=to_mesh @ armature.data.bones[head_name].head_local
            axis=to_mesh @ armature.data.bones[tail_name].head_local-head
            if axis.length_squared<1e-10:continue
            projection=max(0,min(1,(vertex.co-head).dot(axis)/axis.length_squared))
            radial=vertex.co-(head+axis*projection)
            if radial.length<1e-5:continue
            direction=radial.normalized()
            hit,normal,face_index,distance=tree.ray_cast(vertex.co-direction*.002,direction,.022)
            if hit is None or distance<.001:continue
            offsets[index]=-direction*.003
            # Use the locally covering triangle, never an unrelated nearby cuff.
            cover_index=min(cloth_faces[face_index],key=lambda i:(mesh.data.vertices[i].co-hit).length_squared)
            cover_weights=[(names[g.group],g.weight) for g in mesh.data.vertices[cover_index].groups if g.weight>1e-6]
            if cover_weights:
                for group in list(vertex.groups):mesh.vertex_groups[group.group].remove([index])
                for name,weight in cover_weights:
                    group=mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
                    group.add([index],weight,"REPLACE")
                transfers+=1
        blocks=mesh.data.shape_keys.key_blocks if mesh.data.shape_keys else ()
        for index,offset in offsets.items():
            mesh.data.vertices[index].co+=offset
            for block in blocks:block.data[index].co+=offset
        mesh.data.update()
        summary.append({"mesh":mesh.name,"covered_surface_vertices":len({i for face in cloth_faces for i in face}),"removed_hidden_skin_faces":0,"moved_vertices":len(offsets),"weight_transfers":transfers,"maximum_offset_m":.003 if offsets else 0})
    report["covered_arm_skin_inset"]={"revision":2,"coverage":"outward radial garment raycast; preserve skin faces","meshes":summary,"removed_hidden_skin_faces":0,"moved_vertices":sum(r["moved_vertices"] for r in summary),"weight_transfers":sum(r["weight_transfers"] for r in summary)}
    return report["covered_arm_skin_inset"]


def link_twist_bones(armature, report):
    links = []
    for side, suffix in (("左", "l"), ("右", "r")):
        for control, segment in ((f"{side}腕捩", "upperarm"), (f"{side}手捩", "forearm")):
            control = bn(control)
            controller = armature.pose.bones.get(control)
            if controller is None:
                continue
            controller.mmd_bone.enabled_fixed_axis = True
            controller.mmd_bone.fixed_axis = (controller.bone.tail_local - controller.bone.head_local).normalized().xzy
            for index, influence in enumerate(native_twist_coefficients(segment), 1):
                target = f"Bone_{segment}_{suffix}_{index}"
                pose_bone = armature.pose.bones.get(target)
                if pose_bone is None:
                    continue
                mmd_bone = pose_bone.mmd_bone
                mmd_bone.has_additional_rotation = True
                mmd_bone.additional_transform_bone = control
                mmd_bone.additional_transform_influence = influence
                mmd_bone.is_additional_transform_dirty = True
                links.append({"bone": target, "grant": control, "influence": influence})
    return links


def activate_leg_deform_controls(armature, meshes):
    """D chain follows IK/FK bones; native weighted helpers follow D controls."""
    links, transfers = [], []
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    edit = armature.data.edit_bones
    for side in ("左", "右"):
        mapping = {bn(f"{side}{base}"): bn(f"{side}{base}D") for base in ("足", "ひざ", "足首", "つま先")}
        # Do not reparent original FK joints: those are the IK solver chain.
        for bone in list(edit):
            if bone.name in mapping or bone.name in mapping.values():
                continue
            if bone.parent and bone.parent.name in mapping:
                replacement = edit.get(mapping[bone.parent.name])
                if replacement is not None:
                    bone.parent = replacement
        ex = edit.get(bn(f"{side}足先EX"))
        if ex and edit.get(bn(f"{side}つま先D")):
            ex.parent = edit[bn(f"{side}つま先D")]
    bpy.ops.object.mode_set(mode="OBJECT")
    for side in ("左", "右"):
        for base in ("足", "ひざ", "足首", "つま先"):
            source, target = bn(f"{side}{base}"), bn(f"{side}{base}D")
            bone = armature.pose.bones.get(target)
            if not bone or not armature.pose.bones.get(source):
                continue
            prop = bone.mmd_bone
            prop.has_additional_rotation = True
            prop.has_additional_location = True
            prop.additional_transform_bone = source
            prop.additional_transform_influence = 1.0
            prop.is_additional_transform_dirty = True
            links.append({"bone": target, "grant": source, "influence": 1.0})
            # Direct skin weights also move to the deformation chain.
            destination = bn(f"{side}足先EX") if base == "つま先" else target
            for mesh in meshes:
                src = mesh.vertex_groups.get(source)
                if not src:
                    continue
                dst = mesh.vertex_groups.get(destination) or mesh.vertex_groups.new(name=destination)
                moved = []
                for vertex in mesh.data.vertices:
                    weight = next((g.weight for g in vertex.groups if g.group == src.index), 0.0)
                    if weight > 0:
                        dst.add([vertex.index], weight, "REPLACE")
                        moved.append(vertex.index)
                if moved:
                    src.remove(moved)
                    transfers.append({"source": source, "target": destination, "vertices": len(moved)})
    return {"links": links, "weight_transfers": transfers}


def rewire_eyes(mesh, armature, report):
    """把眼睛（Es 材质）顶点从 头/高光骨 改绑到 左目/右目，让视线轨真的能转眼。"""
    if armature.data.bones.get(bn("左目")) is None or armature.data.bones.get(bn("右目")) is None:
        report["eye_reweight"] = "没有视线骨，跳过"
        return []
    slots = {}
    for index, material in enumerate(mesh.data.materials):
        if material is None:
            continue
        name = SUFFIX_PATTERN.sub("", material.name)
        if name in EYE_MATERIAL_TOKENS:
            slots[index] = bn("左目") if name.endswith("_L") else bn("右目")
    if not slots:
        report["eye_reweight"] = "没有找到眼睛材质槽"
        return []
    for group_name in (bn("左目"), bn("右目")):
        if mesh.vertex_groups.get(group_name) is None:
            mesh.vertex_groups.new(name=group_name)
    moved = {}
    for polygon in mesh.data.polygons:
        group_name = slots.get(polygon.material_index)
        if group_name is None:
            continue
        for vertex_index in polygon.vertices:
            vertex = mesh.data.vertices[vertex_index]
            for element in list(vertex.groups):
                mesh.vertex_groups[element.group].remove([vertex_index])
            mesh.vertex_groups[group_name].add([vertex_index], 1.0, "REPLACE")
            moved[group_name] = moved.get(group_name, 0) + 1
    report["eye_reweight"] = moved
    return [{"vertex_group": name, "vertices": count} for name, count in moved.items()]


def build_ik(armature, knee_limit):
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    created = []
    bpy.ops.object.mode_set(mode="EDIT")
    edit = armature.data.edit_bones
    for ik_name, ankle, _, _ in IK_BONES:
        ik_name, ankle = bn(ik_name), bn(ankle)
        if edit.get(ik_name) is not None:
            continue
        source = edit.get(ankle)
        if source is None:
            continue
        bone = edit.new(ik_name)
        bone.head = source.head.copy()
        bone.tail = source.tail.copy()
        # Feet remain planted when the center moves; toe targets follow foot IK.
        side = "左" if ik_name == bn("左つま先ＩＫ") else "右"
        bone.parent = (edit.get(bn(f"{side}足ＩＫ")) if "つま先" in ik_name else None) or edit.get("全ての親")
        bone.use_connect = False
        created.append(ik_name)
    bpy.ops.object.mode_set(mode="OBJECT")

    root = armature.parent
    if root is not None and hasattr(root, "mmd_root"):
        root.mmd_root.ik_loop_factor = 1

    for ik_name, ankle, _, chain in IK_BONES:
        ik_name, ankle = bn(ik_name), bn(ankle)
        pose_bone = armature.pose.bones.get(ankle)
        if pose_bone is None or armature.pose.bones.get(ik_name) is None:
            continue
        for existing in list(pose_bone.constraints):
            if existing.type == "IK" and existing.subtarget == ik_name:
                pose_bone.constraints.remove(existing)
        constraint = pose_bone.constraints.new("IK")
        constraint.name = f"mmd_ik_{ik_name}"
        constraint.target = armature
        constraint.subtarget = ik_name
        constraint.chain_count = chain
        constraint.use_tail = False
        constraint.iterations = 40
    if knee_limit:
        for name in (bn("左ひざ"), bn("右ひざ")):
            bone = armature.pose.bones.get(name)
            if bone is not None:
                bone.use_ik_limit_x = True
                bone.ik_min_x = 0.0
                bone.ik_max_x = 2.8
    return created


MATERIAL_PATTERN = re.compile(r"^MI_([A-Za-z0-9]+)_([A-Za-z]+)_(\d+)$")
SUFFIX_PATTERN = re.compile(r"\.\d{3}$")
TOKEN_PATTERN = re.compile(r"^MI_([A-Za-z0-9]+)_([A-Za-z]+)(?:_|$)")


def material_token(name):
    """从材质名取部位代号：MI_PC2_Cup_2071090101 -> Cup（MI_PC_Es_A_L -> Es）。"""
    match = TOKEN_PATTERN.match(SUFFIX_PATTERN.sub("", name))
    return match.group(2) if match else None


# SKM_PC2 是「没衣服」时的那份整体：它自带一整套默认装，皮肤(By)也合成在这一块里。
# 实测每件衣服的网格自己带它露出来的那块皮肤：
#   袜子 SKM_PC2_So_21000101 带 By 皮肤 y 0.215~0.699（小腿到膝）
#   手套 SKM_PC2_Ge_20800101 带 By 皮肤 y 0.787~0.953（前臂）
#   连衣 2071090101 带 By 皮肤 y 0.909~1.307（上臂/肩/颈）+ Ps 层（躯干与大腿）
# 所以穿衣服时正确的做法是：用各部位网格拼身体，皮肤由衣服自带；SKM_PC2 只保留头部
# （脸/眼/眉/头发/头饰），它的 By 整块皮肤和其它槽位都不参与。
BODY_SKIN_TOKEN = "By"
PART_SLOTS = ["Cup", "Ps", "So", "Se", "Ge", "Bg"]          # 由部位网格提供（含各自皮肤）
HEAD_TOKENS = {"Et", "Es", "Br", "Hr", "Hi"}                 # 默认从 SKM_PC2 保留的头部


def neck_skin_faces(mesh_obj):
    """Find the upper-neck By island even when glTF merges By materials."""
    mesh = mesh_obj.data
    by_faces = {face.index for face in mesh.polygons
                if mesh.materials[face.material_index] is not None
                and material_token(mesh.materials[face.material_index].name) == BODY_SKIN_TOKEN}
    by_vertex = {}
    for face_id in by_faces:
        for vertex in mesh.polygons[face_id].vertices:
            by_vertex.setdefault(vertex, set()).add(face_id)
    result = set()
    remaining = set(by_faces)
    while remaining:
        component = set()
        pending = [remaining.pop()]
        while pending:
            face_id = pending.pop()
            if face_id in component:
                continue
            component.add(face_id)
            for vertex in mesh.polygons[face_id].vertices:
                adjacent = by_vertex[vertex] & remaining
                pending.extend(adjacent)
                remaining.difference_update(adjacent)
        vertices = {vertex for face_id in component
                    for vertex in mesh.polygons[face_id].vertices}
        coords = [mesh_obj.matrix_world @ mesh.vertices[vertex].co for vertex in vertices]
        if (min(point.z for point in coords) > 1.24
                and max(point.z for point in coords) > 1.34
                and max(abs(point.x) for point in coords) < .2):
            result.update(component)
    return result


def drop_materials(mesh_obj, tokens, preserve_upper_neck=False):
    """按材质槽删掉指定部位的面，然后重建材质列表并重映射面索引。"""
    import bmesh

    mesh = mesh_obj.data
    preserve = neck_skin_faces(mesh_obj) if preserve_upper_neck else set()
    drop = [i for i, material in enumerate(mesh.materials)
            if material is not None and material_token(material.name) in tokens]
    if not drop:
        return []

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    faces = [face for face in bm.faces
             if face.material_index in drop and face.index not in preserve]
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    bm.to_mesh(mesh)
    bm.free()

    used_indices = {polygon.material_index for polygon in mesh.polygons}
    kept = [material for i, material in enumerate(mesh.materials) if i in used_indices]
    remap = {}
    next_index = 0
    for i, material in enumerate(mesh.materials):
        if i not in used_indices:
            continue
        remap[i] = next_index
        next_index += 1
    removed = [mesh.materials[i].name for i in drop]
    # materials.clear() 会把所有面的材质索引清零，所以先记下旧索引
    old_indices = [polygon.material_index for polygon in mesh.polygons]
    mesh.materials.clear()
    for material in kept:
        mesh.materials.append(material)
    for polygon, old in zip(mesh.polygons, old_indices):
        polygon.material_index = remap.get(old, 0)
    mesh.update()
    return removed


def find_texture(root, character, slot, item):
    """在槽位目录下递归找 D 贴图：优先 ID 目录，其次该槽的基础目录。"""
    avatar = Path(root) / character / "Avatar" / slot
    if avatar.is_dir():
        if item:
            exact = sorted(avatar.glob(f"{item}/Tex/T_{character}_{slot}_{item}_D.png"))
            if exact:
                return exact[0]
            any_dir = sorted(avatar.glob(f"**/T_{character}_{slot}_{item}_D.png"))
            if any_dir:
                return any_dir[0]
        else:
            candidates = sorted(avatar.glob(f"**/T_*_{slot}_*_D.png"))
            if len(candidates) == 1:
                return candidates[0]
    if item:
        # 服装部件的整套贴图放在物品自己的目录下（例如 Cup/2071090101/Tex/T_PC2_Ps_2071090101_D.png）
        elsewhere = sorted((Path(root) / character / "Avatar").glob(f"**/T_{character}_{slot}_{item}_D.png"))
        if elsewhere:
            return elsewhere[0]
    return None


# 沙龙预设：同一发型/眉毛有 5 档颜色（色号取自 SALON_ITEM_CONF.json，type=1 发型 / type=2 眉毛）。
# 默认是「初始发型的棕色」与「初始眉毛」，也就是用户要的预设。
COLOR_PRESETS = {
    1: ("棕", "563027FF"),
    2: ("黑", "3E3F40FF"),
    3: ("银", "93A6ABFF"),
    4: ("金", "9D7447FF"),
    5: ("红", "671D2AFF"),
}
DEFAULT_COLOR_ID = 1


def hair_base_id(material_id):
    """8 位物品 ID 的变体在末两位：10100005 → 10100001（与预览器 getBaseId 同规则）。"""
    text = str(material_id)
    return int(text[:-2] + "01") if len(text) == 8 else int(material_id)


def find_hair_texture(root, character, material_id, color_id):
    """按发色档位取发型贴图：棕=10100001、黑=10100002…（同目录里按色号递增）。"""
    base = hair_base_id(material_id)
    number = base + max(color_id - 1, 0)
    avatar = Path(root) / character / "Avatar" / "Hr"
    if not avatar.is_dir():
        return None
    for pattern in (f"{base}/Tex/T_{character}_Hr_{number}_D.png",
                    f"**/T_{character}_Hr_{number}_D.png"):
        found = sorted(avatar.glob(pattern))
        if found:
            return found[0]
    return None


def find_brow_texture(root, character, color_id, props_cache=None):
    """眉毛贴图按颜色最近匹配。

    游戏里眉毛是共用材质 MI_Avatar_Br 的 9 张底图，文件名带的是内部色号，
    与沙龙色号不是同一套编号；用 RGB 最近匹配，棕色(563027) 会取到 4F2317FF——
    与游戏材质 dump 里的 BaseTex 一致。
    """
    # 与预览器 PC_BROW_COLOR_TEXTURE_ID 共用的确定映射，不能用最近色替代。
    texture_id = {1: "4F2317FF", 2: "261A1EFF", 3: "9F91A1FF", 4: "AC6931FF", 5: "8F291AFF"}[color_id]
    exact = Path(root) / "PC_Br" / "Tex" / f"T_PC1_Br_{texture_id}_D.png"
    if exact.is_file():
        return exact
    return None
def claim_placeholder_materials(mesh, report):
    """源 GLB 里眉毛 primitive 没有材质（槽名 None），照原样导出就是空白材质。

    按权重认领：该槽的权重集中在 Bone_meimao*（眉毛）的，补成游戏共用眉毛材质 MI_PC_Br，
    后面的贴图绑定就会按色号给它贴上眉毛底图。
    """
    from collections import defaultdict

    names = {group.index: group.name for group in mesh.vertex_groups}
    claimed, unclaimed = [], []
    for index, material in enumerate(mesh.data.materials):
        if material is not None and material.name != "None" and not material.name.startswith("dummy_material"):
            continue
        weights = defaultdict(float)
        for polygon in mesh.data.polygons:
            if polygon.material_index != index:
                continue
            for vertex_index in polygon.vertices:
                for element in mesh.data.vertices[vertex_index].groups:
                    if element.weight > 1e-4:
                        weights[names.get(element.group, "")] += element.weight
        if not weights:
            continue
        total = sum(weights.values())
        brow = sum(value for name, value in weights.items() if name.startswith("Bone_meimao"))
        top = sorted(weights.items(), key=lambda kv: -kv[1])[:3]
        if total <= 0 or brow / total < 0.5:
            unclaimed.append({"slot": index, "old": material.name if material else None,
                              "top_groups": [(name, round(value, 1)) for name, value in top]})
            continue
        new_material = bpy.data.materials.get("MI_PC_Br") or bpy.data.materials.new("MI_PC_Br")
        mesh.data.materials[index] = new_material
        claimed.append({"slot": index, "old": material.name if material else None,
                        "new": new_material.name,
                        "reason": "权重集中在 Bone_meimao*，按共用眉毛材质 MI_PC_Br 认领"})
    if claimed:
        report["materials_claimed"] = claimed
    if unclaimed:
        report["materials_unclaimed"] = unclaimed
    return claimed


def soften_face_socket(image, output_dir):
    """把脸贴图暗红眼窝改成肤色（纯 Python，Blender 内跑），去掉闭眼黑块。

    游戏 T_*_Et_*_D 的眼窝区是暗红 [50,6,6]，睁眼被眼白挡住、闭眼就露出来。
    这里把暗红区向整脸肤色混合，并保留最外一圈暗边当眼线，睁眼仍有轮廓。
    返回改写后的贴图绝对路径。
    """
    w, h = image.size
    n = w * h
    buf = [0.0] * (n * 4)
    image.pixels.foreach_get(buf)

    dark = [False] * n
    sr = sg = sb = 0.0
    cnt = 0
    for i in range(n):
        o = i * 4
        r, g, b = buf[o], buf[o + 1], buf[o + 2]
        is_dark = 0.10 < r < 0.48 and g < 0.13 and b < 0.13 and r > g * 3.0
        dark[i] = is_dark
        if not is_dark:
            sr += r
            sg += g
            sb += b
            cnt += 1
    skin = (sr / cnt, sg / cnt, sb / cnt) if cnt else (0.867, 0.669, 0.556)

    # 1 像素 4 邻域腐蚀：只有四周都是暗红才属于「内部」，外部一圈留作眼线
    inner = [False] * n
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if not dark[i]:
                continue
            if x > 0 and not dark[i - 1]:
                continue
            if x < w - 1 and not dark[i + 1]:
                continue
            if y > 0 and not dark[i - w]:
                continue
            if y < h - 1 and not dark[i + w]:
                continue
            inner[i] = True

    changed = 0
    for i in range(n):
        if not inner[i]:
            continue
        o = i * 4
        for c in range(3):
            buf[o + c] = buf[o + c] * 0.15 + skin[c] * 0.85
        changed += 1
    if changed:
        image.pixels.foreach_set(buf)
        out_dir = Path(output_dir) / "Tex"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(image.filepath).stem
        target = out_dir / f"{stem}_socket.png"
        image.filepath_raw = str(target.resolve())
        image.save()
        return str(target.resolve()), {"pixels": changed, "skin": [round(x, 4) for x in skin]}
    return str(Path(image.filepath).resolve()), None


def bind_textures(mesh, texture_root, hair_color=DEFAULT_COLOR_ID, brow_color=DEFAULT_COLOR_ID,
                  tex_override=None, output_dir=None, eye_socket_fix=True):
    import importlib

    FnMaterial = importlib.import_module(f"{ADDON}.core.material").FnMaterial

    FnMaterial.set_nodes_are_readonly(False)
    root = Path(texture_root)
    tex_override = tex_override or {}
    bound, missing = [], []
    props_cache = {}
    for material in mesh.data.materials:
        if material is None:
            continue
        if material.name.endswith("_OP"):
            continue  # 描边壳材质：MMD 用 輪郭(edge) 表达，见 configure_materials
        name = SUFFIX_PATTERN.sub("", material.name)
        match = MATERIAL_PATTERN.match(name)
        source = "id-dir"
        if match:
            character, slot, item = match.groups()
        else:
            parts = name.split("_")
            character = parts[1] if len(parts) > 1 else None
            slot = parts[2] if len(parts) > 2 else None
            item = None
        if slot == "Hr" and item:
            candidate = find_hair_texture(root, character, item, hair_color)
            source = "salon-hair-color"
        elif slot == "Br":
            candidate = find_brow_texture(root, character, brow_color, props_cache)
            source = "salon-brow-color"
        else:
            candidate = find_texture(root, character, slot, item) if character and slot else None
        inferred = None
        if candidate is None and name.startswith("dummy_material"):
            # UModel 没解析出该材质的引用；实测这个 primitive 的权重集中在 Bone_meimao*（眉毛），
            # 共用素材里眉毛材质是 MI_PC_Br，因此按它的 BaseTex 推断。
            candidate = texture_from_material_dump(root, "MI_PC_Br", props_cache)
            inferred = "材质名为 dummy_material，按眉毛骨权重 + 共用 MI_PC_Br 材质推断"
            source = "inferred-Br"
        if candidate is None:
            candidate = texture_from_material_dump(root, name, props_cache)
            source = "material-dump"
        if candidate is None:
            missing.append(material.name)
            continue
        if name in tex_override:
            candidate = Path(tex_override[name])
            source = "override"
            inferred = None
        softened = None
        if slot == "Et" and eye_socket_fix and output_dir and source != "override":
            face_image = bpy.data.images.load(str(Path(candidate).resolve()))
            candidate, softened = soften_face_socket(face_image, output_dir)
            source = "eye-socket-softened"
        FnMaterial(material).create_texture(str(Path(candidate).resolve()))
        if hasattr(material.mmd_material, "use_texture_alpha"):
            material.mmd_material.use_texture_alpha = False
        entry = {"material": material.name, "texture": str(candidate), "source": source}
        if softened:
            entry["eye_socket"] = softened
        if inferred:
            entry["inferred"] = inferred
        bound.append(entry)
    return bound, missing


def texture_from_material_dump(root, material_name, cache):
    """共用素材（眼、眉等）没有物品目录，改从 .props.txt 里的贴图参数取名字。

    参数名各槽不同（BaseTex / PupilTex 等），优先取 _D 结尾的漫反射图。
    """
    shared = globals().setdefault('_MATERIAL_TEXTURE_CACHE', {})
    key = (str(Path(root).resolve()).casefold(), material_name)
    if key in shared:
        cache[material_name] = shared[key]
        return shared[key]
    if material_name in cache:
        return cache[material_name]
    cache[material_name] = None
    props = sorted(Path(root).glob(f"**/{material_name}.props.txt"))
    if not props:
        shared[key] = None
        return None
    text = props[0].read_text(encoding="utf-8", errors="replace")
    names = re.findall(r"Texture2D'[^']*?\.([A-Za-z0-9_]+)'", text)
    for texture_name in [n for n in names if n.endswith("_D")] + names:
        hits = sorted(Path(root).glob(f"**/Tex/{texture_name}.png"))
        if hits:
            cache[material_name] = hits[0]
            break
    shared[key] = cache[material_name]
    return cache[material_name]


def synthesize_expression(mesh, block_names, name, recipe):
    """按「已有表情的加权插值」合成新表情（え=い/お 各半，ん=抿嘴的 0.4 倍）。"""
    if name in block_names:
        return None
    keys = mesh.data.shape_keys
    blocks = {kb.name: kb for kb in keys.key_blocks}
    if any(source not in blocks for source, _ in recipe):
        return None
    basis = keys.reference_key.data
    created = mesh.shape_key_add(name=name, from_mix=False)
    for index, base in enumerate(basis):
        offset = [0.0, 0.0, 0.0]
        for source, weight in recipe:
            point = blocks[source].data[index].co
            offset[0] += (point.x - base.co.x) * weight
            offset[1] += (point.y - base.co.y) * weight
            offset[2] += (point.z - base.co.z) * weight
        created.data[index].co = (base.co.x + offset[0], base.co.y + offset[1], base.co.z + offset[2])
    return {"original": f"synthetic:{name}", "name": name, "name_e": "e" if name == "え" else "n", "panel": "MOUTH"}


PHYSICS_PLAN = [
    {
        "label": "裙摆",
        "group": 2,
        "collision_groups": {0},
        # 只有 Bone_W_qunzi 系列真的带顶点权重（Bone_N_/Bone_K_ 系列权重为 0，
        # 建了刚体也不会动任何网格）。12~15 与 16~19 是两条 4 段长飘片，
        # 00~02 与 04~06 是前侧两片 3 段。
        "anchor": "Bone_W_qunzi_root",
        "chains": [
            [f"Bone_W_qunzi{index:02d}" for index in range(12, 16)],
            [f"Bone_W_qunzi{index:02d}" for index in range(16, 20)],
            [f"Bone_W_qunzi{index:02d}" for index in range(0, 3)],
            ["Bone_W_qunzi04", "Bone_W_qunzi05", "Bone_W_qunzi06"],
        ],
        "mass": [1.5, 1.2],
        "rot": [0.5, 0.25, 0.5],
        "damping": [0.4, 0.5],
        "size": 0.55,
    },
    {
        "label": "头发",
        "group": 3,
        "collision_groups": {0},
        "anchor": "Bone_M_TouFa06",
        "chains": [["Bone_M_TouFa07", "Bone_M_TouFa08"]],
        "mass": [0.3, 0.2],
        "rot": [0.3, 0.2, 0.3],
        "damping": [0.6, 0.6],
        "size": 0.45,
    },
]


def mmd_collision_mask(allowed_groups):
    """Return MMD Tools' mask whose exported PMX collides only with these groups.

    MMD Tools 4.5.14 writes a PMX non-collision bit when this property is
    false. Keeping this conversion in one helper prevents the previous
    off-by-one and inverse-mask mistakes.
    """
    return [index in allowed_groups for index in range(16)]


BODY_COLLIDERS = [
    ("腰", 0.75),
    ("下半身", 0.75),
    ("上半身", 0.65),
    ("上半身2", 0.65),
    ("左足", 0.45),
    ("左ひざ", 0.45),
    ("右足", 0.45),
    ("右ひざ", 0.45),
    ("左腕", 0.35),
    ("左ひじ", 0.35),
    ("右腕", 0.35),
    ("右ひじ", 0.35),
]


def weighted_bone_sums(meshes):
    """统计每根骨实际带多少顶点权重（加起来的总权重），用于按穿戴判断该给谁做物理。"""
    sums = {}
    for mesh in meshes:
        names = {group.index: group.name for group in mesh.vertex_groups}
        for vertex in mesh.data.vertices:
            for element in vertex.groups:
                if element.weight <= 1e-4:
                    continue
                name = names.get(element.group)
                if name:
                    sums[name] = sums.get(name, 0.0) + element.weight
    return sums


def hair_chains_from_weights(armature, weighted, root_name="Bone_M_TouiFa_root", limit=4):
    """从头发根往下找出真正带权重的骨链：不同发型用的骨链完全不同，不能写死。"""
    root = armature.data.bones.get(bn(root_name))
    if root is None:
        return []
    paths, stack = [], [(child, [child.name]) for child in root.children]
    while stack:
        bone, path = stack.pop()
        children = list(bone.children)
        if len(children) == 1 and len(path) < 4:
            stack.append((children[0], path + [children[0].name]))
        else:
            paths.append(path)
    scored = [(sum(weighted.get(name, 0.0) for name in path), path) for path in paths]
    scored = [entry for entry in scored if entry[0] > 0]
    scored.sort(key=lambda entry: -entry[0])
    return [{"chain": path, "weight": round(total, 1)} for total, path in scored[:limit]]


def select_physics_plan(armature, weighted, templates):
    """保留带权重骨到锚点之间的真实父子链，不为当前服装不用的骨生成物理。"""
    selected = []
    for template in templates:
        anchor = "Bone_M_TouiFa_root" if template["label"] == "头发" else template["anchor"]
        root = armature.data.bones.get(bn(anchor))
        if root is None:
            continue
        active = set()
        for name, weight in weighted.items():
            if weight <= 1e-4 or name == root.name:
                continue
            bone = armature.data.bones.get(name)
            path = []
            while bone is not None and bone != root:
                path.append(bone.name)
                bone = bone.parent
            if bone == root:
                active.update(path)
        if not active:
            continue
        chains = []
        def walk(bone, path):
            children = sorted((c for c in bone.children if c.name in active), key=lambda b: b.name)
            if not children:
                if path:
                    chains.append(path)
                return
            for child in children:
                walk(child, path + [child.name])
        walk(root, [])
        # A two-segment hair chain has too little inertia for a stable MMD
        # joint and can flip a full turn in one frame. Keep short hair rigidly
        # attached to the head; only simulate chains with at least three bones.
        if template["label"] == "头发":
            chains = [chain for chain in chains if len(chain) >= 3]
            if not chains:
                continue
        selected.append({**template, "anchor": root.name, "chains": chains})
    return selected


def add_physics(armature, report, meshes=()):
    """按骨链生成 MMD 刚体与关节（裙摆 / 头发 / 背包）。

    只给「真的带顶点权重」的骨链建刚体：同一套骨架换一件衣服，
    裙摆（Bone_W_qunzi*）和头发（Bone_M_TouFa*）的权重会完全变样，
    写死骨名会建出一堆不会动任何网格的刚体。
    """
    import importlib
    import math

    from mathutils import Euler, Vector

    weighted = weighted_bone_sums(meshes)

    FnModel = importlib.import_module(f"{ADDON}.core.model").FnModel
    rigid_module = importlib.import_module(f"{ADDON}.core.rigid_body")
    FnRigidBody = rigid_module.FnRigidBody

    root = armature.parent
    if root is None or not hasattr(root, "mmd_root"):
        report["physics"] = "没有 MMD 模型根，跳过"
        return {}
    rigid_group = FnModel.ensure_rigid_group_object(bpy.context, root)
    joint_group = FnModel.ensure_joint_group_object(bpy.context, root)
    display_size = FnModel.get_empty_display_size(root)

    def bone_of(name):
        return armature.data.bones.get(bn(name))

    def make_rigid(bone_name, group_number, collision_groups, mode, mass, size_scale, damping, label):
        bone = bone_of(bone_name)
        if bone is None:
            return None, None
        length = max((bone.tail_local - bone.head_local).length, 0.01)
        rotation = bone.matrix_local.to_euler("YXZ")
        rotation.rotate_axis("X", math.pi / 2)
        obj = FnRigidBody.new_rigid_body_object(bpy.context, rigid_group)
        FnRigidBody.setup_rigid_body_object(
            obj=obj,
            shape_type=rigid_module.shapeType("CAPSULE"),
            location=(bone.head_local + bone.tail_local) / 2,
            rotation=rotation,
            size=Vector((size_scale, size_scale, size_scale)) * length,
            dynamics_type=mode,
            collision_group_number=group_number,
            collision_group_mask=mmd_collision_mask(collision_groups),
            name=f"{label}_{bone_name}",
            name_e=f"{label}_{bone_name}",
            bone=bn(bone_name),
            friction=0.5,
            mass=mass,
            angular_damping=damping,
            linear_damping=damping,
            bounce=0.1,
        )
        return obj, bone

    def make_joint(bone, parent_obj, child_obj, rot_limit, label, angular_spring=0.0):
        rotation = bone.matrix_local.to_euler("YXZ")
        rotation.rotate_axis("X", math.pi / 2)
        obj = FnRigidBody.new_joint_object(bpy.context, joint_group, display_size)
        FnRigidBody.setup_joint_object(
            obj=obj,
            location=bone.head_local,
            rotation=rotation,
            rigid_a=parent_obj,
            rigid_b=child_obj,
            maximum_location=Vector((0.0, 0.0, 0.0)),
            minimum_location=Vector((0.0, 0.0, 0.0)),
            maximum_rotation=Euler(rot_limit),
            minimum_rotation=Euler((-rot_limit[0], -rot_limit[1], -rot_limit[2])),
            spring_angular=Vector((angular_spring, angular_spring, angular_spring)),
            spring_linear=Vector((0.0, 0.0, 0.0)),
            name=f"{label}_{bone.name}",
            name_e="",
        )
        return obj

    body_colliders = []
    for bone_name, size_scale in BODY_COLLIDERS:
        obj, _ = make_rigid(
            bone_name,
            0,
            set(),
            0,
            0.0,
            size_scale,
            0.5,
            "身体碰撞",
        )
        if obj is not None:
            body_colliders.append(bone_name)

    summary = {}
    parents = {b.name: b.parent.name if b.parent else None for b in armature.data.bones}
    native_file = Path(__file__).with_name('native-clothing-physics.json')
    native_data = json.loads(native_file.read_text(encoding='utf-8'))
    character = report['character']
    native_character = native_data['characters'][character]
    native_plan, coverage = build_native_plan(parents, weighted, native_character)
    claimed = {b for e in native_plan for c in e['chains'] for b in c}
    legacy_plan = select_physics_plan(armature, weighted, PHYSICS_PLAN)
    # Retain the established hair policy and legacy coverage only where there
    # is no matching native clothing configuration; never simulate twice.
    fallback = [{**e, 'chains': [c for c in e['chains'] if not claimed.intersection(c)]} for e in legacy_plan]
    plan = native_plan + [e for e in fallback if e['chains']]
    report['native_clothing_physics'] = {
        'revision': REVISION, 'character': character,
        'source_sha256': native_character['source_sha256'], **coverage,
        'safety_policy': 'WeiBa bones and original skin weights are retained; automatic PMX rigid-body physics is disabled pending native runtime calibration',
        'mapping': 'PMX approximation: angular spring = stiffness * solve rate * mass, clamped 0..10; damping = drag clamped 0..0.95',
        'collision_policy': 'existing MMD body colliders; native colliders are bound at runtime and not reconstructed',
        'unsupported': ['runtime wind', 'per-chain gravity overrides', 'runtime collider binding', 'game animation state switches'],
        'selected': [{'anchor': e['anchor'], 'chains': e['chains'], 'source': e['native_source'], 'bone_sources': e['native_sources'], 'effective_settings': e['native_settings']} for e in native_plan],
    }
    report["physics_selection"] = [{"label": e["label"], "anchor": e["anchor"], "chains": e["chains"]} for e in plan]
    report["physics_skipped_unweighted"] = [e["label"] for e in PHYSICS_PLAN if e["label"] not in {p["label"] for p in legacy_plan}]
    report['physics_legacy_replaced_by_native'] = sorted({e['label'] for e in legacy_plan if any(claimed.intersection(c) for c in e['chains'])})
    report["physics_policy"] = {
        e["label"]: {
            "collision_groups": sorted(e["collision_groups"]),
            "pmx_mask": sum(
                1 << index
                for index in range(16)
                if index not in e["collision_groups"]
            ),
        }
        for e in plan
    }
    report["physics_skipped_short_hair"] = (
        "头发"
        if "头发" not in {entry["label"] for entry in plan}
        else None
    )
    for entry in plan:
        rigids, joints, skipped = 0, 0, []
        made = {}
        anchor_obj, _ = make_rigid(entry["anchor"], entry["group"], entry["collision_groups"], 0,
                                   0.0, entry["size"], entry["damping"][0], entry["label"])
        if anchor_obj is None:
            skipped.append(entry["anchor"])
        else:
            rigids += 1
        for chain in entry["chains"]:
            parent_obj = anchor_obj
            for depth, bone_name in enumerate(chain):
                if bone_name in made:
                    parent_obj = made[bone_name]
                    continue
                bone = bone_of(bone_name)
                if bone is None:
                    skipped.append(bone_name)
                    continue
                mass = entry["mass"][min(depth, len(entry["mass"]) - 1)]
                damping = entry["damping"][min(depth, len(entry["damping"]) - 1)]
                spring = 0.0
                if 'native_settings' in entry:
                    converted = pmx_spring_parameters(entry['native_settings'][bone_name], mass, damping)
                    damping, spring = converted['damping'], converted['angular_spring']
                obj, _ = make_rigid(bone_name, entry["group"], entry["collision_groups"], 2,
                                    mass, entry["size"], damping, entry["label"])
                if obj is None:
                    skipped.append(bone_name)
                    continue
                rigids += 1
                made[bone_name] = obj
                if parent_obj is not None:
                    make_joint(bone, parent_obj, obj, entry["rot"], entry["label"], spring)
                    joints += 1
                parent_obj = obj
        summary[entry["label"]] = {"刚体": rigids, "关节": joints, "跳过": skipped}
    report["physics"] = summary
    report["body_collision_rigids"] = body_colliders
    return summary


def add_eye_closure_insets(mesh, renamed, report):
    """MMD compatibility: keep rotated eye surfaces behind closed lids.

    Preserve the original native targets as separate morphs. The game source GLB
    and baked native presets are unchanged; only standard MMD closure keys gain
    a small eye-surface inset, evaluated together with the existing lid motion.
    """
    keys = mesh.data.shape_keys
    eye_vertices = {"L": set(), "R": set()}
    for polygon in mesh.data.polygons:
        material = mesh.data.materials[polygon.material_index]
        name = SUFFIX_PATTERN.sub("", material.name) if material else ""
        if name in EYE_MATERIAL_TOKENS:
            eye_vertices[name[-1]].update(polygon.vertices)
    presets = (("まばたき", "瞬", 0.025), ("閉眼", "閉", 0.025), ("じと目", "細", 0.0125))
    added, corrections = [], []
    original_names = {entry["name"]: entry["original"] for entry in renamed}
    for standard, label, distance in presets:
        for side in ("L", "R"):
            source = keys.key_blocks.get(f"{standard}_{side}")
            if source is None or not eye_vertices[side]:
                continue
            name = f"元_{label}_{side}"
            backup = mesh.shape_key_add(name=name, from_mix=False)
            for i, point in enumerate(source.data):
                backup.data[i].co = point.co
            for i in eye_vertices[side]:
                # Blender's converted body faces -Y; +Y retreats inside the face.
                source.data[i].co.y += distance
            added.append({"original": "preserved:" + original_names[source.name], "name": backup.name,
                          "name_e": "native " + source.name, "panel": "OTHER"})
            corrections.append({"standard": source.name, "original_backup": backup.name,
                                "vertices": len(eye_vertices[side]), "inset_m": distance})
    report["eye_closure_compatibility"] = {"revision": 1, "corrections": corrections,
        "note": "Derived MMD eye inset; original native targets preserved as 元_*; native presets unchanged."}
    return added


def compute_mouth_gain(base_heights, delta_heights, limit):
    """Largest gain in [0,1] whose lip-height range fits the reference cap."""
    def height(gain):
        values = [b + gain * d for b, d in zip(base_heights, delta_heights)]
        return max(values) - min(values)
    limit = max(limit, height(0.0))
    if height(1.0) <= limit:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(40):
        middle = (low + high) / 2
        if height(middle) <= limit:
            low = middle
        else:
            high = middle
    return low


MOUTH_REFERENCE_PROFILE = {'reference_sha256': '429f8284e2135bc7c8102b3da078e689fd1e3e82abd9c5f6b8d78265410ad6ab', 'reference_name': '龙晶石心十人公司制服', 'opening_delta_over_neutral_width': {'あ': 0.43982585884032777, 'い': 0.1044936924638259, 'う': 0.18791936527120814, 'え': 0.25239015403677234, 'お': 0.35613532434827855}, 'default_open_ratio': 0.43982585884032777, 'characters': {'PC1': {'lip_uv_bounds': [0.44081796875, 0.56113515625, 0.57460703125, 0.58945546875]}, 'PC2': {'lip_uv_bounds': [0.45156015625, 0.55039296875, 0.51406015625, 0.5323265625]}}}


def calibrate_mmd_mouth(mesh, renamed, report):
    """Reference-normalized MMD mouth targets; source targets get exact backups."""
    profile = MOUTH_REFERENCE_PROFILE
    character = next((c for c in profile["characters"] if any(
        material and SUFFIX_PATTERN.sub("", material.name).startswith(f"MI_{c}_Et_")
        for material in mesh.data.materials)), None)
    if character is None:
        report["mouth_calibration"] = {"status": "no supported face material"}
        return []
    bounds = profile["characters"][character]["lip_uv_bounds"]
    face_vertices, lip_vertices = set(), set()
    for polygon in mesh.data.polygons:
        material = mesh.data.materials[polygon.material_index]
        if not material or not SUFFIX_PATTERN.sub("", material.name).startswith(f"MI_{character}_Et_"):
            continue
        face_vertices.update(polygon.vertices)
        for loop_index in polygon.loop_indices:
            loop = mesh.data.loops[loop_index]
            uv = mesh.data.uv_layers.active.data[loop_index].uv
            u, v = uv.x, 1.0 - uv.y  # Blender bottom-origin -> PMX/image top-origin
            if bounds[0] <= u <= bounds[1] and bounds[2] <= v <= bounds[3]:
                lip_vertices.add(loop.vertex_index)
    if len(lip_vertices) < 8:
        raise RuntimeError(f"{character}: lip calibration found only {len(lip_vertices)} vertices")
    keys = mesh.data.shape_keys
    basis = keys.reference_key.data
    points = [basis[i].co.copy() for i in lip_vertices]
    low_x, high_x = min(p.x for p in points), max(p.x for p in points)
    width = high_x - low_x
    base_heights = [basis[i].co.z for i in lip_vertices]
    neutral_height = max(base_heights) - min(base_heights)
    center_x = (low_x + high_x) / 2
    center_z = (max(base_heights) + min(base_heights)) / 2
    center_y = sum(p.y for p in points) / len(points)
    entries, limited = [], []
    for entry in renamed:
        if not entry["original"].lower().startswith("fe_"):
            continue
        target = keys.key_blocks[entry["name"]]
        ratio = profile["opening_delta_over_neutral_width"].get(target.name, profile["default_open_ratio"])
        limit = neutral_height + width * ratio
        deltas = [target.data[i].co.z - basis[i].co.z for i in lip_vertices]
        gain = compute_mouth_gain(base_heights, deltas, limit)
        if gain >= 0.999999:
            continue
        original_height = max(b + d for b, d in zip(base_heights, deltas)) - min(b + d for b, d in zip(base_heights, deltas))
        backup = mesh.shape_key_add(name="元口_" + target.name, from_mix=False)
        for i, point in enumerate(target.data):
            backup.data[i].co = point.co
            target.data[i].co = basis[i].co + (point.co - basis[i].co) * gain
        entries.append({"original": "preserved-mouth:" + entry["original"], "name": backup.name,
                        "name_e": "native " + entry["original"], "panel": "OTHER"})
        limited.append({"standard": target.name, "gain": gain, "backup": backup.name,
                        "before_height_m": original_height, "limit_height_m": limit})
    semantic_controls = []
    for standard, eye_sources in (("びっくり", ("びっくり_L", "びっくり_R")),
                                  ("笑い", ("にっこり_L", "にっこり_R"))):
        target = keys.key_blocks.get(standard)
        if target is None or any(keys.key_blocks.get(name) is None for name in eye_sources):
            continue
        backup_name = "元口_" + standard
        if keys.key_blocks.get(backup_name) is None:
            backup = mesh.shape_key_add(name=backup_name, from_mix=False)
            for i, point in enumerate(target.data):
                backup.data[i].co = point.co
            original = next(e["original"] for e in renamed if e["name"] == standard)
            entries.append({"original": "preserved-mouth:" + original, "name": backup_name,
                            "name_e": "native " + original, "panel": "OTHER"})
        for i, base in enumerate(basis):
            delta = Vector((0.0, 0.0, 0.0))
            for source_name in eye_sources:
                delta += keys.key_blocks[source_name].data[i].co - base.co
            target.data[i].co = base.co + delta
        if standard == "笑い":
            eye_ids = {i for polygon in mesh.data.polygons
                       if mesh.data.materials[polygon.material_index]
                       and SUFFIX_PATTERN.sub("", mesh.data.materials[polygon.material_index].name) in EYE_MATERIAL_TOKENS
                       for i in polygon.vertices}
            for i in eye_ids:
                target.data[i].co.y += 0.0125
        for entry in renamed:
            if entry["name"] == standard:
                entry["panel"] = "EYE"
        semantic_controls.append({"standard": standard, "eye_sources": list(eye_sources),
                                  "native_backup": backup_name, "mouth_motion_removed": True})
    # Direction/corner controls must not alias a whole open-mouth vowel or laugh.
    definitions = []
    for stem, mode in (("口角上げ", "corner"), ("口角下げ", "corner-down"), ("口横広げ", "wide"), ("口横狭げ", "narrow"), ("口横狭め", "narrow")):
        for suffix, side in (("", 0), ("左", 1), ("右", -1)):
            definitions.append((stem + suffix, mode, side))
    definitions += [("口上", "up", 0), ("口下", "down", 0), ("口左", "left", 0), ("口右", "right", 0)]
    for name, mode, side in definitions:
        key = mesh.shape_key_add(name=name, from_mix=False)
        for i in face_vertices:
            base = basis[i].co
            x, z, depth = base.x - center_x, base.z - center_z, base.y - center_y
            if mode in ("corner", "corner-down"):
                delta_x = delta_z = 0.0
                for sign in (1, -1):
                    if side and side != sign:
                        continue
                    distance = ((x - sign * width / 2) / (width * 0.30)) ** 2 + (z / (width * 0.25)) ** 2 + (depth / (width * 0.5)) ** 2
                    influence = math.exp(-distance)
                    delta_x += sign * width * 0.02 * influence
                    delta_z += width * (0.04 if mode == "corner" else -0.04) * influence
            else:
                influence = math.exp(-((x / (width * 0.8)) ** 2 + (z / (width * 0.45)) ** 2 + (depth / (width * 0.6)) ** 2))
                if side:
                    influence *= max(0.0, min(1.0, 2.0 * side * x / width))
                delta_x = (x * (0.30 if mode == "wide" else -0.30)) * influence if mode in ("wide", "narrow") else 0.0
                delta_z = 0.0
                if mode in ("left", "right"):
                    delta_x = width * (0.05 if mode == "left" else -0.05) * influence
                if mode in ("up", "down"):
                    delta_z = width * (0.05 if mode == "up" else -0.05) * influence
            key.data[i].co.x += delta_x
            key.data[i].co.z += delta_z
        entries.append({"original": "compat-mouth:" + name, "name": name, "name_e": "MMD mouth " + mode, "panel": "MOUTH"})
    report["mouth_calibration"] = {"revision": 1, "character": character,
        "reference_name": profile["reference_name"], "reference_sha256": profile["reference_sha256"],
        "reference_opening_delta_ratios": profile["opening_delta_over_neutral_width"],
        "lip_vertices": len(lip_vertices), "lip_neutral_width_m": width,
        "lip_neutral_height_m": neutral_height, "limited": limited,
        "direction_controls": [name for name, _, _ in definitions],
        "semantic_controls": semantic_controls,
        "limits": "Per-target 0..1 limits; arbitrary additive morph combinations can exceed these caps."}
    return entries


def apply_expression_names(mesh, armature, report):
    """把游戏 morph（shape key）改名为 MMD 标准表情名、合成缺失音、登记到 mmd_root。"""
    root = armature.parent
    keys = mesh.data.shape_keys
    if keys is None:
        report["expressions"] = 0
        return
    reference = keys.reference_key
    renamed, unmapped = [], []
    for block in list(keys.key_blocks):
        if block == reference:
            continue
        original = block.name
        # 大小写不敏感（PC1 的 morph 名是全大写 FE_danu）
        mapping = EXPRESSION_MAP.get(original) or EXPRESSION_MAP_LOWER.get(original.lower())
        if original.startswith("NRC_P_"):
            # VMD morph tracks have a 15-byte Shift-JIS name field.
            mapping = ("原生_" + original.removeprefix("NRC_P_"), original, "OTHER")
        if mapping is None and original.endswith(("_L", "_R")):
            base, side = original[:-2].rstrip("_"), original[-1]
            base_mapping = EXPRESSION_MAP.get(base) or EXPRESSION_MAP_LOWER.get(base.lower())
            if base_mapping is not None:
                mapping = (f"{base_mapping[0]}_{side}", f"{base_mapping[1]}_{side}", base_mapping[2])
        if mapping is None:
            unmapped.append(original)
            mapping = (original, original, "OTHER")
        block.name = mapping[0]
        renamed.append({"original": original, "name": mapping[0], "name_e": mapping[1], "panel": mapping[2]})

    preserved_eye_targets = add_eye_closure_insets(mesh, renamed, report)
    mouth_entries = calibrate_mmd_mouth(mesh, renamed, report)
    synthesized = []
    block_names = {block.name for block in keys.key_blocks}
    for name, recipe in SYNTHETIC_EXPRESSIONS.items():
        entry = synthesize_expression(mesh, block_names, name, recipe)
        if entry is not None:
            synthesized.append(entry)
            block_names.add(name)

    entries = renamed + preserved_eye_targets + mouth_entries + synthesized
    order_index = {}
    for position, entry in enumerate(entries):
        order_index[entry["name"]] = position
    entries.sort(key=lambda entry: (
        MORPH_ORDER.index(entry["name"]) if entry["name"] in MORPH_ORDER else len(MORPH_ORDER),
        order_index[entry["name"]],
    ))

    if root is not None and hasattr(root, "mmd_root"):
        morphs = root.mmd_root.vertex_morphs
        while len(morphs):
            morphs.remove(len(morphs) - 1)
        for entry in entries:
            item = morphs.add()
            item.name = entry["name"]
            item.name_e = entry["name_e"]
            item.category = entry["panel"]
    report["expressions"] = len(entries)
    report["expression_map"] = entries
    report["expression_synthesized"] = [entry["name"] for entry in synthesized]
    report["expression_unmapped"] = unmapped


def add_morph_aliases(armature, report, mesh=None):
    """把动作里的别名烘成「顶点表情」：复制目标表情的顶点位移。

    mmd_tools 导入 VMD 时只驱动顶点表情（组表情它不认），烘成顶点表情后
    Blender 与 MMD 都能驱动；代价是 PMX 里多几十个重复位移的表情条目。
    """
    root = armature.parent
    keys = mesh.data.shape_keys if mesh else None
    if keys is None or root is None or not hasattr(root, "mmd_root"):
        report["morph_aliases"] = []
        return []
    blocks = {block.name for block in keys.key_blocks}
    morphs = root.mmd_root.vertex_morphs
    categories = {item.name: item.category for item in morphs}
    added = []
    for alias, (target, factor) in MORPH_ALIASES.items():
        if alias in blocks or target not in blocks:
            continue
        entry = synthesize_expression(mesh, blocks, alias, ((target, factor),))
        if entry is None:
            continue
        item = morphs.add()
        item.name = alias
        item.name_e = f"alias of {target}"
        item.category = categories.get(target, "OTHER")
        blocks.add(alias)
        added.append({"alias": alias, "target": target, "factor": factor, "panel": item.category})
    report["morph_aliases"] = added
    return added


def build_display_items(armature):
    """重建 MMD 表示枠，保证每根骨都能在 MMD 面板里选到。"""
    root = armature.parent
    if root is None or not hasattr(root, "mmd_root"):
        return None
    frames = root.mmd_root.display_item_frames
    while len(frames):
        frames.remove(len(frames) - 1)

    names = {bone.name for bone in armature.data.bones}
    core = ["全ての親", "センター", "グルーブ", "腰", "上半身", "上半身2", "首", "頭",
            bn("左肩"), bn("右肩"), bn("左腕"), bn("右腕"), bn("左ひじ"), bn("右ひじ"),
            bn("左手首"), bn("右手首"),
            bn("左肩P"), bn("右肩P"), bn("左腕捩"), bn("右腕捩"), bn("左手捩"), bn("右手捩"),
            bn("両目"), bn("左目"), bn("右目"), "下半身"]
    layout = [
        ("Root", False, [n for n in core if n in names]),
        ("表情", True, []),
        ("左手", False, [b for b in sorted(names) if b.startswith("左") and any(k in b for k in ("親指", "人指", "中指", "薬指", "小指"))]),
        ("右手", False, [b for b in sorted(names) if b.startswith("右") and any(k in b for k in ("親指", "人指", "中指", "薬指", "小指"))]),
        ("左足ＩＫ", False, [bn(n) for n in ("左足", "左ひざ", "左足首", "左つま先", "左足先EX", "左足ＩＫ",
                                             "左つま先ＩＫ", "左足D", "左ひざD", "左足首D", "左つま先D") if bn(n) in names]),
        ("右足ＩＫ", False, [bn(n) for n in ("右足", "右ひざ", "右足首", "右つま先", "右足先EX", "右足ＩＫ",
                                             "右つま先ＩＫ", "右足D", "右ひざD", "右足首D", "右つま先D") if bn(n) in names]),
    ]
    used = {item for _, _, items in layout for item in items}
    rest = sorted(names - used)
    layout.append(("物理与其他", False, rest))

    for frame_name, special, items in layout:
        frame = frames.add()
        frame.name = frame_name
        frame.name_e = frame_name
        frame.is_special = special
        for bone_name in items:
            item = frame.data.add()
            item.type = "BONE"
            item.name = bone_name
        if frame_name == "表情":
            # 表情面板：把顶点表情与组表情都列进「表情」表示枠，MMD 的表情标签才有内容
            for morph_name in [m.name for m in root.mmd_root.vertex_morphs]:
                item = frame.data.add()
                item.type = "MORPH"
                item.name = morph_name
                item.morph_type = "vertex_morphs"
            for morph_name in [m.name for m in root.mmd_root.group_morphs]:
                item = frame.data.add()
                item.type = "MORPH"
                item.name = morph_name
                item.morph_type = "group_morphs"
    return {name: len(items) for name, _, items in layout}


def configure_materials(mesh, double_sided, edge):
    configured = 0
    skipped = []
    for material in mesh.data.materials:
        if material is None:
            continue
        mmd_material = material.mmd_material
        is_outline_shell = material.name.endswith("_OP")
        for name, value in (
            ("is_double_sided", double_sided),
            ("enabled_toon_edge", edge and not is_outline_shell),
            ("edge_color", (0.0, 0.0, 0.0, 1.0) if edge and not is_outline_shell else (0.0, 0.0, 0.0, 0.0)),
            ("alpha", 0.0 if is_outline_shell else 1.0),
        ):
            if hasattr(mmd_material, name):
                setattr(mmd_material, name, value)
            else:
                skipped.append(f"{material.name}:{name}")
        configured += 1
    return configured, skipped


def model_height(meshes):
    lows, highs = [], []
    for mesh in meshes:
        coordinates = [mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices]
        lows.append(min(c.z for c in coordinates))
        highs.append(max(c.z for c in coordinates))
    return max(highs) - min(lows)


def mesh_stats(meshes):
    return {
        "mesh_objects": [
            {
                "name": mesh.name,
                "vertices": len(mesh.data.vertices),
                "triangles": sum(len(polygon.vertices) - 2 for polygon in mesh.data.polygons),
                "materials": len([m for m in mesh.data.materials if m]),
            }
            for mesh in meshes
        ],
        "vertices": sum(len(mesh.data.vertices) for mesh in meshes),
        "triangles": sum(sum(len(polygon.vertices) - 2 for polygon in mesh.data.polygons) for mesh in meshes),
        "materials": sum(len([m for m in mesh.data.materials if m]) for mesh in meshes),
    }


def main():
    args = parse_args()
    global NAMING_STYLE
    NAMING_STYLE = args.naming
    report = {"body": args.body, "clothes": args.clothes, "out": args.out, "naming": args.naming}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.native_expressions_manifest:
        manifest = json.loads(Path(args.native_expressions_manifest).read_text(encoding="utf-8"))
        actual_hash = hashlib.sha256(Path(args.body).read_bytes()).hexdigest()
        if manifest.get("version") != 1 or actual_hash != manifest.get("model_sha256"):
            raise RuntimeError("原生表情 v1 模型与来源清单不匹配")
        if not args.no_eye_socket_fix:
            raise RuntimeError("原生表情 v1 不应叠加旧眼窝涂色补丁")
        report["native_expression_v1"] = manifest

    reset_scene()
    body_objects = import_gltf(args.body)
    arms = [o for o in body_objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise RuntimeError(f"身体 glTF 里期望 1 个骨架，实际 {len(arms)}")
    armature = arms[0]
    armature['nrc_body_source'] = str(args.body)
    report["armature"] = armature.name
    report["bones_before"] = len(armature.data.bones)

    export_root = Path(args.body).parents[1]
    part_root = Path(args.part_root) if args.part_root else export_root
    character = Path(args.body).parent.name
    report['character'] = character
    body_mesh = next((o for o in armature.children if o.type == "MESH"), None)
    if body_mesh is None:
        raise RuntimeError("身体骨架下没有网格")

    if args.eye_avatar_id is not None:
        replace_modular_head(armature, body_mesh, part_root, character, args.eye_avatar_id, report)

    resolved, skipped_items = resolve_requested_items(args.item, args.item_conf, part_root)
    report["items"] = resolved
    report["items_skipped"] = skipped_items
    if skipped_items:
        log("跳过无法解析的物品:", skipped_items)
    explicit_parts = [explicit_clothing_part(path) for path in args.clothes]
    user_tokens = {token for item in resolved + explicit_parts for token in item["tokens"]}
    default_has_hat=any(m and material_token(m.name)=='Ht' for m in body_mesh.data.materials)
    desired_has_hat=('Ht' in user_tokens) or (default_has_hat and 'Hi' not in user_tokens)
    report['desired_has_hat']=desired_has_hat
    report["user_slot_tokens"] = sorted(user_tokens)

    # 1) 用各部位网格拼身体：被替换的槽位用指定物品，其余槽位用默认款
    parts = []
    defaults = default_part_ids(body_mesh)
    report["default_part_ids"] = defaults
    if not args.no_strip:
        for slot in PART_SLOTS:
            if slot in user_tokens:
                continue
            part_id = defaults.get(slot)
            if not part_id:
                continue
            path = find_part_mesh(part_root, character, slot, part_id)
            if path is None:
                report.setdefault("parts_missing", []).append(f"{slot}:{part_id}")
                continue
            parts.append({"slot": slot, "id": part_id, "mesh": str(path), "source": "默认款"})
    for item in resolved:
        parts.append({"slot": item["type_name"], "id": item["id"], "asset_id": item['asset_id'], "geometry_id": item['geometry_id'], "mesh": item["mesh"], "source": "指定物品"})
    parts.extend(explicit_parts)
    report["parts"] = parts

    # 2) SKM_PC2 只留头部；它的 By 是「没衣服」时的整块皮肤，穿衣服时由部位网格提供
    if not args.no_strip:
        strip_now = wardrobe_strip_tokens(user_tokens)
        report["body_neck_skin_preserved_faces"] = len(neck_skin_faces(body_mesh))
        report["body_parts_stripped"] = drop_materials(
            body_mesh, strip_now, preserve_upper_neck=True)

    if not args.hair_mesh and desired_has_hat!=default_has_hat:
        replace_default_hat_hair(armature,body_mesh,character,desired_has_hat,report)

    if args.hair_mesh:
        report["base_hair_stripped"] = drop_materials(body_mesh, {"Hr"})
        extra = import_gltf(args.hair_mesh)
        merge_into_body(armature, extra, strip_parts=False)
        report["hair_mesh"] = args.hair_mesh

    clothing_weighted = set()
    clothing_added = set()
    for part in parts:
        extra = import_gltf(part["mesh"])
        extra = prepare_wearable(armature, extra, part, report)
        source_arms = {o for o in extra if o.type == 'ARMATURE'}
        source_meshes = [o for o in extra if o.type == 'MESH' and uses_any_armature(o, source_arms)]
        source_weighted = weighted_bone_sums(source_meshes)
        before_bones = set(armature.data.bones.keys())
        _, _, _, seen = merge_into_body(armature, extra, strip_parts=False)
        if part.get('attachment_roots'):
            bpy.context.view_layer.objects.active=armature;bpy.ops.object.mode_set(mode='EDIT')
            for name in part['attachment_roots']:
                armature.data.edit_bones[name].parent=armature.data.edit_bones[part['attachment_anchor']]
            bpy.ops.object.mode_set(mode='OBJECT')
        merged_parents = {b.name: b.parent.name if b.parent else None for b in armature.data.bones}
        preserved = validate_weighted_bones(merged_parents, source_weighted)
        added = sorted(set(merged_parents) - before_bones)
        clothing_weighted.update(preserved)
        clothing_added.update(added)
        report.setdefault('clothing_bones', []).append({
            'mesh': part['mesh'], 'weighted_bones': preserved,
            'added_bones': added,
            'parents': {name: merged_parents[name] for name in preserved},
        })
        report.setdefault("clothes_merged", []).append(part["mesh"])
        report.setdefault("item_tokens_seen", []).append({"mesh": part["mesh"], "tokens": seen})
    report['clothing_bones_summary'] = {
        'weighted': sorted(clothing_weighted),
        'added': sorted(clothing_added),
    }

    report["helpers_removed"] = strip_helper_objects(armature, set())
    for obj in list(bpy.context.scene.objects):
        if obj.type == "EMPTY" and obj.parent is None:
            bpy.data.objects.remove(obj, do_unlink=True)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in [o for o in bpy.context.scene.objects if o.type in {"ARMATURE", "MESH"}]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.mmd_tools.convert_to_mmd_model(scale=0.08)

    import importlib

    FnModel = importlib.import_module(f"{ADDON}.core.model").FnModel
    meshes = list(FnModel.iterate_mesh_objects(armature.parent))
    for mesh in meshes:
        claim_placeholder_materials(mesh, report)
    report["salon_preset"] = {"hair_color": args.hair_color, "brow_color": args.brow_color}
    report["helpers_removed"] += strip_helper_objects(armature, set(meshes))
    report.update(mesh_stats(meshes))
    height = model_height(meshes)
    report["height_blender_units"] = round(height, 4)
    for mesh in meshes:
        if mesh.data.shape_keys:
            apply_expression_names(mesh, armature, report)
            break

    pairs = [(source, bn(target)) for source, target in load_mapping(Path(args.mapping))]
    done, missing = rename_bones(armature, pairs)
    report["renamed"] = len(done)
    report["rename_missing"] = missing
    report["vertex_groups_renamed"] = sum(sync_vertex_groups(mesh, pairs) for mesh in meshes)
    final_parents = {b.name: b.parent.name if b.parent else None for b in armature.data.bones}
    report['weighted_bones_preserved'] = validate_weighted_bones(final_parents, weighted_bone_sums(meshes))
    report['clothing_bones_revision'] = REVISION
    report["bones_after_rename"] = len(armature.data.bones)

    report["created_bones"] = restructure(armature)

    arm_pose = "a" if args.keep_a_pose else args.arm_pose
    report["arm_pose"] = arm_pose
    if arm_pose == "t":
        angles_before = {side: measure_arm_angle(armature, bn(f"{side}腕"), bn(f"{side}ひじ")) for side in ("左", "右")}
        bpy.ops.object.mode_set(mode="POSE")
        for side in ("左", "右"):
            straighten_segment(armature, bn(f"{side}腕"), bn(f"{side}ひじ"))
            straighten_segment(armature, bn(f"{side}ひじ"), bn(f"{side}手首"))
        bpy.context.view_layer.update()
        angles_after = {side: measure_arm_angle(armature, bn(f"{side}腕"), bn(f"{side}ひじ")) for side in ("左", "右")}
        report["arm_pose_baked"] = bake_pose_into_meshes(meshes)
        bpy.ops.pose.armature_apply(selected=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        report["arm_angle_before_deg"] = {k: round(v, 2) for k, v in angles_before.items()}
        report["arm_angle_after_deg"] = {k: round(v, 2) for k, v in angles_after.items()}
    else:
        report["arm_angle_deg"] = {
            side: round(measure_arm_angle(armature, bn(f"{side}腕"), bn(f"{side}ひじ")), 2)
            for side in ("左", "右")
        }

    if not args.no_ik:
        report["ik_bones"] = build_ik(armature, args.knee_limit)
        report["ik_constraints"] = [
            {"bone": b.name, "target": c.subtarget, "chain": c.chain_count}
            for b in armature.pose.bones for c in b.constraints if c.type == "IK"
        ]

    report["standard_bones"] = add_standard_bones(armature, report)
    report["twist_links"] = link_twist_bones(armature, report)
    report["leg_deform_controls"] = activate_leg_deform_controls(armature, meshes)
    if not args.keep_native_arm_weights:
        report["arm_skinning"] = conform_arm_skinning(armature, meshes)
    inset_covered_arm_skin(armature, meshes, report)
    report["skeleton_revision"] = "native-audit-v2-20261019"
    report["eye_pivot_revision"] = "native-eye-skin-v1-20261019"
    report["eye_closure_revision"] = "mmd-eye-inset-v1-20261019"
    report["mouth_revision"] = "reference-mouth-v1-20261019"
    report["morph_aliases"] = add_morph_aliases(armature, report, meshes[0] if meshes else None)

    if args.physics:
        add_physics(armature, report, meshes)

    if args.no_eye_rewire:
        report["eye_reweight"] = "已按参数跳过"
        report["eye_reweight_detail"] = []
    else:
        report["eye_reweight_detail"] = rewire_eyes(meshes[0], armature, report)

    report["display_frames"] = build_display_items(armature)

    model_root = armature.parent
    if model_root is not None and hasattr(model_root, "mmd_root"):
        model_root.mmd_root.name = output.stem
        model_root.mmd_root.name_e = output.stem
        model_root.name = output.stem
    report["model_name"] = output.stem

    if not args.no_textures:
        root = args.texture_root or str(Path(args.body).parents[1])
        tex_override = {}
        if args.tex_override:
            import json as _json
            tex_override = _json.loads(Path(args.tex_override).read_text(encoding="utf-8"))
        bound, unbound = [], []
        for mesh in meshes:
            mesh_bound, mesh_unbound = bind_textures(
                mesh, root, args.hair_color, args.brow_color,
                tex_override=tex_override,
                output_dir=str(output.parent),
                eye_socket_fix=not args.no_eye_socket_fix,
            )
            bound += mesh_bound
            unbound += mesh_unbound
        report["textures_bound"] = len(bound)
        report["textures_unbound"] = unbound
        report["textures_bound_detail"] = bound
        report["texture_root"] = root
    configured, skipped_props = 0, []
    for mesh in meshes:
        mesh_configured, mesh_skipped = configure_materials(mesh, args.double_sided, not args.no_edge)
        configured += mesh_configured
        skipped_props += mesh_skipped
    report["materials_configured"] = configured
    report["material_props_missing"] = skipped_props

    scale = args.pmx_scale
    if args.target_height:
        scale = round(args.target_height / height, 4)
    report["pmx_scale"] = scale
    report["expected_pmx_height"] = round(height * scale, 3)

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.mmd_tools.export_pmx(
        filepath=str(output),
        scale=scale,
        copy_textures_mode="SKIP_EXISTING",
        sort_materials=False,
        fix_bone_order=True,
        normal_handling="PRESERVE_ALL_NORMALS",
        export_vertex_colors_as_adduv2=args.adduv2_vertex_color,
    )

    if output.is_file():
        report["pmx_bytes"] = output.stat().st_size
        report["pmx_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    else:
        report["pmx_bytes"] = 0

    if args.dynamic_chroma:
        import runpy
        module = runpy.run_path(str(Path(__file__).with_name("dynamic-chroma.py")))
        report["dynamic_chroma"] = module["build_scene"](str(output), args.dynamic_chroma)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log("报告:", args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

