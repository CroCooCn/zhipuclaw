#!/usr/bin/env python3
"""
Simple ROS2 image topic to WebSocket bridge.
"""

import argparse
import asyncio
import base64
import json
import io
import threading
import time

import rclpy
from PIL import Image as PILImage
from rclpy.node import Node
from sensor_msgs.msg import Image

try:
    import websockets
except ImportError as e:
    raise RuntimeError("需要安装 websockets") from e


class CameraBridge(Node):
    def __init__(self, camera_topic: str):
        super().__init__("camera_ws_server")
        self.camera_topic = camera_topic
        self.latest_raw = None
        self.latest_encoding = None
        self.latest_width = None
        self.latest_height = None
        self.latest_ts = None
        self.quality = 85
        self.subscription = self.create_subscription(Image, camera_topic, self._on_image, 10)

    def _to_pil(self, msg: Image) -> PILImage:
        if msg.encoding == "rgb8":
            return PILImage.frombytes("RGB", (msg.width, msg.height), bytes(msg.data), "raw", "RGB")
        if msg.encoding == "bgr8":
            return PILImage.frombytes("RGB", (msg.width, msg.height), bytes(msg.data), "raw", "BGR")
        if msg.encoding == "mono8":
            return PILImage.frombytes("L", (msg.width, msg.height), bytes(msg.data), "raw", "L")
        raise RuntimeError(f"unsupported encoding: {msg.encoding}")

    def _on_image(self, msg: Image) -> None:
        try:
            self.latest_raw = bytes(msg.data)
            self.latest_encoding = msg.encoding
            self.latest_width = msg.width
            self.latest_height = msg.height
            self.latest_ts = time.time()
        except Exception as e:
            self.get_logger().warning(f"image encode failed: {e}")

    def get_image_payload(self, quality: int) -> dict:
        self.quality = int(quality)
        if not self.latest_raw:
            raise RuntimeError(f"话题 {self.camera_topic} 暂无图像")
        image = self._to_pil(
            type(
                "ImageMsg",
                (),
                {
                    "encoding": self.latest_encoding,
                    "width": self.latest_width,
                    "height": self.latest_height,
                    "data": self.latest_raw,
                },
            )()
        )
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=self.quality)
        jpeg_bytes = buf.getvalue()
        return {
            "type": "image",
            "data": base64.b64encode(jpeg_bytes).decode("ascii"),
            "width": self.latest_width,
            "height": self.latest_height,
            "quality": self.quality,
            "ts": self.latest_ts,
            "camera_topic": self.camera_topic,
        }


async def serve_ws(bridge: CameraBridge, host: str, port: int):
    async def handler(websocket):
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                if msg.get("type") != "get_image":
                    await websocket.send(json.dumps({"type": "error", "msg": "unsupported request type"}))
                    continue
                quality = int(msg.get("quality", 85))
                await websocket.send(json.dumps(bridge.get_image_payload(quality)))
            except Exception as e:
                await websocket.send(json.dumps({"type": "error", "msg": str(e)}))

    async with websockets.serve(handler, host, port, ping_interval=None, ping_timeout=None):
        await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser(description="ROS2 camera WebSocket server")
    parser.add_argument("--camera-topic", default="/image_raw")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8766, type=int)
    args = parser.parse_args()

    rclpy.init()
    bridge = CameraBridge(args.camera_topic)

    spin_thread = threading.Thread(target=rclpy.spin, args=(bridge,), daemon=True)
    spin_thread.start()

    try:
        asyncio.run(serve_ws(bridge, args.host, args.port))
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
