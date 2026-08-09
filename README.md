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
2. **从图片智能创建**：从本地文件或剪贴板导入图片，通过交互式裁切、多种采样方式（最近邻/双线性/双三次）与选色方式（RGB 线性/平方误差、灰阶、多数投票）将图片自动转换为像素画。
3. **ArkPicCode 分享码**：每幅画作可编码为一段 Base64 文本分享码，在程序内输入分享码即可一键导入他人作品。
4. **本地画廊管理**：本地保存、浏览和编辑已有画作，支持名称、描述和预览图等显示。
5. **游戏内自动作画**：连接游戏窗口（Win32）或模拟器（adb）后，自动完成区域校准（滑条预置、锚点识别、网格构建）、画布差异计算与逐色绘制，支持增量模式与绘制速度调节。此外，也支持识别游戏画布当前内容并载入编辑器中，作为新画作继续创作。

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
| 图像处理 | OpenCV + NumPy                        |

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
├── main.py       # 应用入口
├── assets/       # 自动化模板图像（720p 归一化空间）
├── src/
│   ├── app/      # 主窗口、设备管理、信号总线
│   ├── auto/     # 自动化：设备抽象（Win32/adb）、模板/颜色匹配、Automator 门面
│   ├── core/     # 数据模型、ArkPicCode 编解码、量化、存储、游戏内任务（tasks/）
│   ├── gui/      # GUI 页面、控件、对话框
│   └── utils/    # 路径等工具
└── gallery/      # 用户画作存储 (运行时生成)
```

### 自动绘图流程

「自动作画」功能通过 `src/auto` 自动化包驱动游戏窗口完成游戏内像素画绘制。整体流程拆分为两个阶段：区域校准与验证、自动绘制。区域校准与画布内容读取（`src/core/tasks`）同时被「从游戏画布导入」功能复用。

**图 1：区域校准与验证**

```mermaid
flowchart TD
    A([Start]) --> B["Detect canvas page<br/>in game window"]
    B --> C{"Is in canvas page?"}
    C -- "No" --> ERR1["Abort: not in canvas page<br/>save error screenshot"]
    C -- "Yes" --> D["Match scale slider<br/>drag it to the bottom"]
    D --> E["Match LT / RB canvas anchors"]
    E --> F["Build canvas grid (rows x cols)<br/>and palette region"]
    F --> G["Read canvas content<br/>quantize by majority voting"]
    G --> H["Compute diff cells vs the painting"]
    H --> I["Show verification dialog<br/>incremental toggle, drawing speed"]
    I --> J{"User choice"}
    J -- "Cancel" --> Z([End])
    J -- "Start Drawing" --> X(["Continue: drawing flow"])
    ERR1 --> Z
```

**图 2：自动绘制**

```mermaid
flowchart TD
    A([Start Drawing]) --> B{"Incremental mode<br/>and no diff?"}
    B -- "Yes" --> M1["Success: canvas already matches<br/>skip painting"]
    B -- "No" --> C["For each used color (lowest ID first)"]
    C --> D["Find color swatch<br/>in the palette ROI"]
    D --> E{"Found?"}
    E -- "No" --> F1["Scroll palette up, retry"]
    F1 --> F2{"Found?"}
    F2 -- "No" --> F3["Scroll palette down, retry"]
    F3 --> F4{"Found?"}
    F4 -- "No" --> ERR2["Abort: color not found<br/>save error screenshot"]
    E -- "Yes" --> G["Click the swatch"]
    F2 -- "Yes" --> G
    F4 -- "Yes" --> G
    G --> H["Click every cell of this color<br/>in the canvas<br/>(incremental: only diff cells)"]
    H --> I{"More colors?"}
    I -- "Yes" --> C
    I -- "No" --> Z
    M1 --> Z([End])
    ERR2 --> Z
```

### 实现细节注意事项

1. **模板缩放约定**：模板按固定短边（720p）采集，属于归一化空间资产，运行时永不缩放模板；匹配时把设备截图缩放到归一化空间再原样匹配。

2. **模板匹配的方差陷阱**：`cv2.matchTemplate`（TM_CCOEFF_NORMED）对纯色零方差输入是未定义行为，会返回假阳性，因此须对模板做标准差守卫并对分数做有限性检查。纯色色块（如色板取色）不能走模板匹配，应使用颜色敏感匹配。

3. **Win32 光标纪律**：仅在 Win32 控制器中，游戏通常会读取 `GetCursorPos`，因此每次点击/拖动前必须把真实光标精确移动到目标像素；截图前把光标停在窗口客户区右下角并等待一小段时间，防止鼠标光标污染画面。瞬时点击会被部分情景漏检，需通过 `hold_ms` 参数保持按压。

4. **Win32 截图纪律**：Win32 以非管理员模式运行程序时，后台模式下 `PrintWindow` 可能会返回全黑画面，会自动回退到 `BitBlt` 截屏。尽量确保程序是以管理员方式运行。

5. **随机化纪律**：自动化流程中唯一允许的随机化是 `random_ratio`（中心 p% 区域均匀随机），仅用于 `click_region`/`click_match`/`click_template`；滑条与色板的拖动采用点对点精确，不引入任何随机。

6. **画布读取的投票量化**：从游戏画布读取内容（绘制前的差异计算、画布导入）使用投票降采样：每个目标格统计源区域内出现次数最多的精确像素颜色，平票时取众数颜色的算术平均。格子边框与水印文本因此被自然压制，无需容差参数。

## 许可证 <sub>Licensing</sub>

本项目基于 **BSD-3 开源协议**。任何人都可以自由地使用和修改项目内的源代码，前提是要在源代码或版权声明中保留作者说明和原有协议，且不可以使用本项目名称或作者名称进行宣传推广。
