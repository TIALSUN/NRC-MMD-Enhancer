# Blender 动态炫彩

NRC 统一使用“导出 MMD”按钮，自动跟随当前配色：原色时只导出 PMX 和普通贴图；启用炫彩并选择配色/基础花纹后，同一按钮同时生成 PMX、炫彩参数/贴图及动态 .blend。PMX 本身不执行 Blender 材质，动态播放使用生成的 .blend。

## 实现入口

项目 `work/mmd-native-clothing-20261020/app/mmd/dynamic-chroma.py` 从最终序列化 PMX 干净回读生成场景，脚本由转换器的 `--dynamic-chroma <参数JSON>` 调用。server.js 只接受内置配色 ID 与已知花纹，释放构建器、复制选中纹理并提供材料遮罩映射；前端从 `nrc-chroma-change` 取得当前选择，并在点击时快照配色对象；切回原色清空炫彩选择。当前前端入口位于同一累计目录的 `app/public/app.js`，独立动态导出按钮已移除。

输出：PMX、Tex、Chroma、炫彩参数.json、动态炫彩.blend、使用说明与 report。构建器仅修改有映射的衣服材质；原色、基础图、遮罩、流动底纹、花纹和闪粉图全部 pack 到场景，参数中只保留实际命中的相对路径遮罩。无可用炫彩材质时明确失败，不能输出空场景冒充成功。

## 动态规则

- 时间为 `(frame-1)*fps_base/fps`，由简单驱动表达式和场景属性决定，不用帧变化 Python handler；拖动、倒放、改变帧率及重开场景可用。
- 遮罩 R 限定染色区域；底纹 RG 分配双色，按原色线性明度调色。底纹 UV 按配色 tiling 和 flow 滚动。
- 花纹使用原图 B 形状、G 相位、R 阈值与四个颜色，周期显隐按现有 chroma-core.mjs 的公式建立节点。
- 闪粉使用选中星图、密度与平铺、`(0.0056,0.25)` 流动及四秒循环相位，与当前预览近似保持一致；没有复原 UE 随机邻格查询、折射和完整游戏光照。表面使用 Blender Principled 的近似光泽。
- 默认30fps、1—120帧。打开 .blend 即可播放材质；载入 VMD 用已安装 MMD Tools，动作前按模型留静止缓冲，物理另构建和烘焙。

## 验证与本机产物

两种配色以 PC2 克莱因龙连衣 2071090101 验证：暗夜拾光的底纹/花纹，月涌狂想的花纹/闪粉。重开场景确认使用中图片均 pack，30fps第31帧与60fps第61帧的时间均为1秒，多帧实际渲染存在颜色差异。手臂露肤回归要求不删面、不移动无遮盖皮肤，覆盖区内收不超过3mm且 Morph 差值不变。样例已恢复双臂。

证据：`work/mmd-dynamic-chroma-20261020/scene-validation/`、`test-arm-skin*.log`；动态和原有导出接口5+18项测试通过。`outputs/NRC-mmd-dynamic-chroma-installed-verification-20261020.json` 记录安装版真实服务导出结果。交付样例位于 `outputs/mmd-dynamic-chroma-20261020/`，以最终交付清单中的两个模型目录为准。

验证未覆盖全部服装/配色或 MikuMikuDance.exe。该输出是 Blender 场景，不是 MME .fx；不要把节点反向写回 PMX 后宣称动态已保留。
