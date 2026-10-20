# MMD 材质、卡通渲染与描边

## 导入后材质长什么样

MMD Tools 导入模型后，每个材质的节点树里是几件固定东西：

- `mmd_shader` 节点组：输入端有 `Ambient Color`、`Diffuse Color`、`Specular Color`、`Reflect`、`Alpha`、`Base Tex`、`Toon Tex`、`Sphere Tex`。
- 贴图节点：`mmd_base_tex`（基础色）、`mmd_toon_tex`（卡通阴影色）、`mmd_sphere_tex`（环境球面贴图）、`mmd_tex_uv`。
- MMD 自己的参数存在 `material.mmd_material` 上：`name_j` / `name_e`、`alpha`、`ambient_color`、`diffuse_color`、`specular_color`、`shininess`、`is_double_sided`、`edge_color`、`edge_weight`、`sphere_texture_type`、`is_shared_toon_texture`、`toon_texture`。

**调参数的入口是 `mmd_material` 的属性**（改了会驱动 `mmd_shader`），不要直接删节点或改 `mmd_shader` 的默认值，否则和 PMX 数据脱钩，重导就丢。

## 卡通渲染：MMD_Toon 节点组

可使用节点组 `MMD_Toon`（配套材质 `MMD_Toon_Example`、`MMD_Toon_Outline`）组织这套渲染。先检查当前场景是否存在；缺少时按下述结构创建并保存，不假定历史内存数据块仍在。

它的结构就是卡通渲染的标准做法，EEVEE 专用：

```
Diffuse BSDF → Shader to RGB → RGB to BW → Map Range(阈值±羽化)  ──┐
                                                                    ├→ Mix(Shadow Color, Base Tex) → +Rim → Emission → Mix Shader(by Alpha) → 输出
Layer Weight(Facing) → ColorRamp → × Rim Strength ────────────────┘
```

要点：

- **Shader to RGB 只能在 EEVEE 用**，正是它把"光照结果"变成可再加工的数值，硬边明暗交界就是这么来的。Cycles 走不了这条路。
- `Map Range` 的 From Min/Max 接 `阈值 ∓ 羽化`，羽化调小到 0.01 就是刀切一样的边。
- 输出用 **Emission**，等于关掉引擎的二次着色，颜色完全可控。
- 头发、裙子的透明用 `Alpha` 输入（内部 Mix Shader 混合 Transparent BSDF）。

输入：`Base Tex`、`Shadow Color`、`Shadow Threshold`、`Shadow Feather`、`Rim Color`、`Rim Strength`、`Alpha`。

**实操提醒**：光照方向决定明暗交界在哪。光正对镜头时整面都是亮部，看不到分层——这不是节点坏了。想要经典效果，让光从侧上方来。MMD 模型的 `mmd_base_tex` 直接接到 `Base Tex` 上就沿用原贴图。

## 描边

两条路，按需要选：

**A. MMD Tools 自带**：选中模型 → `bpy.ops.mmd_tools.edge_preview_setup(action="CREATE")`（清理用 `"CLEAN"`）。它给每个网格加 `mmd_edge_preview` 修改器（Solidify 反向壳）和 `mmd_edge.<材质名>` 材质，粗细由每个材质的 `edge_weight` 决定，颜色取 `edge_color`——也就是说 **PMX 里作者设好的描边参数可以直接复用**。必须选中 MMD 模型（内部要 `find_root_object`），否则报错。

**B. 自己搭反向壳**（想完全控制时）。实测在 Blender 5.2 + EEVEE 下，**不要指望 `use_backface_culling` 把近侧的壳剔掉**——反向壳会整片盖住模型，画面全黑。可靠做法是在描边材质里按法线朝向混合：

```
Geometry(Backfacing) → Mix Shader.Factor
   输入 1（正面 = 壳的远侧）→ Emission 黑色   ← 这就是描边
   输入 2（背面 = 壳的近侧）→ Transparent BSDF ← 让开
```

配合 `Solidify`：`thickness` = 描边粗细、`offset = 1`、`use_flip_normals = True`、`material_offset` 指向描边材质槽。

## 透明与发黑的常见原因

- **头发/裙子整块发黑或背面消失**：MMD 靠 `is_double_sided` 控制双面。转出 Blender 后如果只看到单面，先查这个参数。
- **该透明的不透明、该实心的透明**：`bpy.ops.mmd_tools.toggle_transparent_materials(action="SHOW"/"RESTORE")` 一键开关/还原（SHOW 把 alpha 设为 1.0，RESTORE 从 `mmd_material` 取回）。
- **多层 alpha 排序错乱**（头发透出头皮/背景）：EEVEE 里用 Alpha Hashed / Dithered，别用混合透明排序。
- **球面贴图（spa/sph）失效**：`sphere_texture_type` 决定"乘"还是"加"，MMD 用它做环境反射；转 Principled 时用 Layer Weight / Fresnel 驱动混合来近似。

## 转成 Blender 原生材质

要给 Cycles 或重度改造时用 `convert_materials` / `convert_materials_for_cycles` / `convert_bsdf_materials`。**转换不可逆地改写节点树**，先存盘或复制一份模型。

视口着色用 `set_glsl_shading` / `set_shadeless_glsl_shading` / `reset_shading`，只影响视口，不影响渲染。

