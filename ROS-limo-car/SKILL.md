---
name: ROS-limo-car
description: 用于控制 LIMO 小车的 skill。适用于查看状态、获取摄像头图像、短时运动控制、单点或多点导航、按指定颜色目标靠近、拍照取图。所有操作通过 scripts/limo_ws_client.py 执行，输出为 JSON。
---

# ROS-limo-car

## 适用范围

这个 skill 适合下面几类任务：

- 查看小车当前状态：里程计、IMU、激光雷达、电池、运动模式
- 让小车短时间运动：前进、后退、转向、横移、急停
- 调用 `move_base` 做单点或多点导航
- 获取实时摄像头图像
- 根据摄像头画面靠近指定颜色目标，并在完成后自动返程
- 远程触发拍照并把图片拉回本地

不适合的任务：

- 基于深度估计的精确抓取
- 纯图像直接转换成 map 坐标的全局导航
- 长时间无人看守的高速自动驾驶

---

## 运行前提

所有操作都通过 [limo_ws_client.py](/home/userli/.openclaw/skills/ROS-limo-car/scripts/limo_ws_client.py) 执行。

维护约束：

- 只要修改了 `scripts/limo_ws_client.py` 的命令、参数、默认值、返回 JSON 结构或控制逻辑，必须同步更新本 `SKILL.md`
- 尤其是 `move`、`get_image`、`approach_color`、`navigate`、`take_photo` 这些对外命令，文档示例和注意事项要与脚本当前行为保持一致

推荐命令：

```bash
TOOL="conda run -n mqtt-server python3 ~/.openclaw/skills/ROS-limo-car/scripts/limo_ws_client.py"
```

如果 `conda run` 不可用：

```bash
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -z "$CONDA_BASE" ]; then
  CONDA_BASE="$HOME/miniconda3"
  [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ] && CONDA_BASE="$HOME/anaconda3"
fi
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate mqtt-server

TOOL="python3 ~/.openclaw/skills/ROS-limo-car/scripts/limo_ws_client.py"
```

兼容性说明：

- 当前 client 已避免使用仅较新 Python 才支持的类型标注写法，适合 ROS 常见环境直接运行
- 如果后续要继续扩展脚本，优先保持对较老 Python 版本的兼容，避免因为语法问题导致命令在启动前就失败

当前这套代码里，客户端默认 WebSocket 地址是：

- `ws://192.168.0.5:8765`

如果你的车不是这个地址，需要显式传：

```bash
$TOOL --host <IP> --port 8765 get_state
```

当前你这边常用摄像头话题是：

- `/usb_cam_0/image_raw`

因此实际调用时，优先显式带上：

```bash
--camera-topic /usb_cam_0/image_raw
```

---

## 推荐操作顺序

执行复杂动作前，优先按这个顺序：

1. 先确认 WebSocket 服务和 ROS 节点已启动。
2. 先跑一次 `get_state`，确认能收到里程计和激光雷达。
3. 再跑一次 `get_image --camera-topic /usb_cam_0/image_raw`，确认图像正常。
4. 先用低速 `move` 做短动作测试。
5. 最后再用 `approach_color` 或 `navigate`。

最小联通性检查：

```bash
$TOOL get_state
$TOOL get_image --camera-topic /usb_cam_0/image_raw --output /tmp/limo_check.jpg
```

---

## 获取状态

```bash
$TOOL get_state
```

返回重点字段：

- `odom.x / odom.y / odom.yaw`：当前位置与朝向
- `scan.front_distance`：当前“前向扇区”的最近距离
- `scan.front_distance_0deg`：0 度扇区最近距离
- `scan.front_distance_180deg`：180 度扇区最近距离
- `scan.min_distance`：整圈最近距离
- `status.battery_voltage`：电池电压
- `status.motion_mode_name`：当前底盘模式

示例：

```json
{
  "success": true,
  "odom": {
    "x": 0.12,
    "y": -0.03,
    "yaw": 5.1,
    "vx": 0.0,
    "vyaw": 0.0
  },
  "scan": {
    "min_distance": 0.45,
    "front_distance": 1.2,
    "front_distance_0deg": 1.2,
    "front_distance_180deg": 2.8,
    "left_distance": 0.8,
    "right_distance": 0.6,
    "points": 360
  },
  "status": {
    "battery_voltage": 12.3,
    "motion_mode": 0,
    "motion_mode_name": "差速(diff)",
    "error_code": 0
  }
}
```

