#!/usr/bin/env python3
"""Validate a PMX against a real VMD motion and render sampling frames.

Run inside Blender (MMD Tools required):
  blender -b -noaudio --factory-startup --python vmd-motion-test.py -- \
      --pmx model.pmx --vmd motion.vmd --out report-dir [--frames 1,60,120,240,400] [--png]

Outputs <out>/motion-report.json and, with --png, <out>/f<frame>.png.
Checks: bone channels hit existing bones, facial morph channels hit shape keys,
rigid bodies/physics, per-frame vertex count / non-finite / bbox.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import addon_utils
import bpy

ADDON = "bl_ext.user_default.mmd_tools"


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--pmx", required=True)
    parser.add_argument("--vmd", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--frames", default="1,60,120,240,400")
    parser.add_argument("--png", action="store_true")
    parser.add_argument("--no-physics", action="store_true")
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=675)
    return parser.parse_args(argv)


def enable_addon():
    for name in (ADDON, "mmd_tools"):
        try:
            addon_utils.enable(name, default_set=True)
            return
        except Exception:
            continue
    raise SystemExit("MMD Tools add-on not found")


def import_model(pmx, with_physics):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    enable_addon()
    types = {"MESH", "ARMATURE", "MORPHS"}
    if with_physics:
        types.add("PHYSICS")
    bpy.ops.mmd_tools.import_model(
        filepath=str(pmx), scale=0.08, types=types,
        clean_model=True, remove_doubles=False, fix_ik_links=True, rename_bones=False)
    armature = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")
    return armature, mesh


def import_motion(armature, mesh, vmd):
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    result = bpy.ops.mmd_tools.import_vmd(
        filepath=str(vmd), scale=0.08, margin=0,
        create_new_action=True, use_pose_mode=False, rename_bones=False)
    if result != {"FINISHED"}:
        raise SystemExit(f"VMD import failed: {result}")


def action_channels():
    bones, morphs = set(), set()
    for action in bpy.data.actions:
        for curve in action.fcurves:
            path = curve.data_path
            if path.startswith('pose.bones["'):
                bones.add(path.split('"')[1])
            elif path.startswith("key_blocks["):
                morphs.add(path.split('"')[1])
    return bones, morphs


def build_physics(mesh):
    import importlib

    scene = bpy.context.scene
    root = next((o for o in scene.objects if hasattr(o, "mmd_root")), None)
    Model = importlib.import_module(f"{ADDON}.core.model").Model
    if root is not None and not root.mmd_root.is_built:
        Model(root).build()
    scene.rigidbody_world.enabled = True
    bodies = [o for o in scene.objects if o.rigid_body is not None]
    tracks = sum(1 for pb in next(o for o in scene.objects if o.type == "ARMATURE").pose.bones
                 if "mmd_tools_rigid_track" in pb.constraints)
    return len(bodies), tracks


def emission_materials():
    """Render texture colors directly; round alpha so 254/255 is not dithered as noise."""
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        if not out:
            continue
        tex = nodes.get("mmd_base_tex")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Strength"].default_value = 1.0
        if tex and tex.image:
            links.new(tex.outputs["Color"], emission.inputs["Color"])
            transparent = nodes.new("ShaderNodeBsdfTransparent")
            mix = nodes.new("ShaderNodeMixShader")
            rounded = nodes.new("ShaderNodeMath")
            rounded.operation = "ROUND"
            links.new(tex.outputs["Alpha"], rounded.inputs[0])
            links.new(rounded.outputs[0], mix.inputs[0])
            links.new(transparent.outputs[0], mix.inputs[1])
            links.new(emission.outputs[0], mix.inputs[2])
            links.new(mix.outputs[0], out.inputs["Surface"])
        else:
            emission.inputs["Color"].default_value = mat.diffuse_color
            links.new(emission.outputs[0], out.inputs["Surface"])


def setup_render(width, height):
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.5, 0.52, 0.55, 1.0)
    scene.world = world
    bpy.ops.object.light_add(type="SUN", location=(2, -3, 5))
    bpy.context.object.data.energy = 3.0
    bpy.context.object.rotation_euler = (math.radians(55), 0, math.radians(30))
    cam_data = bpy.data.cameras.new("C")
    camera = bpy.data.objects.new("C", cam_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 2.7
    camera.location = (0, -4.2, 0.95)
    camera.rotation_euler = (math.radians(90), 0, 0)


def main():
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = [int(v) for v in args.frames.replace(" ", "").split(",") if v]

    armature, mesh = import_model(Path(args.pmx), not args.no_physics)
    import_motion(armature, mesh, Path(args.vmd))
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(frames)

    driven_bones, driven_morphs = action_channels()
    existing_bones = {b.name for b in armature.data.bones}
    shape_keys = [kb.name for kb in mesh.data.shape_keys.key_blocks] if mesh.data.shape_keys else []
    missing_bones = sorted(b for b in driven_bones if b not in existing_bones)
    missing_morphs = sorted(m for m in driven_morphs if m not in shape_keys)

    rigid_bodies = rigid_tracks = 0
    if not args.no_physics:
        rigid_bodies, rigid_tracks = build_physics(mesh)

    setup_render(args.width, args.height)
    with_png = bool(args.png)
    if with_png:
        emission_materials()

    stats = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for frame in frames:
        for step in range(scene.frame_current + 1, frame + 1):
            scene.frame_set(step)
        scene.frame_set(frame)
        depsgraph.update()
        evaluated = mesh.evaluated_get(depsgraph)
        data = evaluated.to_mesh()
        coords = [v.co.copy() for v in data.vertices]
        non_finite = sum(1 for c in coords if not all(map(math.isfinite, (c.x, c.y, c.z))))
        bbox = None
        if coords:
            xs = [c.x for c in coords]
            ys = [c.y for c in coords]
            zs = [c.z for c in coords]
            bbox = [round(min(xs), 4), round(max(xs), 4), round(min(ys), 4),
                    round(max(ys), 4), round(min(zs), 4), round(max(zs), 4)]
        evaluated.to_mesh_clear()
        if with_png:
            scene.render.filepath = str(out / f"f{frame:04d}.png")
            bpy.ops.render.render(write_still=True)
        stats.append({"frame": frame, "vertices": len(coords),
                      "non_finite": non_finite, "bbox": bbox})

    report = {
        "pmx": str(args.pmx),
        "vmd": str(args.vmd),
        "bones_total": len(existing_bones),
        "driven_bones": len(driven_bones),
        "driven_bones_missing": missing_bones,
        "morphs_total": max(0, len(shape_keys) - 1),
        "driven_morphs": len(driven_morphs),
        "driven_morphs_missing": missing_morphs,
        "rigid_bodies": rigid_bodies,
        "rigid_driven_bones": rigid_tracks,
        "frames": stats,
    }
    (out / "motion-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "frames"},
                     ensure_ascii=False, indent=2))
    print(f"frames checked: {len(stats)}; report: {out / 'motion-report.json'}")


if __name__ == "__main__":
    main()
