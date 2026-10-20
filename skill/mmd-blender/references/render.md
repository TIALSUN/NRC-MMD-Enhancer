# 引擎、灯光与出片（MMD 场景）

## 引擎选择

实测该环境的 engine 枚举里 EEVEE 的标识就是 `BLENDER_EEVEE`（5.x 没有单独 `BLENDER_EEVEE_NEXT` 这个 id）。

- **EEVEE**：二次元/卡通渲染的正解。`Shader to RGB` 只有它支持（见 materials.md 的 toon 节点组），描边、透明处理也快。
- **Cycles**：写实向、真实阴影和折射。代价是 toon 那套 Shader to RGB 用不了，得换成基于数学节点的方案（法线点乘 + ColorRamp 做假光照）。

## 灯光

- MMD 模型的光照观感**几乎完全由光的方向决定**：光正对镜头 → 没有明暗交界，画面发平；光从侧上方约 45° 来 → 明暗交界横跨模型，卡通感最强。
- 用 Sun（平行光）配 `angle` 调软硬，做卡通时保持很小的 angle（硬阴影）。
- 环境光/背景用 World 的 Background 控制；要写实再上 HDRI。

## 视图变换

Blender 默认视图变换是 **AgX**，它会压高光、去饱和，卡通渲染的颜色会被"洗"掉一截。追求鲜艳平涂时换成 Standard 或 Filmic 再调。

## 4.x 之后的 Bloom

EEVEE Next 起渲染属性里没有 Bloom，**辉光改到合成器（Compositor）的 Glare 节点**做，别再找引擎里的开关。

## 输出与交接

- 帧率对齐 MMD 的 30fps（`import_vmd(update_scene_settings=True)` 会设好）。
- 要拿到 Blender 之外用（AE / 其他 3D 软件），用 **ABC（Alembic）** 导出，物理烘焙缓存能一起带走。
- MME 的 `.fx` 效果资产**不能复用**，能带走的只有模型、贴图、动作。
- 已经烘焙过的物理如果还要继续改渲染，别删烘焙，否则要重跑整套流程。

## 舞蹈视频

完整物理动作以逐帧 PNG 为准，再编码为 H.264 MP4；不要用实时预览替代烘焙结果。使用 `scripts/encode-video.py`，指定连续帧目录、起始帧、30fps、动作包 WAV 和输出路径。编码后必须：

- 用 FFmpeg 全片解码，解码错误为 0。
- 核对帧数、30fps、分辨率和时长；IRIS OUT 代表段为场景 31—495，共 465 帧、15.5 秒。
- 保留动作作者署名与配布限制；当前 IRIS OUT 来源为 Pronxy_迫奈熏。
- 单独保留当前帧/抽样预览；视频通过不替代逐件穿模和 Morph 驱动检查。

已交付样本采用 960×720、H.264 CRF 18、AAC 192k、`+faststart`，并在灰底摄影棚场景中检查 WeiBa 稳定衣摆。若输出用于再次编辑，同时保留 `.blend` 和帧序列。
