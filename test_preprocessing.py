#!/usr/bin/env python3
"""
test_preprocessing.py - 图片预处理测试脚本

用于验证图片预处理和坐标映射的正确性。

Usage:
    python test_preprocessing.py [--create-dummy-image]
"""

import json
import os
import sys
import subprocess
from pathlib import Path

# 获取 SKILL 目录
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PREPROCESS_SCRIPT = os.path.join(SKILL_DIR, "preprocess_image.py")
VISUAL_LOCATOR_SCRIPT = os.path.join(SKILL_DIR, "visual_locator.py")


def create_dummy_large_image(output_path):
    """创建一个大的虚拟图片用于测试（2160×3840，模拟 Pixel 6 截图）"""
    from PIL import Image, ImageDraw

    width, height = 2160, 3840
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 绘制一些图形用于视觉验证
    # 蓝色按钮（中心位置）
    btn_x1, btn_y1 = 800, 1800
    btn_x2, btn_y2 = 1360, 2000
    draw.rectangle(((btn_x1, btn_y1), (btn_x2, btn_y2)), fill=(0, 100, 200))
    draw.text((900, 1880), "Login", fill=(255, 255, 255))

    # 绿色输入框
    input_x1, input_y1 = 600, 1400
    input_x2, input_y2 = 1560, 1600
    draw.rectangle(((input_x1, input_y1), (input_x2, input_y2)), outline=(0, 200, 0), width=5)

    img.save(output_path, "PNG")
    print(f"✅ 创建虚拟图片: {output_path} ({width}×{height})")
    return output_path


