# NRC MMD 修复版与 mmd-blender 技能

一个面向《洛克王国：世界》NRC 服装预览工具的非官方 MMD 导出增强项目。项目提供 NRC 代码修复覆盖层和 `mmd-blender` 技能，用于从用户本机资源生成 PMX、动态炫彩 Blender 场景、动作验证和舞蹈视频。

> 原项目：**NRC 服装预览工具**  
> 原作者：**浅草疏影（Sparse Shadow）**  
> 本项目为非官方修改版，不代表原作者认可或维护。

## 功能

- 统一“导出 MMD”按钮：原色生成 PMX，炫彩同时生成 PMX、参数、贴图和动态 `.blend`。
- 保留服装实际使用的骨骼、父级和四权重，并在 NRC 显示“骨骼 / 服装骨 / 新增骨”摘要。
- 原生衣服弹簧骨与 MMD 刚体近似，`WeiBa` 保留骨骼和权重但不自动建刚体，避免舞摆被错误甩开。
- 原生 Morph、表情、口型、眼型、眼骨、足 IK/D/EX 与 MMD 标准骨。
- PMX 干净回读、真实 VMD 驱动、逐帧物理烘焙、MP4 编码和全片解码验证。
- 技能可从本机当前客户端发现并获取所需配置、网格、贴图、Morph 和物理数据。

## 不包含游戏文件

本仓库不包含 Pak、`.uasset`、`.uexp`、GLB/glTF、游戏贴图、解码配置、着色器、动作或音频。

首次使用时：

1. 用 `skill/mmd-blender/scripts/detect-runtime.ps1` 发现游戏、解析器、Blender、NRC 和配置根。
2. 按 `skill/mmd-blender/references/required-assets.json` 从本机当前客户端获取资源。
3. 用 `skill/mmd-blender/scripts/check-assets.ps1` 检查运行时资源。
4. 用 `nrc-fixed/apply.ps1` 从已有 NRC 基础包生成或安装修复版 ASAR。

## 快速开始

```powershell
# 生成用户本机修复版 ASAR
.\nrc-fixed\apply.ps1 `
  -BaseAsar "E:\NRC服装预览工具-修复版\resources\app.asar" `
  -OutputAsar ".\NRC-mmd-fixed.asar"

# 备份并安装
.\nrc-fixed\apply.ps1 `
  -BaseAsar "E:\NRC服装预览工具-修复版\resources\app.asar" `
  -InstallRoot "E:\NRC服装预览工具-修复版" -Install
```

更完整的资源获取流程见 [skill/mmd-blender/references/asset-acquisition.md](skill/mmd-blender/references/asset-acquisition.md)。

## 环境

- Windows、Node.js 22+。
- 已安装 NRC 服装预览工具基础包。
- Blender 5.2 LTS 与 MMD Tools 4.5.14。
- 读取加密客户端的授权条件、兼容解析器和必要 Schema；或已从当前客户端导出的资源。
- FFmpeg 仅在编码视频时需要。

## 验证范围

已验证 PC1/PC2 默认、PC2 连衣和 PC1 黑白炫彩的代表导出；PMX 回读确认服装权重骨、表情、贴图、衣料物理和无 WeiBa 自动刚体。IRIS OUT 代表动作验证为 465 帧、30fps、15.5 秒，并完成全片视频解码。

Blender/MMD Tools 通过不等于 MikuMikuDance.exe 全动作实机通过。不同客户端、服装搭配、动作和插件组合仍需单独复核。

## 许可与署名

- 修改版代码与文档：**GPL-3.0-or-later**，见 [LICENSE](LICENSE)。
- 原作者：**浅草疏影（Sparse Shadow）**，见 [NOTICE.md](NOTICE.md)。
- 使用前请阅读 [DISCLAIMER.md](DISCLAIMER.md)。

GPL-3.0 不授予任何游戏素材、角色、商标、动作或音乐的使用权。