如何判断雷达前向基准：

- 如果小车正前方没有障碍，但 `front_distance_0deg` 很小，可能 0 度不是车头。
- 如果 `front_distance_180deg` 更符合实际车头方向，后续 `approach_color` 用 `--front-basis-deg 180`。

---

## 获取摄像头图像

最常用命令：

```bash
$TOOL get_image --camera-topic /usb_cam_0/image_raw --output /tmp/limo_cam.jpg
```

其他例子：

```bash
$TOOL get_image --camera-topic /usb_cam_0/image_raw --quality 80 --output /tmp/limo_cam.jpg
$TOOL get_image --camera-topic /usb_cam_1/image_raw --output /tmp/cam1.jpg
```

说明：

- 该命令通过 WebSocket 请求服务端返回最近一帧 JPEG 图像
- 输出是 JSON，文件本体写到 `--output`
- 如果长时间收不到图像，先检查车端对应 ROS 话题是否在发布

返回示例：

```json
{
  "success": true,
  "message": "已通过 WebSocket 获取图像",
  "local_path": "/tmp/limo_cam.jpg",
  "width": 1280,
  "height": 720,
  "quality": 85,
  "ts": 1710750000.123
}
```

---

## 短时运动控制

前进、后退、转向、横移都用 `move`：

```bash
# 前进
$TOOL move --linear-x 0.2 --duration 1.0

# 后退
$TOOL move --linear-x -0.15 --duration 1.0

# 左转
$TOOL move --angular-z 0.6 --duration 1.0

# 右转同时前进
$TOOL move --linear-x 0.15 --angular-z -0.4 --duration 1.5

# 横移（仅麦轮模式）
$TOOL move --linear-y 0.15 --duration 1.0
```

参数解释：

| 参数 | 作用 |
|---|---|
| `--linear-x` | 前后速度，正值前进，负值后退 |
| `--angular-z` | 转向角速度，正值左转，负值右转 |
| `--linear-y` | 横向速度，仅麦轮模式有效 |
| `--duration` | 持续时间，结束后自动停车 |
| `--no-verify-odom` | 关闭“命令发出后检查里程计变化”的校验（默认开启） |
| `--min-odom-distance` | 线速度动作判定为“已移动”的最小位移（默认 0.005m） |
| `--min-odom-yaw` | 角速度动作判定为“已转动”的最小航向变化（默认 0.01rad） |

建议：

- 初次测试时，`linear-x` 先不要超过 `0.2`
- 室内调试时，`duration` 先控制在 `1.0` 秒以内
- 当前 `move` 会在持续时间内循环发送 `cmd_vel`，到时后再主动发送一次零速停车
- `duration <= 0` 时不会发送运动指令；如果只想立即刹停，直接用 `stop`
- 若命令发送成功但底盘几乎没动，`move` 会返回 `success=false` 并给出 `diagnosis` 字段（用于快速定位底盘模式/执行链路问题）

急停：

```bash
$TOOL stop
```

---

## 按指定颜色靠近目标

这是当前最实用的视觉功能。它不是 map 导航，而是视觉伺服：

- 摄像头找颜色目标
- 激光雷达做前向避障
- `cmd_vel` 连续微调，让车朝目标靠近
- 到达目标后默认原地旋转 2 圈，再自动返回起点

最常用命令：

```bash
$TOOL approach_color \
  --color blue \
  --camera-topic /usb_cam_0/image_raw
```

建议的安全起步参数：

```bash
$TOOL approach_color \
  --color blue \
  --camera-topic /usb_cam_0/image_raw \
  --linear-x 0.12 \
  --slow-linear-x 0.06 \
  --min-area 180 \
  --stop-distance 0.23 \
  --stop-area-ratio 0.02 \
  --stop-min-area 800 \
  --debug-output /tmp/limo_approach_debug.jpg
```

支持颜色预设：

- `red`
- `orange`
- `yellow`
- `green`
- `blue`
- `purple`

典型例子：

