#!/bin/bash
# 截图脚本：从 Android 设备截图→自动预处理→保存
#
# 用法: ./screenshot.sh <设备序列号> [文件名]
# 示例: ./screenshot.sh 9A131FFAZ00095
#       ./screenshot.sh 9A131FFAZ00095 my_screenshot.png
#
# 输出：处理后的图片路径（stdout）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_DIR="$SCRIPT_DIR/tmp"
PREPROCESS_SCRIPT="$SCRIPT_DIR/preprocess_image.py"

# 参数处理
DEVICE="${1:?用法: $0 <设备序列号> [文件名]}"
FILENAME="${2:-mobile_screenshot.png}"

RAW="$TMP_DIR/${FILENAME%.*}_raw.png"
FINAL="$TMP_DIR/$FILENAME"
OUTPUT_DIR="$(dirname "$FINAL")"

# 确保输出目录存在
mkdir -p "$OUTPUT_DIR"

# 步骤 1: 从设备截图
adb -s "$DEVICE" exec-out screencap -p > "$RAW"

if [ $? -ne 0 ] || [ ! -s "$RAW" ]; then
    echo "截图失败" >&2
    rm -f "$RAW"
    exit 1
fi

# 步骤 2: 自动预处理（压缩 + 格式转换），用 python3 安全解析 JSON
if [ -f "$PREPROCESS_SCRIPT" ]; then
    PROCESSED=$(python3 "$PREPROCESS_SCRIPT" "$RAW" 2>/dev/null \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['processed_path'])" 2>/dev/null)
    if [ -n "$PROCESSED" ] && [ -f "$PROCESSED" ]; then
        mv "$PROCESSED" "$FINAL"
    else
        mv "$RAW" "$FINAL"
    fi
else
    mv "$RAW" "$FINAL"
fi

# 清理原始文件
rm -f "$RAW"

# 输出最终图片路径
echo "$FINAL"
