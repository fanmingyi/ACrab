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
import math
import os
import re
import subprocess
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


# --- 本地 mlx-vlm 参数 ---
FACTOR_LOCAL = 28                    # patch_size(14) × merge_size(2) = 28
MIN_PIXELS_LOCAL = 256 * 256         # 65536
MAX_PIXELS_LOCAL = 2560 * 28 * 28    # 2007040

# --- 网络 API (DashScope) 参数 ---
FACTOR_API = 32                      # factor = 32
MIN_PIXELS_API = 4 * 32 * 32         # 4096（参照官方示例）
MAX_PIXELS_API = 2560 * 32 * 32      # 2621440


def smart_resize_qwen2_5_vl(img, factor=FACTOR_LOCAL, min_pixels=MIN_PIXELS_LOCAL, max_pixels=MAX_PIXELS_LOCAL):
    """
    Qwen2.5-VL图像自适应缩放，返回模型内部的 resized 尺寸（仅用于坐标映射）。
    factor=28 与 processor 内部 patch_size=14 × merge_size=2 一致。
    """
    width, height = img.size
    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def get_output_text(output) -> str:
    if isinstance(output, str):
        return output
    for attr in ("text", "generation", "output", "result"):
        if hasattr(output, attr):
            return getattr(output, attr)
    return str(output)


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


def _save_debug_image(img, output_text, save_path, factor=FACTOR_LOCAL, min_pixels=MIN_PIXELS_LOCAL, max_pixels=MAX_PIXELS_LOCAL, coord_denominator=None):
    """在图像上绘制 bbox 并保存到 save_path，用于调试验证定位结果。
    coord_denominator: (denom_w, denom_h) 覆盖坐标除数，用于 0-1000 归一化坐标模式。
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

    if coord_denominator:
        denom_w, denom_h = coord_denominator
    else:
        resized_h, resized_w = smart_resize_qwen2_5_vl(debug_img, factor=factor, min_pixels=min_pixels, max_pixels=max_pixels)
        denom_w, denom_h = resized_w, resized_h

    for i, item in enumerate(items):
        color = colors[i % len(colors)]
        bbox = item.get("bbox_2d") or item.get("bbox")
        if bbox is None:
            continue

        if len(bbox) == 2:
            cx = int(bbox[0] / denom_w * width)
            cy = int(bbox[1] / denom_h * height)
            r = 15
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=3)
        elif len(bbox) == 4:
            abs_x1 = int(bbox[0] / denom_w * width)
            abs_y1 = int(bbox[1] / denom_h * height)
            abs_x2 = int(bbox[2] / denom_w * width)
            abs_y2 = int(bbox[3] / denom_h * height)
            if abs_x1 > abs_x2:
                abs_x1, abs_x2 = abs_x2, abs_x1
            if abs_y1 > abs_y2:
                abs_y1, abs_y2 = abs_y2, abs_y1
            draw.rectangle(((abs_x1, abs_y1), (abs_x2, abs_y2)), outline=color, width=3)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    debug_img.save(save_path)


# ---------------------------------------------------------------------------
# Backend: local (mlx-vlm)
# ---------------------------------------------------------------------------

_model = None
_processor = None
_config = None
_loaded_model_path = None


def _resolve_model(props, backend=None, model_override=None):
    """根据 backend 从配置中读取对应的模型名。model_override 优先。"""
    if model_override:
        return model_override
    b = (backend or props.get("backend", "local")).lower()
    if b == "vllm":
        return props.get("vllm_model", "Qwen/Qwen3-VL-8B-Instruct")
    if b == "api":
        return props.get("api_model", "qwen2.5-vl-7b-instruct")
    return props.get("local_model", "mlx-community/Qwen2.5-VL-7B-Instruct-bf16")


def _load_model(model_override=None):
    global _model, _processor, _config, _loaded_model_path
    props = _load_config_properties()
    model_path = _resolve_model(props, backend="local", model_override=model_override)
    if _model is None or _loaded_model_path != model_path:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config
        _model, _processor = load(model_path)
        _config = load_config(model_path)
        _loaded_model_path = model_path
    return _model, _processor, _config


def _infer_local(image_path: str, prompt: str, img: Image.Image, model_override=None):
    """本地 mlx-vlm 推理，返回模型原始输出文本。"""
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor, config = _load_model(model_override)

    processor.image_processor.min_pixels = MIN_PIXELS_LOCAL
    processor.image_processor.max_pixels = MAX_PIXELS_LOCAL

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are a helpful assistant."}],
        },
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": prompt},
            ],
        },
    ]

    formatted_prompt = apply_chat_template(
        processor, config, messages, num_images=1
    )

    raw_output = generate(
        model,
        processor,
        formatted_prompt,
        image=[image_path],
        max_tokens=256,
        temperature=0.0,
        verbose=False,
    )

    return get_output_text(raw_output)


# ---------------------------------------------------------------------------
# Shared helper for OpenAI-compatible backends (api / vllm)
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
    """通过 OpenAI 兼容 API 推理，返回模型原始输出文本。"""
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

def _infer_api(image_path: str, prompt: str, img: Image.Image, model_override=None):
    """通过云端 API 推理（DashScope 等 OpenAI 兼容接口）。"""
    props = _load_config_properties()
    model_name = _resolve_model(props, backend="api", model_override=model_override)

    api_key_env = props.get("api_key_env", "DASHSCOPE_API_KEY")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"环境变量 {api_key_env} 未设置，无法调用 API")

    return _infer_openai_compat(
        image_path, prompt,
        api_key=api_key,
        base_url=props.get("api_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model_name=model_name,
        image_extra={"min_pixels": MIN_PIXELS_API, "max_pixels": MAX_PIXELS_API},
    )


# ---------------------------------------------------------------------------
# Backend: vllm (局域网 vLLM 服务，如 Qwen3-VL，坐标为 0-1000 归一化)
# ---------------------------------------------------------------------------

def _infer_vllm(image_path: str, prompt: str, img: Image.Image, model_override=None):
    """通过局域网 vLLM 服务推理，坐标为 0-1000 归一化。"""
    props = _load_config_properties()
    model_name = _resolve_model(props, backend="vllm", model_override=model_override)

    enhanced_prompt = f"""{prompt}

