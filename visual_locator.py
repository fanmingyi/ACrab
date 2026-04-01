#!/usr/bin/env python3
"""
visual_locator.py - CLI tool for visually locating UI elements in screenshots.

Usage:
    python visual_locator.py <image_path> <element_description> [--debug] [--model MODEL]
    python visual_locator.py --selfcheck

Output (stdout):
    JSON object with keys: x1, y1, x2, y2, center ([cx, cy])
    Exit code 0 on success, 1 on failure.

Example:
    python visual_locator.py /tmp/mobile_screenshot.png "灰色的按钮包含'下一步'文字，在屏幕下方"
    # => {"x1": 120, "y1": 340, "x2": 280, "y2": 400, "center": [200, 370]}

    # 环境自检（加载模型 + 测试推理）
    python visual_locator.py --selfcheck
"""

import argparse
import base64
import json
import os
import re
import sys
from PIL import Image

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_config_properties():
    """读取 config.properties，返回 key-value dict。文件不存在则返回空 dict。"""
    cfg_path = os.path.join(_SKILL_DIR, "config.properties")
    props = {}
    if not os.path.exists(cfg_path):
        return props
    with open(cfg_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    return props


def _resolve_model(props, backend=None, model_override=None):
    """根据 backend 从配置中读取对应的模型名。model_override 优先。"""
    if model_override:
        return model_override
    b = (backend or props.get("backend", "ollama")).lower()
    if b == "ollama":
        return props.get("ollama_model", props.get("openai_compat_model", "qwen3.5:9b"))
    if b == "api":
        return props.get("api_model", "qwen-vl-max")
    return props.get("ollama_model", "qwen3.5:9b")


def parse_bboxes(output_text: str):
    """解析模型输出中的所有 bbox 对象，支持数组和单对象"""
    # 移除 Qwen3 的 <think>...</think> 思考过程
    output_text = re.sub(r"<think>.*?</think>", "", output_text, flags=re.DOTALL)
    output_text = re.sub(r'```(?:json)?\s*', '', output_text).strip()
    output_text = output_text.replace('```', '')

    try:
        data = json.loads(output_text)
    except json.JSONDecodeError:
        obj_match = re.search(r'\{[^{}]*"bbox_2d"[^{}]*\}', output_text, re.DOTALL)
        if obj_match:
            try:
                data = json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                return []
        else:
            return []

    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                return v
        return [data]
    elif isinstance(data, list):
        return data
    return [data]


def _save_debug_image(img, output_text, save_path):
    """在图像上绘制 bbox 并保存到 save_path，用于调试验证定位结果。
    坐标统一使用 0-1000 归一化格式。
    """
    from PIL import ImageDraw, ImageColor

    additional_colors = [name for name in ImageColor.colormap]
    colors = [
        'red', 'green', 'blue', 'yellow', 'orange', 'pink', 'purple', 'brown',
        'gray', 'beige', 'turquoise', 'cyan', 'magenta', 'lime', 'navy',
        'maroon', 'teal', 'olive', 'coral', 'lavender', 'violet', 'gold', 'silver',
    ] + additional_colors

    items = parse_bboxes(output_text)
    if not items:
        return

    debug_img = img.copy()
    draw = ImageDraw.Draw(debug_img)
    width, height = debug_img.size

    for i, item in enumerate(items):
        color = colors[i % len(colors)]
        bbox = item.get("bbox_2d") or item.get("bbox")
        if bbox is None:
            continue

        if len(bbox) == 2:
            cx = int(bbox[0] / 1000.0 * width)
            cy = int(bbox[1] / 1000.0 * height)
            r = 15
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=3)
        elif len(bbox) == 4:
            abs_x1 = int(bbox[0] / 1000.0 * width)
            abs_y1 = int(bbox[1] / 1000.0 * height)
            abs_x2 = int(bbox[2] / 1000.0 * width)
            abs_y2 = int(bbox[3] / 1000.0 * height)
            if abs_x1 > abs_x2:
                abs_x1, abs_x2 = abs_x2, abs_x1
            if abs_y1 > abs_y2:
                abs_y1, abs_y2 = abs_y2, abs_y1
            draw.rectangle(((abs_x1, abs_y1), (abs_x2, abs_y2)), outline=color, width=3)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    debug_img.save(save_path)


# ---------------------------------------------------------------------------
# Shared helper for OpenAI-compatible backends (api / openai_compat)
# ---------------------------------------------------------------------------

def _encode_image_base64(image_path: str) -> str:
    """将图片编码为 base64 data URL。"""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64,{img_b64}"


