#!/usr/bin/env bash

set -u

# Optional positional arguments:
# 1) dataset repo path (default: ~/.cache/huggingface/lerobot/so101_try_002)
# 2) robot port (default: /dev/ttyACM1)
DATASET_REPO_ID="${1:-$HOME/.cache/huggingface/lerobot/so101_try_002}"
DATASET_INPUT="$DATASET_REPO_ID"
ROBOT_PORT="${2:-/dev/ttyACM1}"
PROJECT_ROOT="${LEROBOT_PROJECT_ROOT:-$HOME/lerobot}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-lerobot}"
PLAY_SOUNDS="${LEROBOT_PLAY_SOUNDS:-false}"
DATASET_ROOT_ARG=""
DATASET_ROOT_OPTIONS=()
DATASET_INFO_PATH=""
DATASET_TASKS_PATH=""

if [ -d "$DATASET_REPO_ID" ]; then
    DATASET_DIR="$(cd "$DATASET_REPO_ID" && pwd)"
    DATASET_ROOT_ARG="$DATASET_DIR"
    DATASET_REPO_ID="$(basename "$DATASET_DIR")"
    DATASET_ROOT_OPTIONS=(--dataset.root="$DATASET_ROOT_ARG")
    DATASET_INFO_PATH="$DATASET_DIR/meta/info.json"
    DATASET_TASKS_PATH="$DATASET_DIR/meta/tasks.parquet"
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
echo "🔍 切换到 lerobot 目录：$PROJECT_ROOT"
cd "$PROJECT_ROOT" || {
    echo "❌ 错误：无法切换到目录 $PROJECT_ROOT，请检查 LEROBOT_PROJECT_ROOT 是否正确！"
    exit 1
}

echo "🔧 激活 $CONDA_ENV_NAME Conda 环境..."
conda activate "$CONDA_ENV_NAME" || {
    echo "❌ 错误：无法激活 $CONDA_ENV_NAME 环境！请执行 conda env list 检查环境是否存在。"
    exit 1
}

if ! command -v lerobot-replay >/dev/null 2>&1; then
    echo "❌ 错误：当前环境中找不到 lerobot-replay 命令。"
    echo "当前环境：$CONDA_ENV_NAME"
    exit 1
fi

if [ ! -e "$DATASET_INPUT" ]; then
    echo "❌ 错误：未找到数据集路径 $DATASET_INPUT"
    exit 1
fi

if [ -n "$DATASET_ROOT_ARG" ]; then
    if [ ! -f "$DATASET_INFO_PATH" ]; then
        echo "❌ 错误：本地数据集缺少元数据文件 $DATASET_INFO_PATH"
        exit 1
    fi

    if [ ! -f "$DATASET_TASKS_PATH" ]; then
        echo "❌ 错误：本地数据集不完整，缺少 $DATASET_TASKS_PATH"
        echo "这通常表示录制没有成功保存完成，当前目录还不能用于 replay。"
        exit 1
    fi
fi

if [ ! -e "$ROBOT_PORT" ]; then
    echo "❌ 错误：未找到 follower 设备端口 $ROBOT_PORT"
    exit 1
fi

# ============= 执行 lerobot-replay 命令 =============
echo "🚀 开始执行 lerobot-replay..."
echo "📦 使用数据集路径：$DATASET_REPO_ID"
if [ -n "$DATASET_ROOT_ARG" ]; then
    echo "📁 数据集根目录：$DATASET_ROOT_ARG"
fi
echo "🔌 使用 follower 端口：$ROBOT_PORT"
echo "📂 lerobot 项目目录：$PROJECT_ROOT"
echo "🧪 Conda 环境：$CONDA_ENV_NAME"
echo "🔊 播报提示音：$PLAY_SOUNDS"
lerobot-replay \
  --robot.type=so101_follower \
  --robot.port="$ROBOT_PORT" \
  --robot.id=my_awesome_follower_arm1 \
  --dataset.repo_id="$DATASET_REPO_ID" \
  "${DATASET_ROOT_OPTIONS[@]}" \
  --dataset.episode=0 \
  --play_sounds="$PLAY_SOUNDS"

# ============= 执行完成后的清理 =============
# 获取命令执行结果
REPLAY_EXIT_CODE=$?
if [ $REPLAY_EXIT_CODE -eq 0 ]; then
    echo "✅ lerobot-replay 执行成功！"
else
    echo "❌ lerobot-replay 执行失败，退出码：$REPLAY_EXIT_CODE"
fi

conda deactivate
exit $REPLAY_EXIT_CODE
