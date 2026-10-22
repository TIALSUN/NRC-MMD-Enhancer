# NRC MMD 修复版与 mmd-blender 技能

发布内容只有程序代码、技能说明、测试和获取清单，不包含游戏文件。

## 目录

- `skill/mmd-blender/`：完整技能副本，包含游戏资源自动发现、必需资源清单、MMD 转换、物品解析与兼容规则、服装骨骼摘要、WeiBa 物理策略、炫彩、PMX 回读验证、VMD 动作测试和视频编码说明。
- `nrc-fixed/app-overlay/`：修复版 NRC 代码覆盖层。
- `nrc-fixed/apply.ps1`：把覆盖层应用到用户已有 NRC，或安装到本机。
- `nrc-fixed/patch.mjs` 与 `tools/`：本地 ASAR 解包、重打包、回读校验工具。

## 2026-10-22 更新

- 兼容性普查：1724 件物品 / 346 项沙龙 / 256 套套装 / 157 个反向缺口；静态规则与 142 份真实导出报告交叉验证 0 不一致，动态导出 23 次全部通过。
- 物品解析修正：
  - 未实装物品（只有材质没有网格，50 件 / 7 套）不再让整次导出失败，改为跳过并写 `items_skipped`；
  - 肤色 30000005/6/8 按 `3000000N` 规则推导（此前静默回退默认肤色）；
  - 发色贴图文件名不规范时按色号材质 BaseTex 回退（修复 20101301 的 4 号色）；
  - 性别不符的物品跳过并记录，避免错误拼接；
  - `type_name` 与网格槽位冲突时以槽位为准（12108501 帽子资源落在 Hi，按头饰处理；硬切戴帽发型会悬空或掉脖子）。
- 帽子/头饰：HEADWEAR 偏移只对基础发型定义（1414 条配对 0 条引用 Ht 发型），静态头饰不切 Ht 发型；普通蒙皮帽子不受影响。
- 技能新增 `references/compatibility.md`、`scripts/pmx_verify.py`（58 项 PMX 回读，不依赖 Blender）、`scripts/vmd-motion-test.py`（骨/表情覆盖、物理与采样渲染）。
- 代码覆盖层同步到当前安装版（`mmd/roco-to-mmd.py`、`mmd/dynamic-chroma.py`、`public/app.js`、`server.js`）。

## 为什么不直接提供带模型的完整 NRC

游戏模型、贴图、配置解码结果、着色器和 Pak 属于游戏资源。本 ZIP 明确不包含这些文件。

技能首次运行会：

1. 用 `scripts/detect-runtime.ps1` 发现游戏、解析器、Blender、NRC 和配置根。
2. 按 `references/required-assets.json` 从用户本机当前客户端取得资源。
3. 用 `scripts/check-assets.ps1` 检查 NRC 运行时资源完整性。
4. 从用户已有 NRC 基础包提取完整应用，再套用代码修复。

## 快速使用

```powershell
# 仅生成用户本机的修复版 ASAR
.\nrc-fixed\apply.ps1 `
  -BaseAsar "E:\NRC服装预览工具-修复版\resources\app.asar" `
  -OutputAsar ".\NRC-mmd-fixed.asar"

# 备份并安装
.\nrc-fixed\apply.ps1 `
  -BaseAsar "E:\NRC服装预览工具-修复版\resources\app.asar" `
  -InstallRoot "E:\NRC服装预览工具-修复版" -Install

# 检查基础包是否已有全部游戏运行时资源
.\skill\mmd-blender\scripts\check-assets.ps1 `
  -NrcRoot "E:\NRC服装预览工具-修复版\resources\app" # 若已解包
```

权限、游戏版本和授权要求由用户环境决定；没有客户端、解析器或授权密钥时，技能会报告具体缺失项，不会把旧游戏资源冒充当前版本。

## 验证

- 代表导出：套装 189 全套（含 12108501 归类修正）PMX 2.6MB、顶点 14337、材质 15、骨 269、表情 106、刚体 15、关节 2。
- PMX 回读：58 项检查 56 pass + 2 info，0 warn / 0 fail。
- VMD 动作：IRIS OUT 500 帧，骨通道 76/76、表情通道 42/42 全部命中，物理正常步进，无 NaN，采样帧渲染无爆点/破面。
- 兼容性数据与规则见 `skill/mmd-blender/references/compatibility.md`。