def _infer_openai_compat(image_path: str, prompt: str, *,
                          api_key: str, base_url: str, model_name: str,
                          system_prompt: str = "You are a helpful assistant.",
                          temperature: float = 0.0, max_tokens: int = 256,
                          image_extra: dict | None = None) -> str:
    """通过 OpenAI 兼容 API 推理（仅用于云端 api 后端），返回模型原始输出文本。"""
    from openai import OpenAI

    data_url = _encode_image_base64(image_path)

    image_content = {"type": "image_url", "image_url": {"url": data_url}}
    if image_extra:
        image_content.update(image_extra)

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
    messages = [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
        {"role": "user", "content": [image_content, {"type": "text", "text": prompt}]},
    ]

    completion = client.chat.completions.create(
        model=model_name, messages=messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    return completion.choices[0].message.content


# ---------------------------------------------------------------------------
# Backend: api (OpenAI-compatible, e.g. DashScope)
# ---------------------------------------------------------------------------

def _infer_api(image_path: str, prompt: str, props=None):
    """通过云端 API 推理（DashScope 等 OpenAI 兼容接口）。"""
    props = props or _load_config_properties()
    model_name = _resolve_model(props, backend="api")

    api_key_env = props.get("api_key_env", "DASHSCOPE_API_KEY")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"环境变量 {api_key_env} 未设置，无法调用 API")

    return _infer_openai_compat(
        image_path, prompt,
        api_key=api_key,
        base_url=props.get("api_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model_name=model_name,
    )


# ---------------------------------------------------------------------------
# Backend: ollama (Ollama 原生 API，支持 think 参数控制思考模式)
# ---------------------------------------------------------------------------

def _infer_ollama(image_path: str, prompt: str, *,
                  base_url: str, model_name: str,
                  system_prompt: str = "You are a helpful assistant.",
                  temperature: float = 0.0, think: bool = False) -> str:
    """通过 Ollama 原生 /api/chat 接口推理，返回模型输出文本。"""
    import requests as _requests

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Ollama 原生 API 格式：base_url 去掉 /v1 后缀
    api_url = base_url.rstrip("/")
    if api_url.endswith("/v1"):
        api_url = api_url[:-3]
    api_url = api_url.rstrip("/") + "/api/chat"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt, "images": [img_b64]},
        ],
        "stream": False,
        "think": think,
        "options": {"temperature": temperature},
    }

    resp = _requests.post(api_url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _infer_ollama_backend(image_path: str, prompt: str, props=None):
    """通过 Ollama 原生 API 推理。"""
    props = props or _load_config_properties()
    model_name = _resolve_model(props, backend="ollama")
    thinking = props.get("ollama_thinking", "false").lower() == "true"

    enhanced_prompt = f"""{prompt}

【输出要求】
仅输出标准 JSON，不要包含 Markdown 或其他解释。示例格式：
{{
  "results": [
    {{"label": "按钮名称", "bbox_2d": [120, 340, 280, 420]}}
  ]
}}"""

    return _infer_ollama(
        image_path, enhanced_prompt,
        base_url=props.get("ollama_base_url", props.get("openai_compat_base_url", "http://localhost:11434")),
        model_name=model_name,
        system_prompt="You are a helpful visual grounding assistant.",
        temperature=0.1,
        think=thinking,
    )


# ---------------------------------------------------------------------------
# Unified find_element
# ---------------------------------------------------------------------------

def _preprocess_for_vlm(image_path: str) -> str:
    """压缩大图并转换为 JPG。返回处理后的图片路径。"""
    try:
        from preprocess_image import preprocess_image
        result = preprocess_image(image_path)
        path = result.get("processed_path")
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    return image_path


def find_element(image_path: str, element_description: str, debug=None, model_override=None,
                  screen_width=None, screen_height=None, backend_override=None):
    """Locate a UI element in a screenshot by description.

    Uses 0-1000 normalized coordinates. Supports api and ollama backends.

    Args:
        debug: True/False 覆盖 config.properties 中的 debug 设置，None 则读取配置
        model_override: 模型路径，覆盖 config.properties 中的 model 设置
        screen_width: 屏幕实际宽度（像素），用于坐标映射
        screen_height: 屏幕实际高度（像素），用于坐标映射
        backend_override: "api" 或 "ollama"，覆盖 config.properties 中的 backend 设置

    Returns dict with x1, y1, x2, y2, center on success, or None on failure.
    """
    props = _load_config_properties()

    if backend_override:
        props["backend"] = backend_override
    if model_override:
        props["_model_override"] = model_override

    backend = props.get("backend", "ollama").lower()

    # 选择推理后端
    if backend == "api":
        infer_fn = _infer_api
    else:
        infer_fn = _infer_ollama_backend

    # 步骤 1：图片预处理（压缩 + 格式转换）
    processed_path = _preprocess_for_vlm(image_path)
    img = Image.open(processed_path)
    if img.mode == "RGBA":
        img = img.convert("RGB")

    # 步骤 2：确定目标坐标系（屏幕分辨率 > 输入图片尺寸）
    if screen_width is None or screen_height is None:
        orig_img = Image.open(image_path)
        screen_width = screen_width or orig_img.size[0]
        screen_height = screen_height or orig_img.size[1]

    # 步骤 3：VLM 推理
    import time as _time
    prompt = f"识别图片中{element_description}，并以JSON格式输出其bbox_2d坐标及标签"
    t_start = _time.time()
    output_text = infer_fn(processed_path, prompt, props=props)
    t_elapsed = _time.time() - t_start
    print(f"[visual_locator] 推理耗时: {t_elapsed:.2f}s", file=sys.stderr)

    # debug: 打印模型原始输出
    enable_debug = debug if debug is not None else props.get("debug", "false").lower() == "true"
    if enable_debug:
        print(f"[visual_locator] model raw output: {output_text[:300]}", file=sys.stderr)

    # 调试模式：用原始图片绘制 debug 标注
    if enable_debug:
        debug_path = os.path.join(_SKILL_DIR, "tmp", "debug_visual_locator.png")
        try:
            orig_debug_img = Image.open(image_path)
            if orig_debug_img.mode == "RGBA":
                orig_debug_img = orig_debug_img.convert("RGB")
            _save_debug_image(orig_debug_img, output_text, debug_path)
        except Exception:
            pass

    items = parse_bboxes(output_text)
    if not items:
        return None

    item = items[0]
    bbox = item.get("bbox_2d") or item.get("bbox")
    if bbox is None:
        return None

    # 步骤 4：坐标映射 — 0-1000 归一化坐标 → 屏幕坐标
    scale_x, scale_y = screen_width / 1000.0, screen_height / 1000.0

    def _to_screen(bx, by):
        return (
            max(0, min(screen_width, int(bx * scale_x))),
            max(0, min(screen_height, int(by * scale_y))),
        )

    if len(bbox) == 2:
        cx, cy = _to_screen(bbox[0], bbox[1])
        return {"center": [cx, cy]}

    elif len(bbox) == 4:
        x1, y1 = _to_screen(bbox[0], bbox[1])
        x2, y2 = _to_screen(bbox[2], bbox[3])
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        return {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "center": [(x1 + x2) // 2, (y1 + y2) // 2],
        }

    return None


def selfcheck(skip_vlm_test=False):
    """环境自检：验证依赖安装和模型加载是否正常。

    Args:
        skip_vlm_test: True 时跳过 VLM 推理测试（仅检查依赖），加快启动速度
    """
    props = _load_config_properties()
    backend = props.get("backend", "ollama").lower()
    model_path = _resolve_model(props, backend=backend)

    # 读取配置中的 selfcheck_vlm 开关
    selfcheck_vlm_cfg = props.get("selfcheck_vlm", "true").lower() == "true"
    if skip_vlm_test:
        selfcheck_vlm_cfg = False

    print(f"[selfcheck] 后端: {backend}", file=sys.stderr)
    print(f"[selfcheck] 模型: {model_path}", file=sys.stderr)

    # 1. 检查基础依赖
    try:
        from PIL import Image  # noqa: F811
    except ImportError:
        print("[selfcheck] FAIL: Pillow 未安装，请运行: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    # 2. 检查后端依赖
    if backend == "ollama":
        import requests as _requests
        ollama_url = props.get("ollama_base_url", props.get("openai_compat_base_url", "http://localhost:11434"))
        ollama_url = ollama_url.rstrip("/")
        if ollama_url.endswith("/v1"):
            ollama_url = ollama_url[:-3].rstrip("/")
        print(f"[selfcheck] 检查 Ollama 服务: {ollama_url}", file=sys.stderr)
        try:
            resp = _requests.get(f"{ollama_url}/api/tags", timeout=10)
            resp.raise_for_status()
            model_names = [m["name"] for m in resp.json().get("models", [])]
            print(f"[selfcheck] OK: 服务正常，可用模型: {model_names}", file=sys.stderr)
        except Exception as e:
            print(f"[selfcheck] FAIL: 无法连接 Ollama {ollama_url}: {e}", file=sys.stderr)
            print("  请确认 Ollama 已启动", file=sys.stderr)
            sys.exit(1)

    elif backend == "api":
        try:
            import openai  # noqa: F401
        except ImportError:
            print("[selfcheck] FAIL: openai 未安装，请运行: pip install openai", file=sys.stderr)
            sys.exit(1)
        api_key_env = props.get("api_key_env", "DASHSCOPE_API_KEY")
        if not os.environ.get(api_key_env):
            print(f"[selfcheck] FAIL: 环境变量 {api_key_env} 未设置", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] OK: openai 库已安装，{api_key_env} 已设置", file=sys.stderr)

    else:
        print(f"[selfcheck] FAIL: 不支持的后端 '{backend}'，请使用 ollama 或 api", file=sys.stderr)
        sys.exit(1)

    # 3. 检查测试图片
    test_image = os.path.join(_SKILL_DIR, "ACrabTest.png")
    if not os.path.exists(test_image):
        print(f"[selfcheck] FAIL: 测试图片不存在: {test_image}", file=sys.stderr)
        sys.exit(1)

    # 4. VLM 推理测试（可跳过）
    if not selfcheck_vlm_cfg:
        print("[selfcheck] SKIP: VLM 推理测试已跳过（selfcheck_vlm=false 或 --skip-vlm-test）", file=sys.stderr)
        print(json.dumps({"selfcheck": "pass", "vlm_test": "skipped"}))
        sys.exit(0)

    print(f"[selfcheck] 运行推理测试（{backend}）...", file=sys.stderr)
    prompt = "屏幕中显示'Log in'文字的按钮，通常为蓝色或白色的圆角矩形按钮，位于登录页面中部或底部区域"
    try:
        result = find_element(test_image, prompt, debug=True)
    except Exception as e:
        print(f"[selfcheck] FAIL: 推理执行出错: {e}", file=sys.stderr)
        if backend == "ollama":
            print("  请检查 Ollama 服务地址和模型名称是否正确", file=sys.stderr)
        elif backend == "api":
            print("  请检查 API Key、Base URL 和模型名称是否正确", file=sys.stderr)
        sys.exit(1)

    if result is None:
        print("[selfcheck] WARN: 模型未找到目标元素，但推理流程正常", file=sys.stderr)
        print(json.dumps({"selfcheck": "pass", "result": None}))
    else:
        print("[selfcheck] OK: 定位成功", file=sys.stderr)
        print(json.dumps({"selfcheck": "pass", "result": result}))

    debug_path = os.path.join(_SKILL_DIR, "tmp", "debug_visual_locator.png")
    print(f"[selfcheck] 调试图已保存: {debug_path}", file=sys.stderr)
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="视觉定位工具 - 在截图中定位 UI 元素")
    parser.add_argument("image_path", nargs="?", help="截图文件路径")
    parser.add_argument("element_description", nargs="?", help="目标元素的详细描述")
    parser.add_argument("--debug", action="store_true", default=None, help="开启调试模式，保存标注 bbox 的图片")
    parser.add_argument("--no-debug", action="store_true", help="关闭调试模式")
    parser.add_argument("--model", type=str, default=None, help="指定模型路径（覆盖 config.properties）")
    parser.add_argument("--screen-size", type=str, default=None, help="屏幕实际分辨率 WxH（如 1080x2424），用于坐标映射")
    parser.add_argument("--backend", type=str, default=None, choices=["api", "ollama"],
                        help="指定后端（覆盖 config.properties）: api=云端API, ollama=Ollama原生API")
    parser.add_argument("--selfcheck", action="store_true", help="环境自检：验证依赖和模型是否正常")
    parser.add_argument("--skip-vlm-test", action="store_true", help="自检时跳过 VLM 推理测试")
    args = parser.parse_args()

    if args.selfcheck:
        selfcheck(skip_vlm_test=args.skip_vlm_test)
        return

    if not args.image_path or not args.element_description:
        parser.error("需要提供 image_path 和 element_description，或使用 --selfcheck")

    debug_flag = None
    if args.debug:
        debug_flag = True
    elif args.no_debug:
        debug_flag = False

    screen_w, screen_h = None, None
    if args.screen_size:
        parts = args.screen_size.lower().split('x')
        if len(parts) == 2:
            screen_w, screen_h = int(parts[0]), int(parts[1])

    result = find_element(args.image_path, args.element_description, debug=debug_flag,
                          model_override=args.model, screen_width=screen_w, screen_height=screen_h,
                          backend_override=args.backend)
    if result is None:
        print(json.dumps({"error": "Element not found"}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
