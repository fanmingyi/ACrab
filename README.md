# ACrab

<p align="center">
  <img src="ACrab.png" width="200" alt="ACrab Logo">
</p>

ACrab 是一个 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) Skill，通过 ADB 驱动 Android 设备，结合视觉大模型（VLM）实现智能 UI 元素定位，完成自动化测试、界面操作等任务。

## 特性

- **自然语言驱动** — 用自然语言描述任务，Claude Code 自动拆解并逐步执行
- **双定位策略** — 优先使用 `uiautomator` 元素树精确定位，元素树不可用时自动切换 VLM 视觉定位
- **多推理后端** — 支持本地 MLX 推理、OpenAI 兼容 API、远程 HTTP 服务三种后端
- **异常检测与恢复** — 自动检测应用崩溃/ANR，归档日志和截图，支持弹窗自动处理

## 快速开始

### 前置条件

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Android 设备通过 USB 连接，已开启 USB 调试
- ADB（macOS: `brew install android-platform-tools`）
- Python 3.10+、Pillow

### 安装

```bash
# 克隆到 Claude Code 可访问的目录
git clone https://github.com/yourname/ACrab.git

# 安装 Python 依赖
pip install Pillow
```

根据你选择的推理后端，安装对应依赖：

| 后端 | 安装 | 说明 |
|------|------|------|
| `local` | `pip install mlx-vlm` | Apple Silicon Mac 本地推理（推荐） |
| `api` | `pip install openai` | OpenAI 兼容 API（如 DashScope） |
| `vllm` | `pip install openai` | 局域网 vLLM 服务器（如 Qwen3-VL） |
| `remote` | 无额外依赖 | Docker 容器内调用宿主机 MLX 服务 |

### 配置

编辑 `config.properties`：

```properties
# 推理后端: local / api / remote
backend=local

# local 模式 - 模型（HuggingFace ID 或本地路径）
local_model=mlx-community/Qwen2.5-VL-7B-Instruct-4bit

# api 模式 - API Key 环境变量名（不要直接写 key）
api_key_env=DASHSCOPE_API_KEY
api_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
api_model=qwen-vl-max

# vllm 模式 - 局域网 vLLM 服务地址（OpenAI 兼容接口）
vllm_base_url=http://YOUR_VLLM_SERVER_IP:8000/v1
vllm_model=Qwen/Qwen3-VL-8B-Instruct

# remote 模式 - 宿主机服务地址
remote_url=http://host.docker.internal:8420

# 调试模式（保存标注 bbox 的图片到 tmp/）
debug=false
```

### 使用

在 Claude Code 中直接调用 Skill：

```
/ACrab 打开设置，连接 Wi-Fi "MyNetwork"
/ACrab 打开微信，给张三发一条消息"明天开会"
/ACrab 打开应用商店，搜索并安装"某某App"
```

Claude Code 会自动完成环境自检、任务分解、逐步执行，并在每步操作前声明意图。

## 组件说明

| 文件 | 说明 |
|------|------|
| `SKILL.md` | Skill 定义文件，包含完整的操作规范和 prompt |
| `visual_locator.py` | 视觉定位工具，调用 VLM 识别截图中的 UI 元素并返回坐标 |
| `visual_locator_server.py` | HTTP 服务端，在 Mac 上暴露本地 MLX 推理能力供远程调用 |
| `screenshot.sh` | 通过 ADB 截图并保存到 `tmp/` 目录 |
| `keyboardservice-debug.apk` | ADBKeyBoard，用于可靠的中文/长文本输入 |
| `config.properties` | 运行时配置（后端、模型、调试开关等） |

## 视觉定位工具

`visual_locator.py` 可独立使用：

```bash
# 定位截图中的 UI 元素
python visual_locator.py screenshot.png "蓝色的登录按钮，在页面底部"
# => {"x1": 120, "y1": 340, "x2": 280, "y2": 400, "center": [200, 370]}

# 指定屏幕分辨率（修正坐标映射）
python visual_locator.py screenshot.png "搜索框" --screen-size 1080x2400

# 环境自检
python visual_locator.py --selfcheck
```

### vLLM 模式（局域网场景）

在局域网内的 GPU 服务器上部署 vLLM 服务，本机通过 OpenAI 兼容 API 调用。vLLM 返回 0-1000 归一化坐标，`visual_locator.py` 会自动映射到实际屏幕分辨率。

```bash
# GPU 服务器上启动 vLLM（以 Qwen3-VL 为例）
vllm serve Qwen/Qwen3-VL-8B-Instruct --max-model-len 4096

# config.properties 设置
# backend=vllm
# vllm_base_url=http://192.168.1.100:8000/v1
# vllm_model=Qwen/Qwen3-VL-8B-Instruct
```

### Remote 模式（Docker 场景）

在 Mac 宿主机上启动推理服务，Docker 容器内通过 HTTP 调用：

```bash
# Mac 宿主机
python visual_locator_server.py --port 8420 --preload

# Docker 容器内 config.properties 设置
# backend=remote
# remote_url=http://host.docker.internal:8420
```

## 工作流程

```
用户下达任务
    ↓
环境自检（ADB / 设备 / 键盘 / VLM）
    ↓
任务分解为子目标
    ↓
┌─→ 截图 + Read 看图 + uiautomator dump
│       ↓
│   决策 + 声明操作意图
│       ↓
│   定位（元素树优先，不可用时 VLM 视觉定位）
│       ↓
│   执行 ADB 操作
│       ↓
│   判断结果（成功/走错/无效）
└───────┘
```

## 致谢

- [MobileAgent](https://github.com/x-plug/mobileagent) — 本项目在视觉定位与多步骤移动端自动化的思路上借鉴了 MobileAgent 的部分设计思想
- [ADBKeyBoard](https://github.com/senzhk/ADBKeyBoard) — 本项目内置了 ADBKeyBoard 软键盘（`keyboardservice-debug.apk`），通过 ADB broadcast 方式输入文本，解决了原生 `adb shell input text` 不支持中文及特殊字符的问题。使用前需在设备上安装该 APK 并在系统设置中启用 ADB Keyboard 输入法

## License

[Apache License 2.0](LICENSE)
