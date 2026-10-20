# NRC 修复版代码覆盖层

本目录包含 NRC 的修复代码，不包含任何游戏模型、贴图、解码配置、着色器或 Pak 文件。

它需要用户本机已有 NRC 基础安装及配套运行时资源。`apply.ps1` 会：

1. 解包基础 `app.asar`。
2. 检查基础包是否已有 MMD Morph、服装配置、炫彩资源与原生衣料物理数据。
3. 覆盖恢复的代码文件。
4. 重新打包并逐文件回读校验。
5. 仅在显式 `-Install` 时备份并替换当前安装。

示例：

```powershell
.\apply.ps1 -BaseAsar "E:\NRC服装预览工具-修复版\resources\app.asar" `
  -OutputAsar ".\NRC-mmd-fixed.asar"

.\apply.ps1 -BaseAsar "E:\NRC服装预览工具-修复版\resources\app.asar" `
  -InstallRoot "E:\NRC服装预览工具-修复版" -Install
```

如果基础包缺少运行时资源，先使用 `../skill/mmd-blender/references/asset-acquisition.md` 从当前游戏客户端生成资源树。
