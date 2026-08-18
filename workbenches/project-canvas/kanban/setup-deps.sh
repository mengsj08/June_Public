#!/usr/bin/env bash
# Kanban 依赖自动安装脚本
# 用法:
#   ./setup-deps.sh           # 立即安装/检查依赖
#   ./setup-deps.sh --check   # 仅检查，不安装
#   ./setup-deps.sh --schedule "08:00"  # 在指定时间点触发安装

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
LOG_FILE="$SCRIPT_DIR/.deps-install.log"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
DEPS_DIR="$SCRIPT_DIR/.deps"
INSTALL_TARGET=""

# ── 颜色输出 ──
info()  { echo -e "\033[36m[INFO]\033[0m $*"; }
ok()    { echo -e "\033[32m[OK]\033[0m $*"; }
warn()  { echo -e "\033[33m[WARN]\033[0m $*"; }
err()   { echo -e "\033[31m[ERROR]\033[0m $*" >&2; }

runtime_python() {
    if [[ "$INSTALL_TARGET" == "venv" && -x "$VENV_PYTHON" ]]; then
        echo "$VENV_PYTHON"
        return
    fi
    echo "python3"
}

run_runtime_python() {
    local py
    py=$(runtime_python)
    if [[ "$INSTALL_TARGET" == "deps" ]]; then
        PYTHONPATH="$DEPS_DIR${PYTHONPATH:+:$PYTHONPATH}" "$py" "$@"
        return
    fi
    "$py" "$@"
}

has_working_venv() {
    [[ -x "$VENV_PYTHON" ]] && "$VENV_PYTHON" -c 'import sys' >/dev/null 2>&1
}

detect_runtime() {
    if has_working_venv; then
        INSTALL_TARGET="venv"
    elif [[ -d "$DEPS_DIR" ]]; then
        INSTALL_TARGET="deps"
    else
        INSTALL_TARGET=""
    fi
}

# ── 检查 Python3 ──
check_python() {
    if ! command -v python3 &>/dev/null; then
        err "未找到 python3，请先安装 Python 3.8+"
        exit 1
    fi

    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    info "Python 版本: $py_ver"
}

# ── 创建 venv（如不存在）──
ensure_venv() {
    if has_working_venv; then
        INSTALL_TARGET="venv"
        ok "venv 已存在: $VENV_DIR"
        return
    fi

    if [[ -d "$VENV_DIR" ]]; then
        warn "检测到不可用或跨平台复制的 venv，正在重建: $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi

    info "创建 venv: $VENV_DIR"

    # Try creating venv directly
    if python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1 && has_working_venv; then
        INSTALL_TARGET="venv"
        ok "venv 创建成功"
        return
    fi

    # venv module missing — try installing python3-venv
    warn "venv 模块不可用，尝试安装 python3-venv..."
    if command -v apt-get &>/dev/null; then
        local venv_pkg
        local -a apt_cmd
        venv_pkg=$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")')
        if [[ "$(id -u)" -eq 0 ]]; then
            apt_cmd=(apt-get install -y)
        elif command -v sudo &>/dev/null; then
            apt_cmd=(sudo apt-get install -y)
        else
            apt_cmd=()
        fi

        if (( ${#apt_cmd[@]} > 0 )) && (
            "${apt_cmd[@]}" python3-venv >> "$LOG_FILE" 2>&1 ||
            "${apt_cmd[@]}" "$venv_pkg" >> "$LOG_FILE" 2>&1
        ); then
            if python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1 && has_working_venv; then
                INSTALL_TARGET="venv"
                ok "venv 创建成功 (已自动安装 python3-venv)"
                return
            fi
        fi
    fi

    # Fallback: install to local .deps directory
    warn "venv 不可用，使用 pip --target 安装到本地"
    mkdir -p "$DEPS_DIR"
    python3 -m pip install --target="$DEPS_DIR" --upgrade --quiet -r "$REQUIREMENTS_FILE" 2>&1 | tee -a "$LOG_FILE"
    INSTALL_TARGET="deps"
    ok "依赖已安装到 $DEPS_DIR"
}

# ── 安装依赖到 venv ──
install_deps() {
    if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
        err "未找到 $REQUIREMENTS_FILE"
        exit 1
    fi

    ensure_venv

    if [[ "$INSTALL_TARGET" == "venv" ]]; then
        info "安装依赖到 venv..."
        "$VENV_PYTHON" -m pip install --quiet -r "$REQUIREMENTS_FILE" 2>&1 | tee -a "$LOG_FILE"
    elif [[ "$INSTALL_TARGET" == "deps" ]]; then
        info "使用本地 .deps 依赖目录"
    else
        err "未找到可用的 Python 依赖安装目标"
        exit 1
    fi
    ok "依赖安装完成"
}

# ── 校验依赖是否就绪 ──
verify_deps() {
    local py
    detect_runtime
    if [[ -z "$INSTALL_TARGET" ]]; then
        err "未找到已安装依赖，请先运行 $0"
        return 1
    fi
    py=$(runtime_python)

    info "校验依赖..."
    while IFS= read -r line; do
        # 跳过空行和注释
        [[ -z "$line" || "$line" == \#* ]] && continue

        # 提取包名 (去掉版本约束)
        local pkg
        pkg=$(echo "$line" | sed 's/[<>=!].*//' | sed 's/\[.*//')
        local import_name="$pkg"
        if [[ "$pkg" == "PyYAML" ]]; then
            import_name="yaml"
        fi

        if run_runtime_python -c "import ${import_name//-/_}" 2>/dev/null; then
            ok "$pkg ✓"
        else
            err "$pkg ✗ — 导入失败"
            return 1
        fi
    done < "$REQUIREMENTS_FILE"
}

# ── 定时触发 ──
schedule_install() {
    local target_time="$1"
    local current_time
    current_time=$(date +%H:%M)

    # 计算等待秒数
    local target_sec current_sec wait_sec
    target_sec=$(echo "$target_time" | awk -F: '{print $1*3600+$2*60}')
    current_sec=$(echo "$current_time" | awk -F: '{print $1*3600+$2*60}')
    wait_sec=$(( target_sec - current_sec ))

    if (( wait_sec <= 0 )); then
        wait_sec=$(( wait_sec + 86400 ))  # 跨天
    fi

    info "当前时间: $current_time"
    info "计划在 $target_time 安装依赖 (等待 $(( wait_sec / 60 )) 分钟)"

    # 后台等待并执行
    nohup bash -c "
        sleep $wait_sec
        echo '=== $(date) 定时安装开始 ===' >> '$LOG_FILE'
        '$0' >> '$LOG_FILE' 2>&1
        echo '=== $(date) 定时安装结束 ===' >> '$LOG_FILE'
    " &>/dev/null &

    local pid=$!
    ok "后台任务已启动 (PID: $pid)"
    info "日志文件: $LOG_FILE"
}

# ── 主流程 ──
main() {
    echo "" >> "$LOG_FILE"
    echo "=== $(date) ===" >> "$LOG_FILE"

    case "${1:-}" in
        --check)
            check_python
            verify_deps
            ;;
        --schedule)
            if [[ -z "${2:-}" ]]; then
                err "用法: $0 --schedule HH:MM"
                exit 1
            fi
            schedule_install "$2"
            ;;
        *)
            check_python
            install_deps
            verify_deps
            info "所有依赖已就绪"
            ;;
    esac
}

main "$@"