```bash
# 靠近绿色目标
$TOOL approach_color \
  --color green \
  --camera-topic /usb_cam_0/image_raw

# 在更远处就停
$TOOL approach_color \
  --color blue \
  --camera-topic /usb_cam_0/image_raw \
  --stop-distance 0.45

# 雷达前向若实际对应 180 度扇区
$TOOL approach_color \
  --color red \
  --camera-topic /usb_cam_0/image_raw \
  --front-basis-deg 180

# 自定义 HSV 阈值覆盖颜色预设
$TOOL approach_color \
  --camera-topic /usb_cam_0/image_raw \
  --hsv-lower 95,100,60 \
  --hsv-upper 130,255,255

# 红色目标：到达后强制原地停车（不转圈、不返程）
$TOOL approach_color \
  --color red \
  --camera-topic /usb_cam_0/image_raw

# 强制全程不转圈（包括搜索阶段/跟踪阶段/到达后）
$TOOL approach_color \
  --color red \
  --camera-topic /usb_cam_0/image_raw \
  --force-no-spin
```

常用参数：

| 参数 | 含义 |
|---|---|
| `--color` | 目标颜色，默认 `blue` |
| `--camera-topic` | 摄像头话题。当前环境建议用 `/usb_cam_0/image_raw` |
| `--linear-x` | 目标较居中时前进速度 |
| `--slow-linear-x` | 接近目标或偏差较大时的慢速前进速度 |
| `--search-angular-z` | 没发现目标时原地搜索转速 |
| `--stop-distance` | 前向距离小于该值时停车 |
| `--stop-distance-buffer` | 停车距离缓冲，实际停车阈值=`stop-distance+buffer`（默认 0.08m） |
| `--hard-stop-distance` | 最小安全停距硬阈值，前向距离小于该值立即停止（默认 0.35m） |
| `--slow-stop-distance` | 前向距离小于该值时自动降速 |
| `--emergency-stop-distance` | 急停距离阈值 |
| `--stop-area-max-distance` | 面积触发停车时允许的最远前向距离（默认 0.23m） |
| `--stop-center-tolerance` | 面积停车时目标需基本居中（默认 0.24） |
| `--stop-confirm-frames` | 停车条件需连续命中的帧数（默认 4） |
| `--allow-area-stop-without-lidar` | 允许雷达无近距确认时仅靠面积停车（默认关闭） |
| `--spin-after-reach` | 到达后原地转圈（默认开启） |
| `--reach-spin-angular-z` | 到达后转圈角速度（默认 0.7rad/s） |
| `--reach-spin-turns` | 到达后转圈圈数（默认 2） |
| `--reach-spin-interval` | 到达后重复发送转圈指令的周期（默认 0.05s） |
| `--disable-spin-after-reach` | 关闭到达后自动转圈 |
| `--force-no-spin` | 强制全程不转圈（禁用搜索转向/跟踪转向/到达后转圈，并关闭自动返程） |

说明：开启 `--force-no-spin` 后，到达判定会启用快速视觉退出策略（单帧确认），命中后命令立即返回，避免循环长时间不退出。
| `--min-area` | 可靠目标最小面积（默认 180 像素） |
| `--stop-min-area` | 目标面积超过该像素值时也可判定到达（默认 800） |
| `--min-visible-area` | 可见目标最小面积（默认 60 像素） |
| `--weak-linear-x` | 仅“弱检测”时的小速度靠近（默认 0.06m/s） |
| `--weak-center-tolerance` | 弱检测下允许前进的中心偏差（默认 0.3） |
| `--front-basis-deg` | 选择 0 度还是 180 度扇区作为“车头前方” |
| `--use-min-distance-guard` | 开启整圈最小距离保护，侧后方近物也会触发 |
| `--stop-area-ratio` | 颜色区域占画面比例超过该值时认为已靠近（默认 0.02） |
| `--min-move-distance` | 失败诊断时判定“底盘几乎没动”的最小位移（默认 0.01m） |
| `--hsv-lower` / `--hsv-upper` | 自定义 HSV 阈值 |
| `--debug-output` | 保存最后一帧带检测框的调试图 |
| `--record-start-pose` | 进入靠近流程时记录当前起点坐标（默认开启） |
| `--no-record-start-pose` | 本次不记录起点 |
| `--start-pose-file` | 起点坐标文件路径（默认 `/tmp/limo_start_pose.json`） |
| `--return-to-start` | 转圈后自动返回起点（默认开启） |
| `--no-return-to-start` | 关闭自动返程 |
| `--return-frame` | 自动返程使用的坐标系，默认 `odom` |
| `--return-timeout` | 自动返程超时秒数，默认 120 |
| `--return-final-yaw-offset` | 返程完成后在起点朝向上追加的角度偏移，默认 `0`（不翻转） |
| `--no-return-final-yaw-flip` | 兼容参数：返程完成后不做 180 度翻转（会把偏移设为 0） |
| `--refine-after-nav` | 自动返程导航后执行里程计精修（默认开启） |
| `--no-refine-after-nav` | 关闭自动返程后的精修 |
| `--refine-pos-tol` | 精修位置误差阈值（默认 0.04m） |
| `--refine-yaw-tol` | 精修朝向误差阈值（默认 0.10rad） |
| `--refine-max-steps` | 精修最大迭代次数（默认 320） |
| `--refine-step-duration` | 每次精修控制持续时间（默认 0.25s） |
| `--refine-max-linear-x` | 精修最大前进速度（默认 0.45m/s） |

