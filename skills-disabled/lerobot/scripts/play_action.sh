#!/usr/bin/env bash

# Optional positional arguments:
# 1) dataset repo path (default: ./so101_try_002)
# 2) robot port (default: /dev/tty.usbmodem5AA90243381)
DATASET_REPO_ID="${1:-./so101_try_002}"
ROBOT_PORT="${2:-/dev/tty.usbmodem5AA90243381}"
DATASET_ROOT=""

# Preserve the caller's dataset path even if we later change directories.
if [[ "$DATASET_REPO_ID" != /* ]]; then
    DATASET_REPO_ID="$(realpath "$DATASET_REPO_ID")"
fi

if [ -d "$DATASET_REPO_ID" ]; then
    if [ ! -f "$DATASET_REPO_ID/meta/info.json" ]; then
        echo "❌ 错误：本地数据集目录不完整，缺少 $DATASET_REPO_ID/meta/info.json"
        echo "请确认你传入的是 LeRobot 数据集根目录，而不是脚本目录下的占位路径。"
        exit 1
    fi

    DATASET_ROOT="$DATASET_REPO_ID"
    DATASET_REPO_ID="$(basename "$DATASET_REPO_ID")"
fi

# ============= 关键修复：强制加载 Conda 配置（解决非交互式运行问题） =============
# 自动检测 Conda 安装路径（兼容 miniconda/anaconda）
# 自动检测 Conda 安装路径（兼容 miniconda/anaconda）
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -z "$CONDA_BASE" ]; then
    # 尝试默认路径
    CONDA_BASE="$HOME/miniconda3"
    if [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        CONDA_BASE="$HOME/anaconda3"
    fi

    if [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        echo "❌ 错误：未找到 Conda 安装路径，请先安装并初始化 Conda！"
        echo "尝试的路径：$CONDA_BASE"
        exit 1
    fi
fi

# 加载 Conda 核心配置
if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    source "$CONDA_BASE/etc/profile.d/conda.sh"
else
    echo "❌ 错误：Conda 配置文件不存在，请重新执行 conda init bash！"
    exit 1
fi

# ============= 切换到 lerobot 目录并激活环境 =============
# LEROBOT_ROOT is optional. Most setups can run from the current directory
# as long as the lerobot Conda environment exposes the CLI commands.
if [ -n "$LEROBOT_ROOT" ]; then
    echo "🔍 切换到 lerobot 目录：$LEROBOT_ROOT"
    cd "$LEROBOT_ROOT" || {
        echo "❌ 错误：无法切换到目录 $LEROBOT_ROOT，请检查 LEROBOT_ROOT 是否正确！"
        exit 1
    }
else
    echo "📂 未设置 LEROBOT_ROOT，保持当前目录：$(pwd)"
fi

# 激活 lerobot 环境
echo "🔧 激活 lerobot Conda 环境..."
conda activate lerobot || {
    echo "❌ 错误：无法激活 lerobot 环境！请执行 conda env list 检查环境是否存在。"
    exit 1
}

if ! command -v lerobot-replay >/dev/null 2>&1; then
    echo "❌ 错误：当前 lerobot 环境中未找到 lerobot-replay 命令。"
    echo "请检查 lerobot 是否已正确安装到 Conda 环境中。"
    exit 1
fi

# ============= 执行 lerobot-replay 命令 =============
echo "🚀 开始执行 lerobot-replay..."
echo "📦 使用数据集路径：$DATASET_REPO_ID"
if [ -n "$DATASET_ROOT" ]; then
    echo "📁 使用数据集根目录：$DATASET_ROOT"
fi
echo "🔌 使用 follower 端口：$ROBOT_PORT"
lerobot-replay \
  --robot.type=so101_follower \
    --robot.port="$ROBOT_PORT" \
  --robot.id=my_awesome_follower_arm \
    --dataset.repo_id="$DATASET_REPO_ID" \
    --dataset.root="$DATASET_ROOT" \
  --dataset.episode=0

# ============= 执行完成后的清理 =============
# 获取命令执行结果
REPLAY_EXIT_CODE=$?
if [ $REPLAY_EXIT_CODE -eq 0 ]; then
    echo "✅ lerobot-replay 执行成功！"
else
    echo "❌ lerobot-replay 执行失败，退出码：$REPLAY_EXIT_CODE"
fi

# 退出 Conda 环境（非必需，脚本结束后自动退出）
conda deactivate
exit $REPLAY_EXIT_CODE
