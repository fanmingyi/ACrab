#!/usr/bin/env python3
"""
preprocess_image.py - 图片预处理工具

功能：
1. 图片尺寸检查与自动压缩（宽高超过 1200px 时按比例缩小）
2. 格式转换（PNG → JPG，保留高质量）
3. 坐标缩放因子计算（用于后续的坐标映射）

Usage:
    python preprocess_image.py <image_path> [--screen-size WxH]

Returns (stdout):
    JSON object: {
        "original": {"width": int, "height": int},
        "processed": {"width": int, "height": int},
        "processed_path": str,
        "scale_factor": float,  # 原始图片缩放到处理图片的比例，用于坐标反向映射
        "compressed": bool      # 是否进行了压缩
    }

Example:
    python preprocess_image.py /tmp/screenshot.png
    # => {
    #   "original": {"width": 2160, "height": 3840},
    #   "processed": {"width": 675, "height": 1200},
    #   "processed_path": "/tmp/screenshot_processed.jpg",
    #   "scale_factor": 3.2,
    #   "compressed": true
    # }
"""

import argparse
import json
import os
import sys
from PIL import Image

# 最大允许的单边尺寸（像素）
MAX_DIMENSION = 1200

# JPG 质量参数
JPG_QUALITY = 95


def preprocess_image(image_path, screen_width=None, screen_height=None):
    """
    图片预处理：检查尺寸，必要时压缩，转换格式。

    Args:
        image_path: 输入图片路径
        screen_width: 屏幕实际宽度（可选，用于日志）
        screen_height: 屏幕实际高度（可选，用于日志）

    Returns:
        dict: {
            "original": {"width": int, "height": int},
            "processed": {"width": int, "height": int},
            "processed_path": str,
            "scale_factor": float,
            "compressed": bool
        }

    Raises:
        FileNotFoundError: 如果输入文件不存在
        IOError: 如果无法读取或保存图片
    """
    # 检查文件存在性
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    # 打开图片
    try:
        img = Image.open(image_path)
    except Exception as e:
        raise IOError(f"无法打开图片: {e}")

    # 转换为 RGB（去掉 Alpha 通道）
    if img.mode == "RGBA":
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    orig_w, orig_h = img.size
    max_dim = max(orig_w, orig_h)

    # 判断是否需要压缩
    compressed = False
    scale_factor = 1.0
    img_processed = img

    if max_dim > MAX_DIMENSION:
        # 按比例压缩
        scale_factor = max_dim / MAX_DIMENSION
        new_w = max(1, int(orig_w / scale_factor))
        new_h = max(1, int(orig_h / scale_factor))

        try:
            img_processed = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            compressed = True
        except Exception as e:
            raise IOError(f"图片缩放失败: {e}")

    # 确定输出路径（转换为 JPG）
    base, ext = os.path.splitext(image_path)
    if ext.lower() in ['.png', '.jpeg', '.jpg', '.bmp', '.gif', '.webp']:
        processed_path = f"{base}_processed.jpg"
    else:
        processed_path = f"{image_path}_processed.jpg"

    # 保存为 JPG
    try:
        img_processed.save(processed_path, "JPEG", quality=JPG_QUALITY)
    except Exception as e:
        raise IOError(f"无法保存处理后的图片: {e}")

    processed_w, processed_h = img_processed.size

    return {
        "original": {"width": orig_w, "height": orig_h},
        "processed": {"width": processed_w, "height": processed_h},
        "processed_path": processed_path,
        "scale_factor": scale_factor,
        "compressed": compressed,
    }


def main():
    parser = argparse.ArgumentParser(description="图片预处理工具 - 自动压缩和格式转换")
    parser.add_argument("image_path", help="输入图片路径")
    parser.add_argument(
        "--screen-size",
        type=str,
        default=None,
        help="屏幕分辨率 WxH（仅用于日志记录，不影响处理逻辑）",
    )
    args = parser.parse_args()

    try:
        result = preprocess_image(args.image_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (FileNotFoundError, IOError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"未预期的错误: {e}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
