#!/usr/bin/env bash

# Optional positional arguments:
# 1) dataset name (default: so101_try_001)
# 2) single task text (default: pick and place test)
# 3) follower robot port (default: /dev/tty.usbmodem5AA90243381)
# 4) leader teleop port (default: /dev/tty.usbmodem5AA90242591)
DATASET_NAME="${1:-so101_try_001}"
SINGLE_TASK="${2:-pick and place test}"
ROBOT_PORT="${3:-/dev/tty.usbmodem5AA90243381}"
TELEOP_PORT="${4:-/dev/tty.usbmodem5AA90242591}"
DATASET_NAMESPACE="${DATASET_NAMESPACE:-local}"
DATASET_REPO_ID="${DATASET_NAMESPACE}/${DATASET_NAME}"
DATASET_BASE_ROOT="${DATASET_ROOT:-$(pwd)}"
EXPECTED_DATASET_PATH="${DATASET_BASE_ROOT}/${DATASET_REPO_ID}"
PLAY_SOUNDS="${PLAY_SOUNDS:-false}"
DISPLAY_DATA="${DISPLAY_DATA:-false}"

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
if [ -n "$LEROBOT_ROOT" ]; then
	echo "🔍 切换到 lerobot 目录：$LEROBOT_ROOT"
	cd "$LEROBOT_ROOT" || {
		echo "❌ 错误：无法切换到目录 $LEROBOT_ROOT，请检查 LEROBOT_ROOT 是否正确！"
		exit 1
	}
else
	echo "📂 未设置 LEROBOT_ROOT，保持当前目录：$(pwd)"
fi

echo "🔧 激活 lerobot Conda 环境..."
conda activate lerobot || {
	echo "❌ 错误：无法激活 lerobot 环境！请执行 conda env list 检查环境是否存在。"
	exit 1
}

if ! command -v lerobot-record >/dev/null 2>&1; then
	echo "❌ 错误：当前 lerobot 环境中未找到 lerobot-record 命令。"
	echo "请检查 lerobot 是否已正确安装到 Conda 环境中。"
	exit 1
fi

mkdir -p "$(dirname "$EXPECTED_DATASET_PATH")" || {
	echo "❌ 错误：无法创建数据集父目录：$(dirname "$EXPECTED_DATASET_PATH")"
	exit 1
}

# ============= 执行 lerobot-record 命令 =============
echo "🚀 开始执行 lerobot-record..."
echo "📦 本次数据集名称：$DATASET_NAME"
echo "🏷️  本地数据集标识：$DATASET_REPO_ID"
echo "📁 数据集父目录：$DATASET_BASE_ROOT"
echo "🔌 使用 follower 端口：$ROBOT_PORT"
echo "🔌 使用 leader 端口：$TELEOP_PORT"
echo "🔊 播报提示音：$PLAY_SOUNDS"
echo "🖥️  实时数据显示：$DISPLAY_DATA"
echo "🗂️  预期输出目录：$EXPECTED_DATASET_PATH"
lerobot-record \
  --robot.type=so101_follower \
	--robot.port="$ROBOT_PORT" \
  --robot.id=my_awesome_follower_arm1 \
  --teleop.type=so101_leader \
  --teleop.port="$TELEOP_PORT" \
  --teleop.id=my_awesome_leader_arm1 \
  --dataset.repo_id="$DATASET_REPO_ID" \
  --dataset.root="$EXPECTED_DATASET_PATH" \
  --dataset.single_task="$SINGLE_TASK" \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=20 \
  --dataset.reset_time_s=5 \
  --dataset.push_to_hub=false \
  --play_sounds="$PLAY_SOUNDS" \
  --display_data="$DISPLAY_DATA"

# ============= 执行完成后的清理 =============
RECORD_EXIT_CODE=$?
if [ $RECORD_EXIT_CODE -eq 0 ]; then
	echo "✅ lerobot-record 执行成功！"
	if [ -d "$EXPECTED_DATASET_PATH" ]; then
		echo "📁 录制数据目录：$EXPECTED_DATASET_PATH"
	else
		echo "ℹ️ 命令已成功，若未即时看到目录，请检查：$DATASET_BASE_ROOT/$DATASET_NAMESPACE/"
	fi
else
	echo "❌ lerobot-record 执行失败，退出码：$RECORD_EXIT_CODE"
fi

conda deactivate
exit $RECORD_EXIT_CODE
