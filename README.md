<!-- 欢迎阅读 Ark-Picit 说明文档 -->
<div align="center" style="text-align:center">
   <h1> Ark-Picit </h1>
   <p>
      Arknights Pixel Art Painter | 明日方舟奇象巡展像素画创作工具 <br>
      <code><b> v0.1.0 </b></code>
   </p>
   <p>
      <img alt="GitHub Top Language" src="https://img.shields.io/github/languages/top/isHarryh/Ark-Picit?label=Python">
      <img alt="GitHub License" src="https://img.shields.io/github/license/isHarryh/Ark-Picit?label=License"/>
   </p>
</div>

## 介绍 <sub>Intro</sub>

### 项目定位

ArkPicit 是一个基于 PySide6 的面向《明日方舟》奇象巡展绘画模式的像素画创作工具。它提供了一套完整的像素画编辑器，用户可以基于预设的规则集来创作像素画，并通过 ArkPicCode 分享自己的作品。

### 实现的功能

1. **像素画编辑器**：复原了游戏中的像素画编辑器功能。
2. **从图片智能创建**：从本地文件或剪贴板导入图片，通过交互式裁切和色彩拟合，将图片自动转换为像素画。
3. **ArkPicCode 分享码**：每幅画作可编码为一段 Base64 文本分享码，在程序内输入分享码即可一键导入他人作品。
4. **本地画廊管理**：本地保存、浏览和编辑已有画作，支持名称、描述和预览图等显示。

## 使用方法 <sub>Usage</sub>

本项目使用 **Python 3.12** 进行开发。推荐使用 uv 来安装依赖：

```bash
uv sync --group dev
```

随后在 uv 创建的虚拟环境中运行：

```bash
python main.py
```

## 开发 <sub>Development</sub>

### 技术栈

| 层       | 技术                                  |
| :------- | :------------------------------------ |
| 语言     | Python 3.12                           |
| GUI 框架 | PySide6 6.11 + pyside6-fluent-widgets |

### 核心数据模型

#### ArkPicRule

一个 ArkPicRule 对象表示一套像素画规则，包括画幅尺寸、色板定义和默认色。

- 色板中的颜色为十六进制字符串（"RRGGBB" 格式），ID 从 1 开始计算，最多支持 255 种颜色。
- 规则哈希用于高效比较两套像素画规则是否一致，参与运算的元素是色板中的所有颜色值以及默认色 ID。

```
ArkPicRule
  ├── width / height    画幅尺寸 (1-255)
  ├── colors[]          色板
  ├── default_color_id  默认色 ID
  └── color_hash        规则哈希 (CRC-16/CCITT)
```

#### ArkPic

一个 ArkPic 对象表示一副基本像素画。每个像素画必须绑定一个 ArkPicRule，以便确定画幅尺寸和色板信息。

```
ArkPic
  ├── rule        绑定的 ArkPicRule
  └── grid[y][x]  2D 像素网格 (填充颜色 ID，不允许为空值或零值)
```

#### ArkPicCode

ArkPicCode 是一种 URL Safe Base64 文本编码，用于分享画作。原始字节流先经过 zlib 压缩再编码，字节流的格式如下：

```
[U8 width] [U8 height] [U16 rule_hash] // 画幅尺寸和规则哈希
[U8 name_len] [name_bytes...] // 画作名称，UTF-8 编码，0-255 字节
[U8 desc_len] [desc_bytes...] // 画作描述，UTF-8 编码，0-255 字节
[U8 × (width × height)] // 平展后的像素颜色 ID，保证均为非零值
[0x00] // 终止字节
```

解码程序需要拥有相同 `color_hash` 的 `ArkPicRule` 才能将像素 ID 映射回具体颜色，这保证了分享码在不同规则集之间不会混淆。

### 目录结构

```
Ark-Picit/
├── main.py    # 应用入口
├── src/
│   ├── app/   # 主窗口、配置、信号总线
│   ├── core/  # ArkPic 数据模型、ArkPicCode 编解码、存储
│   └── gui/   # GUI 页面、控件、对话框
└── gallery/   # 用户画作存储 (运行时生成)
```

## 许可证 <sub>Licensing</sub>

本项目基于 **BSD-3 开源协议**。任何人都可以自由地使用和修改项目内的源代码，前提是要在源代码或版权声明中保留作者说明和原有协议，且不可以使用本项目名称或作者名称进行宣传推广。
