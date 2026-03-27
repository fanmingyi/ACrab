#!/bin/bash
# 获取屏幕 UI 元素树，输出为易读的文本格式
#
# 用法:
#   ./dump_ui.sh <设备序列号>               # 输出所有有标识的元素
#   ./dump_ui.sh <设备序列号> <关键词>       # 按关键词过滤（大小写不敏感）
#   ./dump_ui.sh <设备序列号> --clickable    # 只显示可点击元素
#   ./dump_ui.sh <设备序列号> --all          # 显示所有元素（含无标识的）
#
# 输出格式（每行一个元素）:
#   [x1,y1][x2,y2] click=true|false text="..." desc="..." id="..."
#
# 配合 grep 使用:
#   ./dump_ui.sh DEV | grep -i "搜索"
#   ./dump_ui.sh DEV | grep "click=true"

DEVICE="${1:?用法: $0 <设备序列号> [关键词|--clickable|--all]}"
FILTER="${2:-}"

# 获取 UI 元素树（XML）
XML=$(adb -s "$DEVICE" exec-out uiautomator dump /dev/tty 2>/dev/null)

if [ -z "$XML" ]; then
    echo "ERROR: uiautomator dump 失败" >&2
    exit 1
fi

# 用 Python 解析 XML（比 sed 循环快 5-10x）
# 通过环境变量传递 FILTER，避免 shell 变量注入 Python 代码的风险
DUMP_FILTER="$FILTER" python3 -c "
import xml.etree.ElementTree as ET, sys, os

xml_str = sys.stdin.read()
# 提取 XML 部分（dump 输出可能有前缀文本）
for marker in ['<?xml', '<hierarchy']:
    idx = xml_str.find(marker)
    if idx >= 0:
        xml_str = xml_str[idx:]
        break
else:
    print('ERROR: 无法解析 XML', file=sys.stderr)
    sys.exit(1)

# 去掉 XML 声明后可能的尾部垃圾
end = xml_str.rfind('>')
if end >= 0:
    xml_str = xml_str[:end+1]

filt = os.environ.get('DUMP_FILTER', '')
root = ET.fromstring(xml_str)
for node in root.iter('node'):
    bounds = node.get('bounds', '')
    if not bounds:
        continue
    text = node.get('text', '')
    desc = node.get('content-desc', '')
    rid = node.get('resource-id', '')
    rid_short = rid.split('/')[-1] if rid else ''
    clickable = node.get('clickable', 'false')

    # 默认跳过无标识节点
    if filt != '--all' and not text and not desc and not rid_short:
        continue
    # --clickable 只显示可点击
    if filt == '--clickable' and clickable != 'true':
        continue

    line = f'{bounds} click={clickable}'
    if text:
        line += f' text=\"{text}\"'
    if desc:
        line += f' desc=\"{desc}\"'
    if rid_short:
        line += f' id=\"{rid_short}\"'

    # 关键词过滤
    if filt and filt not in ('--clickable', '--all'):
        if filt.lower() in line.lower():
            print(line)
    else:
        print(line)
" <<< "$XML"
