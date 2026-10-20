---
name: mmd-blender
description: 将洛克王国世界角色与服装按当前选择转换为 MMD PMX 并接入 NRC；自行定位并从本机游戏客户端获取所需资源，处理骨架、服装权重、表情口型、眼型、炫彩与物理，使用 Blender/MMD Tools 验证和出片。不负责一般建模或手工 K 动画。
---

# MMD 转换与 Blender 验证

按需导出当前角色和服装，每次独立文件夹包含 PMX、相对路径 Tex 贴图和 report。默认不全库批量转换；全量检查按用户要求建立覆盖清单。

## 按任务读取

- 模型、选装 JSON 或 NRC 导出：[references/roco-export.md](references/roco-export.md)。
- 原生表情、眼型、口型、标准骨架：[references/face-and-skeleton.md](references/face-and-skeleton.md)。
- 动作、穿模、装机、交付与当前本机入口：[references/validation-delivery.md](references/validation-delivery.md)。
- 动态炫彩 Blender 场景：[references/dynamic-chroma.md](references/dynamic-chroma.md)。
- 物理：[references/physics.md](references/physics.md)；材质与描边：[references/materials.md](references/materials.md)；引擎与出片：[references/render.md](references/render.md)。
- 无游戏文件发布、首次运行与资源获取：[references/asset-acquisition.md](references/asset-acquisition.md)。

## 执行约定

1. 首次运行先执行 `scripts/detect-runtime.ps1`，按 [asset-acquisition.md](references/asset-acquisition.md) 和 `references/required-assets.json` 从用户本机客户端获取资源。确认输入是选装配置、GLB/glTF、PMX 还是 NRC 当前选择；JSON 只提供装配信息，几何与贴图仍需源文件。已有 PMX 可直接进入动作验证。
2. 原生资源优先。用实际配置、网格、骨骼和动画定位问题，原始资源与参考模型保持原样，兼容修正写入转换器或独立派生文件。
3. 优先用 bpy 与现有转换器。已验证 Blender 5.2 LTS + MMD Tools 4.5.14，扩展 ID `bl_ext.user_default.mmd_tools`；先检查本机路径、插件与算子，不假定 MCP 已连接。
4. 验收最终序列化 PMX 的干净回读。分别验证 PC1、PC2；保留标准骨、IK、原生表情与备份，不因局部修复精简既有功能。当前代表模型各 106 个 Morph，不能把数量硬套给其他模型。
5. 分开报告结构、实际动作驱动、逐件视觉、物理播放和 MikuMikuDance.exe 验证；不把 Blender 通过称为原版 MMD 已验收，不承诺任意服装与动作永不穿模。

常用算子：`mmd_tools.import_model`、`import_vmd`、`export_pmx`、`export_vmd`、`validate_model`、`build_rig`、`clean_rig`、`rigid_body_world_update`、`ptcache_rigid_body_bake`、`ptcache_rigid_body_delete_bake`。参数以当前插件 RNA/实现为准。导入后先校验模型，修复算子按诊断使用。

VMD 按 30fps 验证。导入前把当前帧设为 0 或 1，再用 `frame_margin` 和 `update_scene_settings=True`；当前插件仅在这两帧应用 margin。重建骨架可能影响动作与物理，先保存场景。