返回判断：

- `success=true && reached=true`：成功靠近
- `success=true && reached=false && stop_reason=emergency_front_obstacle`：前方太近触发急停
- `success=true && reached=false && stop_reason=emergency_any_direction_obstacle`：整圈最小距离保护触发
- `success=false`：超时、未找到目标、WebSocket 错误或参数错误；此时会附带 `diagnosis` 和 `suggested_params`

成功示例：

```json
{
  "success": true,
  "reached": true,
  "stop_reason": "target_reached",
  "iterations": 14,
  "color": "blue",
  "selected_front_distance": 0.34,
  "front_basis_deg": 0,
  "last_detection": {
    "found": true,
    "center_error": 0.06,
    "area_ratio": 0.21
  }
}
```

这条命令的实际策略：

1. 先收一帧雷达状态
2. 再抓一帧图像
3. 找到画面中面积最大的指定颜色区域
4. 根据目标偏离画面中心的程度，决定转向角速度
5. 目标居中时前进；若已看到目标但面积偏小，会走“弱检测慢速靠近”策略
6. 当前向距离足够近，或目标面积满足阈值且连续命中后停车
7. 默认原地转 2 圈
8. 然后自动导航并精修回到起点
9. 最后按起点朝向结束（默认不额外翻转）

常见问题：

- 前面没障碍却总说太近：
  先看 `get_state` 里的 `front_distance_0deg` 和 `front_distance_180deg`，然后切换 `--front-basis-deg`
- 侧面物体太近导致误停：
  不要启用 `--use-min-distance-guard`
- 看不到颜色目标：
  检查光照、话题是否正确，必要时改 `--hsv-lower/--hsv-upper`
- 能检测到颜色但一直判定未靠近：
  先看返回里的 `max_seen_area`、`max_seen_area_ratio`、`suggested_params`，优先下调 `--min-area` 或 `--stop-area-ratio`
- 能检测到颜色但停得太远：
  先提高 `--stop-area-ratio`（例如 `0.02~0.05`），或直接调高 `--stop-min-area`
- 已到达但不希望继续转圈：
  调用时加 `--disable-spin-after-reach`
- 已到达但这次不想自动返程：
  调用时加 `--no-return-to-start`
- 红色目标到达后仍继续动作：
  当前代码已内置红色停驻策略，`--color red` 到达后会强制原地停（不转圈、不返程）；且红色停车使用单帧确认并放宽居中约束，减少“到达后仍原地转圈”
- 颜色看到了但车不动：
  先用 `move` 自检；若 `diagnosis` 提示 `cmd_vel_sent_but_odom_almost_unchanged`，先排查底盘模式和驱动链路
- 目标颜色很多时选错目标：
  当前实现会默认选面积最大的同色区域

---

## 三阶段拆分执行（全部在本 SKILL 内）

按你的要求，不再拆多个目录。三阶段都通过同一个 client 命令组合实现：

1. 到达目标区域
2. 原地转圈
3. 返程

### 阶段 1：只到达目标区域（不转圈、不返程）

```bash
$TOOL approach_color \
  --color blue \
  --camera-topic /usb_cam_0/image_raw \
  --disable-spin-after-reach \
  --no-return-to-start
```

成功判定重点：

- `success=true`
- `reached=true`
- `return_to_start=false`

### 阶段 2：只转圈（在当前点位）

当前 `limo_ws_client.py` 暂无独立 `spin` 子命令。可通过 `approach_color` 触发内置 `_spin_for_turns`：

