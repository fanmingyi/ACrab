# ACrab

<p align="center">
  <img src="ACrab.png" width="200" alt="ACrab Logo">
</p>

ACrab 是一个 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) Skill，通过 ADB 驱动 Android 设备，结合视觉大模型（VLM）实现智能 UI 元素定位，完成自动化测试、界面操作等任务。

## 特性

- **自然语言驱动** — 用自然语言描述任务，Claude Code 自动拆解并逐步执行
- **双定位策略** — 优先使用 `uiautomator` 元素树精确定位，元素树不可用时自动切换 VLM 视觉定位
- **多推理后端** — 支持云端 API（DashScope 等）、Ollama 原生 API（支持思考模式开关）
- **异常检测与恢复** — 自动检测应用崩溃/ANR，归档日志和截图，支持弹窗自动处理

## 快速开始

### 前置条件

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Android 设备通过 USB 连接，已开启 USB 调试
- ADB（macOS: `brew install android-platform-tools`）
- Python 3.10+、Pillow、requests

### 安装

```bash
# 克隆到 Claude Code 可访问的目录
git clone https://github.com/yourname/ACrab.git

# 安装 Python 依赖
pip install Pillow requests openai
```

### 配置

编辑 `config.properties`，选择后端并填写对应配置：

```properties
# 后端选择: api / ollama
backend=ollama

# --- [api] 云端 API ---
api_model=qwen-vl-max
api_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
api_key_env=DASHSCOPE_API_KEY

# --- [ollama] Ollama 原生 API ---
ollama_model=qwen3.5:27b
ollama_base_url=http://192.168.1.100:11434
# 思考模式开关（关闭可大幅加速推理）
ollama_thinking=false
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
| `config.properties` | 运行时配置（后端、模型、调试开关等） |
| `keyboardservice-debug.apk` | ADBKeyBoard，用于可靠的中文/长文本输入 |

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

### Ollama 后端

使用 Ollama 原生 API，支持通过 `think` 参数控制思考模式：

```bash
# config.properties:
# backend=ollama
# ollama_base_url=http://192.168.1.100:11434
# ollama_model=qwen3.5:27b
# ollama_thinking=false   # 关闭思考模式，大幅加速推理
```

## 工作流程

```
用户下达任务
    |
环境自检（ADB / 设备 / 键盘 / VLM）
    |
任务分解为子目标
    |
+-> 截图 + Read 看图 + uiautomator dump
|       |
|   决策 + 声明操作意图
|       |
|   定位（元素树优先，不可用时 VLM 视觉定位）
|       |
|   执行 ADB 操作
|       |
|   判断结果（成功/走错/无效）
+-------+
```

## 致谢

- [MobileAgent](https://github.com/x-plug/mobileagent) — 视觉定位与多步骤移动端自动化的设计思路
- [ADBKeyBoard](https://github.com/senzhk/ADBKeyBoard) — 通过 ADB broadcast 输入中文及特殊字符

## License

[Apache License 2.0](LICENSE)
