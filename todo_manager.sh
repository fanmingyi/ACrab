#!/usr/bin/env bash
# todo_manager.sh - ACrab 任务 TODO 管理器
# 用法:
#   todo_manager.sh init "任务名"    — 生成 TODO 文件，预填自检+清理步骤
#   todo_manager.sh check <编号>     — 勾选指定步骤
#   todo_manager.sh add "步骤描述"   — 在「执行步骤」区添加新步骤
#   todo_manager.sh list             — 显示当前 TODO 状态

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_TMP="$SKILL_DIR/tmp"
TODO_CURRENT="$SKILL_TMP/.todo_current"

_todo_file() {
    if [ -f "$TODO_CURRENT" ]; then
        cat "$TODO_CURRENT"
    else
        echo ""
    fi
}

cmd_init() {
    local task_name="${1:-未命名任务}"
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    local todo_file="$SKILL_TMP/todo_${ts}.md"

    mkdir -p "$SKILL_TMP"
    cat > "$todo_file" <<EOF
# TODO: ${task_name}
> 创建时间: $(date '+%Y-%m-%d %H:%M:%S')

## 自检
- [ ] 1. ADB 连接检查
- [ ] 2. 屏幕分辨率获取
- [ ] 3. ADBKeyBoard 检查
- [ ] 4. 键盘启用
- [ ] 5. VLM 自检
- [ ] 6. Logcat 启动

## 执行步骤

## 清理
- [ ] C1. 停止 logcat
- [ ] C2. 关闭目标应用
- [ ] C3. 输出结论报告
EOF

    # 记录当前活跃的 TODO 文件路径
    echo "$todo_file" > "$TODO_CURRENT"
    echo "✅ TODO 已创建: $todo_file"
}

cmd_check() {
    local id="$1"
    local todo_file
    todo_file=$(_todo_file)
    if [ -z "$todo_file" ] || [ ! -f "$todo_file" ]; then
        echo "❌ 没有活跃的 TODO 文件，请先执行 init" >&2
        exit 1
    fi

    # 匹配 "- [ ] {id}." 或 "- [ ] {id}. " 并替换为 "- [x]"
    if grep -q "\- \[ \] ${id}\." "$todo_file"; then
        sed -i '' "s/- \[ \] ${id}\./- [x] ${id}./" "$todo_file"
        echo "✅ 已勾选: ${id}"
    else
        echo "⚠️ 未找到编号 ${id} 的未完成项" >&2
    fi
}

cmd_add() {
    local desc="$1"
    local todo_file
    todo_file=$(_todo_file)
    if [ -z "$todo_file" ] || [ ! -f "$todo_file" ]; then
        echo "❌ 没有活跃的 TODO 文件，请先执行 init" >&2
        exit 1
    fi

    # 计算当前执行步骤区的下一个编号
    local last_num
    last_num=$(grep -o 'E[0-9]*\.' "$todo_file" | grep -o '[0-9]*' | sort -n | tail -1 2>/dev/null || echo "0")
    [ -z "$last_num" ] && last_num=0
    local next_num=$((last_num + 1))

    # 在「## 清理」行之前插入新步骤
    sed -i '' "/^## 清理$/i\\
- [ ] E${next_num}. ${desc}
" "$todo_file"
    echo "✅ 已添加: E${next_num}. ${desc}"
}

cmd_list() {
    local todo_file
    todo_file=$(_todo_file)
    if [ -z "$todo_file" ] || [ ! -f "$todo_file" ]; then
        echo "❌ 没有活跃的 TODO 文件" >&2
        exit 1
    fi

    cat "$todo_file"

    # 统计
    local total done
    total=$(grep -c '\- \[[ x]\]' "$todo_file" || echo 0)
    done=$(grep -c '\- \[x\]' "$todo_file" || echo 0)
    echo ""
    echo "--- 进度: ${done}/${total} ---"
}

# 主入口
case "${1:-}" in
    init)  cmd_init "${2:-}" ;;
    check) cmd_check "${2:?需要指定编号}" ;;
    add)   cmd_add "${2:?需要指定步骤描述}" ;;
    list)  cmd_list ;;
    *)
        echo "用法: $0 {init|check|add|list} [参数]" >&2
        exit 1
        ;;
esac