```bash
$TOOL approach_color \
  --color blue \
  --camera-topic /usb_cam_0/image_raw \
  --linear-x 0.0 \
  --slow-linear-x 0.0 \
  --search-angular-z 0.0 \
  --stop-distance 999 \
  --stop-confirm-frames 1 \
  --spin-after-reach \
  --reach-spin-angular-z 0.7 \
  --reach-spin-turns 2.0 \
  --no-return-to-start
```

成功判定重点：

- `success=true`
- `reached=true`
- `spin_after_reach=true`
- `return_to_start=false`

### 阶段 3：返程到起点

阶段 1 默认会记录起点到 `/tmp/limo_start_pose.json`。返程用 `navigate`：

```bash
POSE=/tmp/limo_start_pose.json
X=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["x"])' "$POSE")
Y=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["y"])' "$POSE")
YAW=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["yaw"])' "$POSE")
FRAME=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("frame","odom"))' "$POSE")

$TOOL navigate --frame "$FRAME" --x "$X" --y "$Y" --yaw "$YAW" --timeout 120
```

建议返程后补一次停车：

```bash
$TOOL stop
```

---

## 导航

这部分依赖车端 `move_base` 正常工作，适合“已知 map 坐标”的目标，不适合直接根据图像里的目标点导航。

单点导航：

```bash
$TOOL navigate --x 1.0 --y 0.5 --yaw 1.57
$TOOL navigate --x 2.0 --y -0.3 --yaw 0.0 --timeout 90
$TOOL navigate --frame map --x 0.0 --y 0.0 --yaw 3.14
```

多点导航：

```bash
$TOOL navigate --waypoints "1.0,0.0,0; 1.0,1.0,1.57; 0.0,0.0,3.14"
```

参数：

| 参数 | 含义 |
|---|---|
| `--x` | 单点导航 x |
| `--y` | 单点导航 y |
| `--yaw` | 目标朝向，单位 rad |
| `--frame` | 坐标系，默认 `map` |
| `--timeout` | 每个目标点超时时间，默认 120 秒 |
| `--waypoints` | 多点导航，格式 `"x,y,yaw; x,y,yaw; ..."` |

使用前确认：

- 车端导航节点已启动
- `move_base` action server 可用
- 地图已经加载成功

---

## 拍照并拉回本地

```bash
$TOOL take_photo
$TOOL take_photo --output /tmp/limo_photo.jpg
```

返回示例：

```json
{
  "success": true,
  "local_path": "/tmp/limo_photo.jpg",
  "remote_path": "/home/agilex/Desktop/color_photo_fixed.jpg"
}
```

说明：

- 通过 SSH 到车端执行拍照脚本
- 再通过 `scp` 拉回本地
- 依赖 `sshpass`

---

## 车端启动参考

建图：

```bash
roslaunch limo_bringup limo_start.launch
roslaunch limo_bringup limo_teletop_keyboard.launch
roslaunch limo_bringup limo_cartographer.launch
rosrun map_server map_saver -f ~/maps/limo_map
```

导航：

```bash
roslaunch limo_bringup limo_start.launch
rosrun map_server map_server ~/maps/limo_map.yaml
roslaunch limo_bringup limo_navigation_diff.launch
```

WebSocket 服务：

```bash
python3 limo_ws_server.py
```

---

## 最常用的几条命令

```bash
TOOL="conda run -n mqtt-server python3 ~/.openclaw/skills/ROS-limo-car/scripts/limo_ws_client.py"

# 1. 查状态
$TOOL get_state

# 2. 看图
$TOOL get_image --camera-topic /usb_cam_0/image_raw --output /tmp/limo.jpg

# 3. 小幅前进
$TOOL move --linear-x 0.15 --duration 1.0

# 4. 靠近蓝色目标
$TOOL approach_color --color blue --camera-topic /usb_cam_0/image_raw

# 5. 立即停车
$TOOL stop
```

---

## 注意事项

- 默认先低速测试，再逐步加速
- 若 `move` 看起来“没执行”，先确认脚本本身能正常启动，再确认 WebSocket 服务在线、底盘模式正确
- `approach_color` 是视觉闭环靠近，不是地图导航
- 若当前环境的 RGB 摄像头是 `/usb_cam_0/image_raw`，请显式传入该话题
- `status.error_code != 0` 说明底盘状态异常，先排查再动
- 若图像正常但颜色检测不稳定，优先调 HSV 阈值和光照
