#!/usr/bin/env bash

set -u

# Optional positional arguments:
# 1) dataset name (default: so101_try_001)
# 2) single task text (default: pick and place test)
# 3) follower robot port (default: /dev/ttyACM1)
# 4) leader teleop port (default: /dev/ttyACM0)
DATASET_NAME="${1:-so101_try_001}"
SINGLE_TASK="${2:-pick and place test}"
ROBOT_PORT="${3:-/dev/ttyACM1}"
TELEOP_PORT="${4:-/dev/ttyACM0}"
DATASET_REPO_ID="./${DATASET_NAME}"
PROJECT_ROOT="${LEROBOT_PROJECT_ROOT:-$HOME/lerobot}"
CACHE_ROOT="${HF_LEROBOT_CACHE_DIR:-$HOME/.cache/huggingface/lerobot}"
EXPECTED_CACHE_PATH="${CACHE_ROOT}/${DATASET_NAME}"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-lerobot}"
PLAY_SOUNDS="${LEROBOT_PLAY_SOUNDS:-false}"
DISPLAY_DATA="${LEROBOT_DISPLAY_DATA:-false}"

send_stop_signal() {
	local target_pid="$1"
	if kill -0 "$target_pid" 2>/dev/null; then
		echo
		echo "⏹️  检测到 Q，正在停止录制并保存..."
		kill -INT "$target_pid" 2>/dev/null || true
	fi
}

# ============= 关键修复：强制加载 Conda 配置（解决非交互式运行问题） =============
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -z "$CONDA_BASE" ]; then
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

if ! command -v lerobot-record >/dev/null 2>&1; then
	echo "❌ 错误：当前环境中找不到 lerobot-record 命令。"
	echo "当前环境：$CONDA_ENV_NAME"
	exit 1
fi

if [ ! -e "$ROBOT_PORT" ]; then
	echo "❌ 错误：未找到 follower 设备端口 $ROBOT_PORT"
	exit 1
fi

if [ ! -e "$TELEOP_PORT" ]; then
	echo "❌ 错误：未找到 leader 设备端口 $TELEOP_PORT"
	exit 1
fi

if [ -d "$EXPECTED_CACHE_PATH" ]; then
	echo "🧹 检测到已有数据集目录，先删除：$EXPECTED_CACHE_PATH"
	rm -rf "$EXPECTED_CACHE_PATH"
fi

mkdir -p "$CACHE_ROOT"

# ============= 执行 lerobot-record 命令 =============
echo "🚀 开始执行 lerobot-record..."
echo "📦 本次数据集名称：$DATASET_NAME"
echo "🔌 使用 follower 端口：$ROBOT_PORT"
echo "🔌 使用 leader 端口：$TELEOP_PORT"
echo "📂 lerobot 项目目录：$PROJECT_ROOT"
echo "🧪 Conda 环境：$CONDA_ENV_NAME"
echo "🔊 播报提示音：$PLAY_SOUNDS"
echo "🖥️  图形数据显示：$DISPLAY_DATA"
echo "🗂️  预期缓存目录：$EXPECTED_CACHE_PATH"
lerobot-record \
  --robot.type=so101_follower \
	--robot.port="$ROBOT_PORT" \
  --robot.id=my_awesome_follower_arm1 \
  --teleop.type=so101_leader \
	--teleop.port="$TELEOP_PORT" \
  --teleop.id=my_awesome_leader_arm1 \
  --dataset.repo_id="$DATASET_REPO_ID" \
  --dataset.single_task="$SINGLE_TASK" \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=20 \
  --dataset.reset_time_s=5 \
  --dataset.push_to_hub=false \
  --play_sounds="$PLAY_SOUNDS" \
  --display_data="$DISPLAY_DATA" &

RECORD_PID=$!
KEY_WATCHER_PID=""

if [ -t 0 ]; then
	echo "⌨️  录制进行中，按 Q 退出并保存。"
	(
		while IFS= read -r -n 1 key; do
			case "$key" in
				q|Q)
					send_stop_signal "$RECORD_PID"
					break
					;;
			esac
		done
	) &
	KEY_WATCHER_PID=$!
fi

wait "$RECORD_PID"

# ============= 执行完成后的清理 =============
RECORD_EXIT_CODE=$?

if [ -n "$KEY_WATCHER_PID" ] && kill -0 "$KEY_WATCHER_PID" 2>/dev/null; then
	kill "$KEY_WATCHER_PID" 2>/dev/null || true
	wait "$KEY_WATCHER_PID" 2>/dev/null || true
fi

if [ $RECORD_EXIT_CODE -eq 0 ]; then
	echo "✅ lerobot-record 执行成功！"
	if [ -d "$EXPECTED_CACHE_PATH" ]; then
		echo "📁 录制数据目录：$EXPECTED_CACHE_PATH"
	else
		echo "ℹ️ 命令已成功，若未即时看到目录，请检查：$CACHE_ROOT/so101_try_00*"
	fi
else
	echo "❌ lerobot-record 执行失败，退出码：$RECORD_EXIT_CODE"
fi

conda deactivate
exit $RECORD_EXIT_CODE
