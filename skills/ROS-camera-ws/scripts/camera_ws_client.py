#!/usr/bin/env python3
"""
Simple WebSocket client for grabbing one camera frame.
"""

import argparse
import asyncio
import base64
import json
import os

try:
    import websockets
except ImportError:
    websockets = None


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766


def _out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


async def _connect(host: str, port: int):
    if websockets is None:
        raise RuntimeError("缺少依赖 websockets，请先安装: pip3 install websockets")
    return await websockets.connect(f"ws://{host}:{port}", ping_interval=None, ping_timeout=None)


async def _recv_image_or_error(ws, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("未在规定时间内收到图像消息")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        if msg.get("type") == "image":
            return msg
        if msg.get("type") == "error":
            raise RuntimeError(msg.get("msg", "服务端返回错误"))


async def cmd_get_image(args):
    ws = await _connect(args.host, args.port)
    async with ws:
        await ws.send(
            json.dumps(
                {
                    "type": "get_image",
                    "camera_topic": args.camera_topic,
                    "quality": int(args.quality),
                }
            )
        )
        msg = await _recv_image_or_error(ws, timeout=12.0)

    img_b64 = msg.get("data")
    if not img_b64:
        raise RuntimeError("图像数据为空")

    parent = os.path.dirname(args.output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(base64.b64decode(img_b64))

    _out(
        {
            "success": True,
            "message": "已获取摄像头图像",
            "local_path": args.output,
            "width": msg.get("width"),
            "height": msg.get("height"),
            "quality": msg.get("quality"),
            "ts": msg.get("ts"),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ROS camera WebSocket client")
    root.add_argument("--host", default=DEFAULT_HOST)
    root.add_argument("--port", default=DEFAULT_PORT, type=int)
    sub = root.add_subparsers(dest="command", required=True)

    p = sub.add_parser("get_image", help="获取一帧摄像头图像")
    p.add_argument("--camera-topic", default="/image_raw")
    p.add_argument("--quality", default=85, type=int)
    p.add_argument("--output", default="/tmp/camera_ws.jpg")
    return root


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "get_image":
            asyncio.run(cmd_get_image(args))
    except TimeoutError as e:
        _out({"success": False, "error": str(e)})
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


if __name__ == "__main__":
    main()