【输出要求】
1. 仅输出标准 JSON，不要包含 Markdown 或其他解释
2. bbox 坐标使用 0~1000 归一化格式 [x1, y1, x2, y2]，其中 (0,0) 为左上角，(1000,1000) 为右下角
3. 示例格式：
{{
  "results": [
    {{"label": "按钮名称", "bbox_2d": [120, 340, 280, 420]}}
  ]
}}"""

    return _infer_openai_compat(
        image_path, enhanced_prompt,
        api_key="EMPTY",
        base_url=props.get("vllm_base_url", "http://localhost:8000/v1"),
        model_name=model_name,
        system_prompt="You are a helpful visual grounding assistant.",
        temperature=0.1,
        max_tokens=2048,
    )


# ---------------------------------------------------------------------------
# Backend: remote (宿主机 HTTP 服务，用于 Docker 容器内调用 Mac MLX 推理)
# ---------------------------------------------------------------------------

def _find_element_remote(image_path: str, element_description: str, debug=None,
                          screen_width=None, screen_height=None, **kwargs):
    """通过 HTTP 调用宿主机上的 visual_locator_server.py，返回定位结果。"""
    import urllib.request

    props = _load_config_properties()
    remote_url = props.get("remote_url", "http://host.docker.internal:8420")

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = json.dumps({
        "image_base64": img_b64,
        "description": element_description,
        "screen_width": screen_width,
        "screen_height": screen_height,
        "debug": debug if debug is not None else False,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{remote_url}/locate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 404:
            return None
        raise RuntimeError(f"Remote locator 返回 {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"无法连接 remote locator ({remote_url}): {e.reason}\n"
            "请确认宿主机已运行: python visual_locator_server.py"
        )


# ---------------------------------------------------------------------------
# Unified find_element
# ---------------------------------------------------------------------------

def _get_backend_params(props):
    """根据 backend 返回 (factor, min_pixels, max_pixels, infer_fn, coord_mode)。
    coord_mode: "resized" 表示坐标相对于模型内部 resized 尺寸，"normalized" 表示 0-1000 归一化。
    """
    backend = props.get("backend", "local").lower()
    if backend == "vllm":
        # vllm 后端：坐标为 0-1000 归一化，factor/pixels 参数仅用于调试图绘制
        return FACTOR_LOCAL, MIN_PIXELS_LOCAL, MAX_PIXELS_LOCAL, _infer_vllm, "normalized"
    if backend == "api":
        return FACTOR_API, MIN_PIXELS_API, MAX_PIXELS_API, _infer_api, "resized"
    return FACTOR_LOCAL, MIN_PIXELS_LOCAL, MAX_PIXELS_LOCAL, _infer_local, "resized"


def _preprocess_for_vlm(image_path: str) -> str:
    """调用外部预处理脚本，压缩大图并转换为 JPG。返回处理后的图片路径。"""
    preprocess_script = os.path.join(_SKILL_DIR, "preprocess_image.py")
    if not os.path.exists(preprocess_script):
        return image_path
    try:
        result = subprocess.run(
            [sys.executable, preprocess_script, image_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            path = data.get("processed_path")
            if path and os.path.exists(path):
                return path
    except Exception:
        pass
    return image_path


def find_element(image_path: str, element_description: str, debug=None, model_override=None,
                  screen_width=None, screen_height=None, backend_override=None):
    """Locate a UI element in a screenshot by description.

    Args:
        debug: True/False 覆盖 config.properties 中的 debug 设置，None 则读取配置
        model_override: 模型路径，覆盖 config.properties 中的 model 设置
        screen_width: 屏幕实际宽度（像素），用于坐标映射修正
        screen_height: 屏幕实际高度（像素），用于坐标映射修正
        backend_override: "local" 或 "api"，覆盖 config.properties 中的 backend 设置

    Returns dict with x1, y1, x2, y2, center on success, or None on failure.
    """
    props = _load_config_properties()

    if backend_override:
        props["backend"] = backend_override

    # remote 后端：直接委托给宿主机 HTTP 服务，跳过本地推理流程
    backend = props.get("backend", "local").lower()
    if backend == "remote":
        return _find_element_remote(
            image_path, element_description, debug=debug,
            screen_width=screen_width, screen_height=screen_height,
        )

    factor, min_pixels, max_pixels, infer_fn, coord_mode = _get_backend_params(props)

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
    resized_h, resized_w = smart_resize_qwen2_5_vl(img, factor=factor, min_pixels=min_pixels, max_pixels=max_pixels)
    prompt = f"识别图片中{element_description}，并以JSON格式输出其bbox_2d坐标及标签"
    output_text = infer_fn(processed_path, prompt, img, model_override=model_override)

    # 调试模式
    enable_debug = debug if debug is not None else props.get("debug", "false").lower() == "true"
    if enable_debug:
        debug_path = os.path.join(_SKILL_DIR, "tmp", "debug_visual_locator.png")
        try:
            denom = (1000, 1000) if coord_mode == "normalized" else None
            _save_debug_image(img, output_text, debug_path,
                              factor=factor, min_pixels=min_pixels, max_pixels=max_pixels,
                              coord_denominator=denom)
        except Exception:
            pass

    items = parse_bboxes(output_text)
    if not items:
        return None

    item = items[0]
    bbox = item.get("bbox_2d") or item.get("bbox")
    if bbox is None:
        return None

    # 步骤 4：坐标映射 — VLM 坐标直接映射到屏幕坐标
    # 数学原理：VLM coord / denom * processed_dim * (screen_dim / processed_dim) = VLM coord / denom * screen_dim
    # 中间的 processed_dim 相互抵消，因此可以跳过中间步骤直接映射到屏幕
    if coord_mode == "normalized":
        scale_x, scale_y = screen_width / 1000.0, screen_height / 1000.0
    else:
        scale_x, scale_y = screen_width / float(resized_w), screen_height / float(resized_h)

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
    backend = props.get("backend", "local").lower()
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
    if backend == "remote":
        import urllib.request
        remote_url = props.get("remote_url", "http://host.docker.internal:8420")
        print(f"[selfcheck] 检查远程服务: {remote_url}/health", file=sys.stderr)
        try:
            req = urllib.request.Request(f"{remote_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                health = json.loads(resp.read().decode("utf-8"))
                print(f"[selfcheck] OK: 远程服务正常，模型: {health.get('model', 'unknown')}", file=sys.stderr)
        except Exception as e:
            print(f"[selfcheck] FAIL: 无法连接远程服务 {remote_url}: {e}", file=sys.stderr)
            print("  请在宿主机 Mac 上运行: python visual_locator_server.py", file=sys.stderr)
            sys.exit(1)

    elif backend == "vllm":
        try:
            import openai  # noqa: F401
        except ImportError:
            print("[selfcheck] FAIL: openai 未安装，请运行: pip install openai", file=sys.stderr)
            sys.exit(1)

        vllm_base_url = props.get("vllm_base_url", "http://localhost:8000/v1")
        print(f"[selfcheck] 检查 vLLM 服务: {vllm_base_url}", file=sys.stderr)
        try:
            from openai import OpenAI
            client = OpenAI(api_key="EMPTY", base_url=vllm_base_url)
            models = client.models.list()
            model_ids = [m.id for m in models.data]
            print(f"[selfcheck] OK: vLLM 服务正常，可用模型: {model_ids}", file=sys.stderr)
        except Exception as e:
            print(f"[selfcheck] FAIL: 无法连接 vLLM 服务 {vllm_base_url}: {e}", file=sys.stderr)
            print("  请确认局域网 vLLM 服务已启动", file=sys.stderr)
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
        try:
            import mlx_vlm  # noqa: F401
        except ImportError:
            print("[selfcheck] FAIL: mlx-vlm 未安装", file=sys.stderr)
            print("  请参照 https://github.com/Blaizzy/mlx-vlm 安装:", file=sys.stderr)
            print("  pip install mlx-vlm", file=sys.stderr)
            print(f"  然后下载模型: python -m mlx_vlm.generate --model {model_path} --prompt test", file=sys.stderr)
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

    if backend == "local":
        print("[selfcheck] 加载本地模型...", file=sys.stderr)
        try:
            _load_model(model_path)
        except Exception as e:
            print(f"[selfcheck] FAIL: 模型加载失败: {e}", file=sys.stderr)
            print(f"  请确认模型已下载: python -m mlx_vlm.generate --model {model_path} --prompt test", file=sys.stderr)
            sys.exit(1)

    print(f"[selfcheck] 运行推理测试（{backend}）...", file=sys.stderr)
    prompt = "屏幕中显示'Log in'文字的按钮，通常为蓝色或白色的圆角矩形按钮，位于登录页面中部或底部区域"
    try:
        result = find_element(test_image, prompt, debug=True, model_override=model_path)
    except Exception as e:
        print(f"[selfcheck] FAIL: 推理执行出错: {e}", file=sys.stderr)
        if backend == "vllm":
            print("  请检查 vLLM 服务地址和模型名称是否正确", file=sys.stderr)
        elif backend == "api":
            print("  请检查 API Key、Base URL 和模型名称是否正确", file=sys.stderr)
        else:
            print("  请确认 mlx-vlm 和模型安装正确:", file=sys.stderr)
            print("  pip install mlx-vlm", file=sys.stderr)
            print("  参照: https://github.com/Blaizzy/mlx-vlm", file=sys.stderr)
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
    parser.add_argument("--screen-size", type=str, default=None, help="屏幕实际分辨率 WxH（如 1080x2424），用于修正坐标映射偏差")
    parser.add_argument("--backend", type=str, default=None, choices=["local", "api", "vllm", "remote"],
                        help="指定后端（覆盖 config.properties）: local=MLX本地, api=网络API, vllm=局域网vLLM, remote=宿主机HTTP服务")
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
