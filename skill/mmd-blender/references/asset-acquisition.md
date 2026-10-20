# 首次运行与游戏资源获取

发布包只包含代码、脚本、映射和文档，不包含游戏模型、贴图、配置解码结果、着色器或 PKA/PAK 文件。首次运行由技能在用户本机定位客户端并生成资源，不把历史电脑的导出目录当成常量。

## 1. 自动发现

运行：

```powershell
& scripts/detect-runtime.ps1 -OutFile runtime.json
```

脚本从 FModel 设置、常见安装目录、NRC 配置与 `PATH` 识别游戏目录、CUE4Parse bundle、Detex、Blender、解码器、NRC 安装和输出根。缺失项显示为 `null`，不要猜一个不存在的路径。可以显式传入 `-GameDirectory`、`-FModelSettings`、`-NrcInstallRoot`、`-NrcConfig`。

密钥只在 `NRC_AES` 或 FModel 已授权配置中存在时读取；不得把密钥写入输出清单、日志、技能、命令记录或交付包。离线验证已有 PMX/VMD 不需要密钥。

FModel 没有密钥时，可按 SKILL 的“密钥来源与使用”读取用户明确授权的原始对话消息，仅在内存中设置当前进程的 `NRC_AES`；不要用历史片段猜测新版本密钥。缺少授权输入时完成不需要密钥的文件盘点，并明确请求缺失项。

## 2. 必需资源

以 `references/required-assets.json` 为清单，从当前客户端版本获取：

- 配置表：`FASHION_ITEM_CONF`、`FASHION_SUITS_CONF`、`SALON_ITEM_CONF`、`CLOSET_TAB_CONF`、头饰/背包偏移与转换表；炫彩另取配色、花纹、玻璃和赛季表。
- 角色资源：`ArtRes/AnimSequence/Human/PC/PC1|PC2` 下的主模型、默认服装槽、眼型组件、帽发组件、Morph 相关网格与动画。
- 贴图与材质：按当前物品/材质实例解析，不按名称猜测共享关系。
- 原生弹簧配置：`ABP_CharacterBase_New` 及相关动画蓝图数据，用于生成 `native-clothing-physics.json`。
- 炫彩动态资源：游戏纹理、花纹图标、闪粉/流动底纹，以及需要取证时的着色器库。

获取时必须保留资产来源、客户端版本和哈希。优先复用用户已解包的当前版本目录；目录不存在或版本不同，再从 Paks 增量导出。不要用技能里的历史样本替代当前客户端。

## 3. 获取方式

客户端需要挂载时，按当前环境使用 CUE4Parse/FModel；配置需要 `decode_bin.py` 与对应 Schema/本地化。可复用 `roco-unpack` 技能的“新版执行流程”，但只完成 MMD/NRC 所需范围。执行细节以当前解析器帮助和实际 API 为准，不照抄旧版参数。

技能附带的直接导出入口：

```powershell
# 列出当前客户端索引，建立目标清单
& scripts/cue-list-index.ps1 -Pattern 'PC1|PC2' -OutFile runtime/index-all.txt `
  -ParserBundle $runtime.cue4parse_bundle -FModelSettings $runtime.fmodel_settings

# 骨骼网格；导出器显式开启 morph target，必要时退回最高 LOD
& scripts/cue-export-meshes-morph.ps1 -TargetFile runtime/meshes.txt `
  -OutDir runtime/exports -ReportPath runtime/mesh-report.json `
  -ParserBundle $runtime.cue4parse_bundle -FModelSettings $runtime.fmodel_settings

# 按计划解码贴图
& scripts/cue-export-textures.ps1 -PlanJson runtime/texture-plan.json `
  -StageDir runtime/textures -ReportPath runtime/texture-report.json `
  -ParserBundle $runtime.cue4parse_bundle -FModelSettings $runtime.fmodel_settings `
  -DetexPath $runtime.detex_dll
```

解析器 API 或版本变化时，先针对一个骨骼网格、一个静态网格和一张贴图做小样本验证，再批量。不能把脚本无报错当作完整挂载；检查 mounted/unloaded 和索引条目数。

从 Paks 导出原始配置 bytes、Schema 与本地化后，用随技能提供的 `scripts/decode_bin.py` 解码，避免依赖某台机器的外部解码器：

```powershell
& python scripts/decode_bin.py runtime/raw/BinDataCompressed --batch `
  --schema-dir runtime/raw/BinConf --loc-dir runtime/raw/BinLocalize/dev_CN `
  --out-dir runtime/config
```

CUE4Parse/FModel、Detex 或当前版解码 Schema 缺失时，技能应获取匹配当前游戏版本的开源工具或从用户项目现状定位它们，记录实际版本；不得提交第三方二进制和游戏资源的混合归档，也不得用旧 Schema 猜测当前配置。

推荐输出结构：

```text
runtime/
|-- config/                 # 当前版配置与来源清单
|-- exports/PC1|PC2/       # 骨骼网格、眼型、帽发、贴图
|-- expression-v1/         # 带 Morph 的兼容 GLB 与 manifest
|-- eye-expression-v1/     # 模块化眼型/发型兼容资源
|-- native-clothing-physics.json
`-- asset-index.json
```

`expression-v1` 与 `eye-expression-v1` 是由游戏资产派生的兼容资源，仍属于游戏资源范围，不放进公共代码包。运行时由技能生成或从用户已有 NRC/资源库定位。

## 4. NRC 接入

修复版 NRC 以代码覆盖层发布。`nrc-fixed/apply.ps1` 从用户已有 `app.asar` 提取完整基础应用，验证基础包已经具备游戏衍生运行时资源，再覆盖代码并重新打包。基础包里的模型、贴图和配置保留在用户本机，不进入技能交付 ZIP。

如果基础包缺少运行时资源，先完成第 2、3 节并形成兼容资源树，再将其接入 NRC 的 `mmd/` 与 `public/` 目录。装机前后分别记录哈希；旧包只做新增备份，不覆盖或降级其他版本。

## 5. 验收

至少检查：

1. 资源根、配置表、主模型、默认槽、眼型与 Morph 清单均存在且来自同一客户端版本。
2. NRC 实际服务导出 PC1/PC2 默认、PC2 连衣与 PC1 炫彩代表项。
3. 最终 PMX 回读确认服装权重骨、标准骨、IK、Morph 和贴图相对路径。
4. 报告 `clothing_bones_summary` 与 NRC `result.boneSummary` 一致。
5. 发布包审计确认没有 `.pak`、`.uasset`、`.uexp`、`GLB/glTF`、游戏贴图或解码表。

缺少游戏安装、授权密钥、解析器或 NRC 基础包时，明确列出缺失输入；不能把“未获取资源”写成导出通过。
