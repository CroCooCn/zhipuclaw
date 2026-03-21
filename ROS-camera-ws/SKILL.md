---
name: ROS-camera-ws
description: 通过 WebSocket 从 ROS 摄像头话题获取图像的 skill。适用于向本机或远端的摄像头 WebSocket 服务请求一帧 JPEG 图像并保存到本地。服务端脚本订阅 ROS2 图像话题，客户端脚本通过 JSON 请求图像。
---

# ROS-camera-ws

## 适用范围

这个 skill 适合下面几类任务：

- 从 ROS2 摄像头话题抓取一帧图片
- 通过 WebSocket 向摄像头服务端请求最新图像
- 把图片保存到本地路径，返回 JSON 结果

不适合的任务：

- 连续视频流录像
- 多相机同步标定
- 深度图、点云处理

---

## 文件结构

- 服务端：[camera_ws_server.py](/home/userli/.openclaw/skills/ROS-camera-ws/scripts/camera_ws_server.py)
- 客户端：[camera_ws_client.py](/home/userli/.openclaw/skills/ROS-camera-ws/scripts/camera_ws_client.py)

---

## 运行前提

需要 ROS2 环境和摄像头话题已启动，例如：

```bash
source /opt/ros/humble/setup.bash
ros2 run usb_cam usb_cam_node_exe --ros-args -p video_device:=/dev/video0
```

如果默认启动不稳定，优先把 `usb_cam` 调到直接输出 `rgb8` 的稳定模式。当前这边已经验证可用的一种做法是：

```bash
source /opt/ros/humble/setup.bash
ros2 run usb_cam usb_cam_node_exe --ros-args \
  -p video_device:=/dev/video0 \
  -p pixel_format:=yuyv2rgb \
  -p image_width:=640 \
  -p image_height:=480 \
  -p framerate:=15.0
```

验证成功的标志是：

```bash
source /opt/ros/humble/setup.bash
ros2 topic echo /image_raw --once
```

输出里应看到：

```text
encoding: rgb8
width: 640
height: 480
```

然后启动 WebSocket 服务端：

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3 ~/.openclaw/skills/ROS-camera-ws/scripts/camera_ws_server.py
```

如果摄像头话题不是默认值，可以显式指定：

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3 ~/.openclaw/skills/ROS-camera-ws/scripts/camera_ws_server.py \
  --camera-topic /image_raw \
  --host 0.0.0.0 \
  --port 8766
```

客户端常用命令：

```bash
TOOL="/usr/bin/python3 ~/.openclaw/skills/ROS-camera-ws/scripts/camera_ws_client.py"
```

兼容性说明：

- 服务端和客户端都建议直接使用 `/usr/bin/python3`
- 不建议混用 conda Python 与 ROS Python
- 当前服务端已按简洁原则收敛，只支持稳定的 `rgb8`、`bgr8`、`mono8`
- 如果图像话题已经是 `rgb8`，就不需要再做任何特殊转换

---

## 获取图片

最常用命令：

```bash
$TOOL get_image --output /tmp/camera.jpg
```

指定远端服务地址：

```bash
$TOOL --host 172.31.94.183 --port 8766 get_image --output /tmp/camera.jpg
```

指定压缩质量与 ROS 话题名：

```bash
$TOOL --host 172.31.94.183 --port 8766 get_image \
  --camera-topic /usb_cam/image_raw \
  --quality 85 \
  --output /tmp/camera.jpg
```

返回示例：

```json
{
  "success": true,
  "message": "已获取摄像头图像",
  "local_path": "/tmp/camera.jpg",
  "width": 640,
  "height": 480,
  "quality": 85,
  "ts": 1774109535.33
}
```

---

## 调试建议

最小联通性检查：

```bash
python3 ~/.openclaw/skills/ROS-camera-ws/scripts/camera_ws_client.py \
  --host 127.0.0.1 --port 8766 \
  get_image --output /tmp/camera_check.jpg
```

如果失败，按这个顺序检查：

1. ROS 摄像头话题是否在发布：`ros2 topic list`
2. WebSocket 服务端是否已启动
3. 服务端 `--camera-topic` 是否和实际话题一致
4. 远端 IP / 端口是否正确