def test_preprocess_image(image_path):
    """测试图片预处理"""
    print("\n" + "=" * 70)
    print("测试 1: 图片预处理")
    print("=" * 70)

    if not os.path.exists(PREPROCESS_SCRIPT):
        print("❌ preprocess_image.py 不存在")
        return None

    try:
        result = subprocess.run(
            [sys.executable, PREPROCESS_SCRIPT, image_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            print(f"❌ 预处理失败: {result.stderr}")
            return None

        data = json.loads(result.stdout)
        print(f"✅ 预处理成功")
        print(f"   原始尺寸: {data['original']['width']}×{data['original']['height']}")
        print(f"   处理后尺寸: {data['processed']['width']}×{data['processed']['height']}")
        print(f"   缩放因子: {data['scale_factor']:.2f}")
        print(f"   压缩: {'是' if data['compressed'] else '否'}")
        print(f"   处理后文件: {data['processed_path']}")

        # 验证缩放因子计算
        max_orig = max(data['original']['width'], data['original']['height'])
        max_proc = max(data['processed']['width'], data['processed']['height'])
        expected_scale = max_orig / max_proc if max_proc > 0 else 1.0
        actual_scale = data['scale_factor']

        if abs(actual_scale - expected_scale) < 0.01:
            print(f"   ✅ 缩放因子验证通过 ({actual_scale:.2f} ≈ {expected_scale:.2f})")
        else:
            print(f"   ❌ 缩放因子不符: {actual_scale:.2f} != {expected_scale:.2f}")

        return data

    except Exception as e:
        print(f"❌ 预处理异常: {e}")
        return None


def test_coordinate_mapping(preprocess_data):
    """测试坐标映射逻辑"""
    print("\n" + "=" * 70)
    print("测试 2: 坐标映射")
    print("=" * 70)

    if not preprocess_data:
        print("❌ 缺少预处理数据，跳过")
        return

    scale_factor = preprocess_data['scale_factor']
    orig_w = preprocess_data['original']['width']
    orig_h = preprocess_data['original']['height']
    proc_w = preprocess_data['processed']['width']
    proc_h = preprocess_data['processed']['height']

    # 模拟坐标映射
    print(f"\n场景: 原始图片 {orig_w}×{orig_h} → 处理 {proc_w}×{proc_h}, scale_factor={scale_factor:.2f}")

    # 假设模型在处理后的图片上检测到按钮 bbox
    model_bbox = [100, 150, 250, 350]  # [x1, y1, x2, y2]

    # 模型坐标（相对于处理后的图片）→ 处理后的图片坐标
    proc_x1, proc_y1, proc_x2, proc_y2 = model_bbox
    print(f"\n1️⃣ 模型输出 (处理后图片坐标): {model_bbox}")

    # 处理后的图片坐标 → 原始图片坐标
    orig_x1 = int(proc_x1 * scale_factor)
    orig_y1 = int(proc_y1 * scale_factor)
    orig_x2 = int(proc_x2 * scale_factor)
    orig_y2 = int(proc_y2 * scale_factor)

    print(f"2️⃣ 映射到原始图片坐标: [{orig_x1}, {orig_y1}, {orig_x2}, {orig_y2}]")

    # 计算中心点
    center_x = (orig_x1 + orig_x2) // 2
    center_y = (orig_y1 + orig_y2) // 2
    print(f"3️⃣ 中心点坐标: ({center_x}, {center_y})")

    # 验证坐标在屏幕范围内
    if 0 <= center_x <= orig_w and 0 <= center_y <= orig_h:
        print(f"✅ 坐标在屏幕范围内")
    else:
        print(f"❌ 坐标超出范围: ({center_x}, {center_y})")

    return {
        "model_bbox": model_bbox,
        "original_bbox": [orig_x1, orig_y1, orig_x2, orig_y2],
        "center": [center_x, center_y],
    }


def test_coordinate_accuracy(preprocess_data):
    """测试坐标映射精度"""
    print("\n" + "=" * 70)
    print("测试 3: 坐标精度验证")
    print("=" * 70)

    if not preprocess_data or preprocess_data['scale_factor'] == 1.0:
        print("⏭️ 图片未压缩，跳过精度测试")
        return

    scale_factor = preprocess_data['scale_factor']
    orig_w = preprocess_data['original']['width']
    orig_h = preprocess_data['original']['height']
    proc_w = preprocess_data['processed']['width']
    proc_h = preprocess_data['processed']['height']

    # 多个测试用例
    test_cases = [
        {
            "name": "屏幕中心",
            "processed_coords": [proc_w // 2, proc_h // 2],
            "expected_original": [orig_w // 2, orig_h // 2],
        },
        {
            "name": "左上角",
            "processed_coords": [0, 0],
            "expected_original": [0, 0],
        },
        {
            "name": "右下角",
            "processed_coords": [proc_w - 1, proc_h - 1],
            "expected_original": [orig_w - 1, orig_h - 1],
        },
    ]

    print(f"\n缩放因子: {scale_factor:.2f}")
    all_pass = True

    for test in test_cases:
        proc_x, proc_y = test["processed_coords"]
        orig_x = int(proc_x * scale_factor)
        orig_y = int(proc_y * scale_factor)
        expected_x, expected_y = test["expected_original"]

        # 允许 ±1 像素的误差
        x_ok = abs(orig_x - expected_x) <= 1
        y_ok = abs(orig_y - expected_y) <= 1
        status = "✅" if (x_ok and y_ok) else "❌"

        print(f"\n{status} {test['name']}")
        print(f"   处理后: ({proc_x}, {proc_y})")
        print(f"   映射后: ({orig_x}, {orig_y})")
        print(f"   预期: ({expected_x}, {expected_y})")

        if not (x_ok and y_ok):
            all_pass = False

    if all_pass:
        print("\n✅ 所有精度测试通过")
    else:
        print("\n❌ 部分精度测试失败")

    return all_pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="图片预处理测试脚本")
    parser.add_argument("--create-dummy-image", action="store_true", help="创建虚拟测试图片")
    parser.add_argument("--image", type=str, help="指定测试图片路径")
    args = parser.parse_args()

    test_image = args.image
    if not test_image:
        test_image = os.path.join(SKILL_DIR, "test_large_image.png")

    # 如果需要创建虚拟图片
    if args.create_dummy_image or (not os.path.exists(test_image) and args.create_dummy_image is not False):
        try:
            create_dummy_large_image(test_image)
        except Exception as e:
            print(f"❌ 无法创建虚拟图片: {e}")
            print("   请手动指定: python test_preprocessing.py --image <path>")
            return

    if not os.path.exists(test_image):
        print(f"❌ 测试图片不存在: {test_image}")
        print(f"   创建虚拟图片: python test_preprocessing.py --create-dummy-image")
        return

    print(f"🧪 开始测试...")
    print(f"   测试图片: {test_image}")
    print(f"   SKILL 目录: {SKILL_DIR}")

    # 执行测试
    preprocess_data = test_preprocess_image(test_image)
    mapping_result = test_coordinate_mapping(preprocess_data)
    accuracy_ok = test_coordinate_accuracy(preprocess_data)

    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)

    if preprocess_data and mapping_result and accuracy_ok:
        print("✅ 所有测试通过！")
        print("\n优化效果:")
        if preprocess_data['compressed']:
            compression_ratio = (
                preprocess_data['original']['width'] * preprocess_data['original']['height']
                / (preprocess_data['processed']['width'] * preprocess_data['processed']['height'])
            )
            print(f"  • 图片尺寸压缩: {compression_ratio:.1f}x")
            print(f"  • Token 消耗减少: ~{(1 - 1/compression_ratio)*100:.0f}%")
            print(f"  • 坐标映射: 精确无损")
    else:
        print("❌ 部分测试失败，请检查日志")


if __name__ == "__main__":
    main()
