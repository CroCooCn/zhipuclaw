#!/usr/bin/env python3
"""
LIMO WebSocket client.

All command results are printed as JSON for easy agent parsing.
"""

import argparse
import asyncio
import base64
import json
import math
import os
import subprocess
from typing import Optional

try:
    import websockets
except ImportError:
    websockets = None


DEFAULT_WS_HOST = "192.168.0.5"
DEFAULT_WS_PORT = 8765
DEFAULT_SSH_HOST = "192.168.0.5"
DEFAULT_SSH_USER = "agilex"
DEFAULT_SSH_PASS = "agx"
REMOTE_PHOTO_CMD = "python3 /home/agilex/catkin_ws/take_photo.py"
REMOTE_PHOTO_PATH = "/home/agilex/Desktop/color_photo_fixed.jpg"
DEFAULT_START_POSE_FILE = "/tmp/limo_start_pose.json"

COLOR_PRESETS = {
    "red": [((0, 120, 70), (10, 255, 255)), ((170, 120, 70), (180, 255, 255))],
    "orange": [((8, 120, 70), (22, 255, 255))],
    "yellow": [((22, 100, 80), (35, 255, 255))],
    "green": [((35, 70, 60), (90, 255, 255))],
    "blue": [((95, 100, 60), (130, 255, 255))],
    "purple": [((130, 70, 60), (160, 255, 255))],
}
MOTION_MODES = {0: "差速(diff)", 1: "阿克曼(ackermann)", 2: "麦轮(mecanum)"}


def _out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_distance(value) -> float:
    distance = _safe_float(value)
    if distance is None or distance <= 0:
        return float("inf")
    return distance


def _normalize_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _extract_odom_pose(odom: dict) -> Optional[tuple[float, float, float]]:
    if not isinstance(odom, dict):
        return None
    x = _safe_float(odom.get("x"))
    y = _safe_float(odom.get("y"))
    yaw = _safe_float(odom.get("yaw"))
    if x is None or y is None or yaw is None:
        return None
    return x, y, yaw


def _calc_odom_delta(odom_before: dict, odom_after: dict) -> dict:
    before = _extract_odom_pose(odom_before)
    after = _extract_odom_pose(odom_after)
    if before is None or after is None:
        return {}
    dx = after[0] - before[0]
    dy = after[1] - before[1]
    raw_dyaw = after[2] - before[2]
    dyaw = raw_dyaw if abs(raw_dyaw) > (2 * math.pi + 0.1) else _normalize_angle(raw_dyaw)
    return {"dx": dx, "dy": dy, "distance": math.hypot(dx, dy), "dyaw": dyaw}


def _status_with_mode(status: dict) -> dict:
    if not isinstance(status, dict):
        return {"motion_mode_name": "未知"}
    return {**status, "motion_mode_name": MOTION_MODES.get(status.get("motion_mode", -1), "未知")}


def _save_json(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _append_trace_point(trace: list[dict], pose: tuple[float, float, float], min_dist: float = 0.02) -> list[dict]:
    point = {"x": pose[0], "y": pose[1], "yaw": pose[2], "frame": "odom"}
    if not trace:
        trace.append(point)
        return trace
    last = trace[-1]
    if math.hypot(point["x"] - last["x"], point["y"] - last["y"]) >= min_dist:
        trace.append(point)
    else:
        trace[-1] = point
    return trace


def _compress_trace(trace: list[dict], min_dist: float = 0.20) -> list[dict]:
    if not trace:
        return []
    result = [trace[0]]
    for point in trace[1:]:
        last = result[-1]
        if math.hypot(point["x"] - last["x"], point["y"] - last["y"]) >= min_dist:
            result.append(point)
    if result[-1] != trace[-1]:
        result.append(trace[-1])
    return result


def _load_vision_modules():
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise RuntimeError("需要安装 opencv-python 和 numpy") from e
    return cv2, np


def _parse_hsv_triplet(text: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        raise ValueError("HSV 参数格式必须是 H,S,V，例如 100,120,60")
    values = tuple(int(p) for p in parts)
    if not (0 <= values[0] <= 180 and 0 <= values[1] <= 255 and 0 <= values[2] <= 255):
        raise ValueError("HSV 范围非法：H 需在 0-180，S/V 需在 0-255")
    return values


def _resolve_color_ranges(args):
    if args.hsv_lower or args.hsv_upper:
        if not (args.hsv_lower and args.hsv_upper):
            raise ValueError("自定义 HSV 需要同时提供 --hsv-lower 和 --hsv-upper")
        return [(_parse_hsv_triplet(args.hsv_lower), _parse_hsv_triplet(args.hsv_upper))]
    color = args.color.lower()
    if color not in COLOR_PRESETS:
        raise ValueError(f"不支持的颜色 '{args.color}'")
    return COLOR_PRESETS[color]


def _decode_bgr_image(img_b64: str):
    cv2, np = _load_vision_modules()
    img_bytes = base64.b64decode(img_b64)
    image = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("无法解码摄像头图像")
    return image


def _detect_color_target(frame_bgr, color_ranges, min_area: int, min_visible_area: int) -> dict:
    cv2, np = _load_vision_modules()
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in color_ranges:
        mask |= cv2.inRange(np.array(hsv), np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))

    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"found": False}

    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    h, w = frame_bgr.shape[:2]
    area_ratio = area / max(1.0, float(w * h))
    if area < float(min_visible_area):
        return {"found": False, "area": area, "area_ratio": area_ratio}

    x, y, bw, bh = cv2.boundingRect(contour)
    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        center_x = x + bw / 2.0
        center_y = y + bh / 2.0
    else:
        center_x = moments["m10"] / moments["m00"]
        center_y = moments["m01"] / moments["m00"]

    return {
        "found": True,
        "center_x": center_x,
        "center_y": center_y,
        "center_error": (center_x - w / 2.0) / max(w / 2.0, 1.0),
        "area": area,
        "area_ratio": area_ratio,
        "bbox": {"x": int(x), "y": int(y), "w": int(bw), "h": int(bh)},
        "image_size": {"width": w, "height": h},
        "meets_min_area": area >= float(min_area),
    }


def _maybe_write_debug_frame(frame_bgr, detection: dict, output_path: str) -> None:
    if not output_path:
        return
    cv2, _ = _load_vision_modules()
    annotated = frame_bgr.copy()
    if detection.get("found"):
        bbox = detection["bbox"]
        cv2.rectangle(
            annotated,
            (bbox["x"], bbox["y"]),
            (bbox["x"] + bbox["w"], bbox["y"] + bbox["h"]),
            (0, 255, 0),
            2,
        )
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    cv2.imwrite(output_path, annotated)


async def _connect(host: str, port: int):
    if websockets is None:
        raise RuntimeError("缺少依赖 websockets，请先安装: pip3 install websockets")
    # The robot server may stay busy during long-running control loops, so keep
    # the connection tolerant to delayed heartbeats.
    return await websockets.connect(f"ws://{host}:{port}", ping_interval=None, ping_timeout=None)


async def _send_cmd_vel(ws, linear_x: float = 0.0, angular_z: float = 0.0, linear_y: float = 0.0) -> None:
    await ws.send(
        json.dumps(
            {
                "type": "cmd_vel",
                "linear_x": linear_x,
                "angular_z": angular_z,
                "linear_y": linear_y,
            }
        )
    )


async def _recv_until(ws, *, timeout: float, accepted_types: tuple[str, ...]) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("等待消息超时")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        msg_type = msg.get("type")
        if msg_type == "error":
            raise RuntimeError(msg.get("msg", "服务端返回错误"))
        if msg_type in accepted_types:
            return msg


async def _recv_state(ws, timeout: float = 3.0) -> dict:
    return (await _recv_until(ws, timeout=timeout, accepted_types=("state",)))["data"]


async def _request_image(ws, quality: int, camera_topic: str) -> dict:
    await ws.send(json.dumps({"type": "get_image", "quality": int(quality), "camera_topic": camera_topic}))
    return await _recv_until(ws, timeout=12.0, accepted_types=("image",))


async def _drive_for(
    ws,
    *,
    linear_x: float,
    angular_z: float,
    linear_y: float,
    duration: float,
    interval: float = 0.05,
) -> None:
    if duration <= 0:
        return
    loop = asyncio.get_running_loop()
    end_time = loop.time() + duration
    while loop.time() < end_time:
        await _send_cmd_vel(ws, linear_x=linear_x, angular_z=angular_z, linear_y=linear_y)
        await asyncio.sleep(min(interval, max(0.0, end_time - loop.time())))


async def _spin_for_turns(ws, angular_z: float, turns: float, interval: float) -> float:
    if abs(angular_z) < 1e-6 or turns <= 0:
        return 0.0
    loop = asyncio.get_running_loop()
    start = loop.time()
    duration = (2.0 * math.pi * turns / abs(angular_z)) * 1.15
    await _drive_for(
        ws,
        linear_x=0.0,
        angular_z=angular_z,
        linear_y=0.0,
        duration=duration,
        interval=max(0.02, interval),
    )
    await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
    return loop.time() - start


def _parse_waypoints(text: str) -> list[tuple[float, float, float]]:
    points = []
    for item in text.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(",")]
        if len(parts) != 3:
            raise ValueError("Each waypoint must be x,y,yaw")
        points.append(tuple(map(float, parts)))
    if not points:
        raise ValueError("No valid waypoint found")
    return points


async def _navigate_request(ws, payload: dict, timeout: float) -> dict:
    await ws.send(json.dumps(payload))
    return await _recv_until(ws, timeout=timeout, accepted_types=("nav_result",))


async def _refine_to_pose(args, x: float, y: float, yaw: float) -> dict:
    last_pose = None
    final_dist = None
    final_yaw_err = None
    try:
        ws = await _connect(args.host, args.port)
        async with ws:
            for step in range(1, max(1, args.refine_max_steps) + 1):
                state = await _recv_state(ws, timeout=3.0)
                pose = _extract_odom_pose(state.get("odom", {}))
                if pose is None:
                    await _drive_for(
                        ws,
                        linear_x=0.0,
                        angular_z=0.0,
                        linear_y=0.0,
                        duration=args.refine_step_duration,
                    )
                    continue

                last_pose = {"x": pose[0], "y": pose[1], "yaw": pose[2]}
                dx = x - pose[0]
                dy = y - pose[1]
                dist = math.hypot(dx, dy)
                yaw_err = _normalize_angle(yaw - pose[2])
                final_dist = dist
                final_yaw_err = yaw_err

                if dist <= args.refine_pos_tol and abs(yaw_err) <= args.refine_yaw_tol:
                    await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
                    return {
                        "success": True,
                        "steps": step,
                        "distance_error": dist,
                        "yaw_error": yaw_err,
                        "last_pose": last_pose,
                    }

                heading = math.atan2(dy, dx)
                heading_err = _normalize_angle(heading - pose[2])
                angular_z = _clamp(
                    args.refine_heading_kp * heading_err if dist > args.refine_pos_tol else args.refine_yaw_kp * yaw_err,
                    -args.refine_max_angular_z,
                    args.refine_max_angular_z,
                )

                if dist > args.refine_pos_tol and abs(heading_err) <= args.refine_heading_tolerance:
                    linear_x = _clamp(
                        args.refine_linear_kp * dist,
                        args.refine_min_linear_x,
                        args.refine_max_linear_x,
                    )
                else:
                    linear_x = 0.0

                await _drive_for(
                    ws,
                    linear_x=linear_x,
                    angular_z=angular_z,
                    linear_y=0.0,
                    duration=args.refine_step_duration,
                )

            await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
            return {
                "success": False,
                "steps": args.refine_max_steps,
                "distance_error": final_dist,
                "yaw_error": final_yaw_err,
                "last_pose": last_pose,
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "distance_error": final_dist,
            "yaw_error": final_yaw_err,
            "last_pose": last_pose,
        }


async def _return_to_pose(args, x: float, y: float, yaw: float, frame: Optional[str] = None) -> dict:
    target_yaw = _normalize_angle(yaw + args.final_yaw_offset)
    try:
        refine_result = await _refine_to_pose(args, x, y, target_yaw)
        if refine_result.get("success"):
            return {
                "success": True,
                "message": "已返回起点",
                "target": {"x": x, "y": y, "yaw": target_yaw},
                "frame": frame or args.frame,
                "refine": refine_result,
            }
        return {
            "success": False,
            "error": refine_result.get("error", "返回起点失败"),
            "target": {"x": x, "y": y, "yaw": target_yaw},
            "frame": frame or args.frame,
            "refine": refine_result,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _return_along_trace(args, trace: list[dict]) -> dict:
    if len(trace) < 2:
        return {"success": False, "error": "轨迹点不足，回退到单点返程", "fallback": True}
    waypoints = [
        {"x": p["x"], "y": p["y"], "yaw": p.get("yaw", 0.0)}
        for p in reversed(_compress_trace(trace)[:-1])
    ]
    if not waypoints:
        return {"success": False, "error": "轨迹点不足，回退到单点返程", "fallback": True}
    try:
        ws = await _connect(args.host, args.port)
        async with ws:
            nav_result = await _navigate_request(
                ws,
                {"type": "navigate", "frame": "odom", "timeout": args.timeout, "waypoints": waypoints},
                timeout=max(10.0, args.timeout * max(1, len(waypoints)) + 5.0),
            )
        if not nav_result.get("success"):
            return {
                "success": False,
                "error": nav_result.get("error", "原路返回失败"),
                "status": nav_result.get("status"),
                "failed_index": nav_result.get("failed_index"),
            }
        final = waypoints[-1]
        refine = await _refine_to_pose(args, final["x"], final["y"], final["yaw"])
        return {
            "success": refine.get("success", False),
            "message": "已按原轨迹返回",
            "points": len(trace),
            "waypoints": len(waypoints),
            "refine": refine,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def cmd_get_state(args):
    ws = await _connect(args.host, args.port)
    async with ws:
        state = await _recv_state(ws, timeout=5.0)
    _out(
        {
            "success": True,
            "odom": state.get("odom", {}),
            "imu": state.get("imu", {}),
            "scan": state.get("scan", {}),
            "status": _status_with_mode(state.get("status", {})),
            "connected_clients": state.get("connected_clients"),
        }
    )


async def cmd_move(args):
    ws = await _connect(args.host, args.port)
    async with ws:
        try:
            state_before = await _recv_state(ws, timeout=3.0)
        except TimeoutError:
            state_before = {}

        await _drive_for(
            ws,
            linear_x=args.linear_x,
            angular_z=args.angular_z,
            linear_y=args.linear_y,
            duration=args.duration,
        )
        await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
        await asyncio.sleep(0.1)

        try:
            state_after = await _recv_state(ws, timeout=3.0)
        except TimeoutError:
            state_after = {}

    odom_delta = _calc_odom_delta(state_before.get("odom", {}), state_after.get("odom", {}))
    if not args.no_verify_odom:
        cmd_linear = abs(args.linear_x) > 1e-6 or abs(args.linear_y) > 1e-6
        cmd_angular = abs(args.angular_z) > 1e-6
        linear_ok = (not cmd_linear) or odom_delta.get("distance", 0.0) >= args.min_odom_distance
        angular_ok = (not cmd_angular) or abs(odom_delta.get("dyaw", 0.0)) >= args.min_odom_yaw
        if args.duration > 0 and (cmd_linear or cmd_angular) and not (linear_ok and angular_ok):
            _out(
                {
                    "success": False,
                    "error": "运动指令已发送，但里程计变化很小，疑似底盘未实际执行",
                    "command": vars(args),
                    "odom_delta": odom_delta,
                    "odom_before": state_before.get("odom", {}),
                    "odom_after": state_after.get("odom", {}),
                }
            )
            return

    _out(
        {
            "success": True,
            "command": {
                "linear_x": args.linear_x,
                "angular_z": args.angular_z,
                "linear_y": args.linear_y,
                "duration": args.duration,
            },
            "odom_before": state_before.get("odom", {}),
            "odom_after": state_after.get("odom", {}),
            "odom_delta": odom_delta,
            "status_before": _status_with_mode(state_before.get("status", {})),
            "status_after": _status_with_mode(state_after.get("status", {})),
        }
    )


async def cmd_stop(args):
    ws = await _connect(args.host, args.port)
    async with ws:
        await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
        await asyncio.sleep(0.1)
    _out({"success": True, "message": "已发送停车指令"})


async def cmd_get_image(args):
    ws = await _connect(args.host, args.port)
    async with ws:
        msg = await _request_image(ws, quality=args.quality, camera_topic=args.camera_topic)
    parent = os.path.dirname(args.output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(base64.b64decode(msg.get("data", "")))
    _out(
        {
            "success": True,
            "message": "已通过 WebSocket 获取图像",
            "local_path": args.output,
            "width": msg.get("width"),
            "height": msg.get("height"),
            "quality": msg.get("quality"),
            "ts": msg.get("ts"),
        }
    )


async def cmd_approach_color(args):
    color_ranges = _resolve_color_ranges(args)
    start_pose = None
    last_detection = None
    last_scan = {}
    last_motion = {"linear_x": 0.0, "angular_z": 0.0, "linear_y": 0.0}
    first_odom = {}
    last_odom = {}
    consecutive_reach_hits = 0
    trace = []

    ws = await _connect(args.host, args.port)
    async with ws:
        for iteration in range(1, args.max_steps + 1):
            state = await _recv_state(ws, timeout=3.0)
            last_scan = state.get("scan", {})
            state_odom = state.get("odom", {})
            if not first_odom and isinstance(state_odom, dict):
                first_odom = state_odom
            if isinstance(state_odom, dict):
                last_odom = state_odom

            if args.record_start_pose and start_pose is None:
                pose = _extract_odom_pose(state_odom)
                if pose is not None:
                    start_pose = {"x": pose[0], "y": pose[1], "yaw": pose[2], "frame": "odom"}
                    trace = _append_trace_point(trace, pose)
                    _save_json(args.start_pose_file, {**start_pose, "source": "approach_color", "trace": trace})
            elif args.record_start_pose:
                pose = _extract_odom_pose(state_odom)
                if pose is not None:
                    trace = _append_trace_point(trace, pose)
                    if start_pose is not None:
                        _save_json(args.start_pose_file, {**start_pose, "source": "approach_color", "trace": trace})

            front_distance = _safe_distance(
                last_scan.get("front_distance_0deg")
                if args.front_basis_deg == 0
                else last_scan.get("front_distance_180deg")
            )
            if math.isinf(front_distance):
                front_distance = _safe_distance(last_scan.get("front_distance"))

            if front_distance <= args.emergency_stop_distance:
                await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
                _out(
                    {
                        "success": True,
                        "reached": False,
                        "stop_reason": "emergency_front_obstacle",
                        "iterations": iteration,
                        "scan": last_scan,
                        "last_detection": last_detection,
                        "last_motion": last_motion,
                    }
                )
                return

            image_msg = await _request_image(ws, quality=args.quality, camera_topic=args.camera_topic)
            frame_bgr = _decode_bgr_image(image_msg.get("data", ""))
            detection = _detect_color_target(
                frame_bgr,
                color_ranges,
                args.min_area,
                args.min_visible_area,
            )
            last_detection = detection
            _maybe_write_debug_frame(frame_bgr, detection, args.debug_output)

            linear_x = 0.0
            angular_z = 0.0
            reached = False

            if detection.get("found"):
                error_x = float(detection.get("center_error", 0.0))
                area = float(detection.get("area", 0.0))
                area_ratio = float(detection.get("area_ratio", 0.0))
                center_ok = abs(error_x) <= args.stop_center_tolerance
                distance_ok = front_distance <= args.stop_distance
                area_ok = area >= float(args.stop_min_area) or area_ratio >= args.stop_area_ratio
                if math.isinf(front_distance) or front_distance > args.stop_area_max_distance:
                    area_ok = False

                reached_candidate = (distance_ok or area_ok) and center_ok
                if reached_candidate:
                    consecutive_reach_hits += 1
                    reached = consecutive_reach_hits >= args.stop_confirm_frames
                else:
                    consecutive_reach_hits = 0
                    if not args.force_no_spin:
                        angular_z = _clamp(-args.angular_gain * error_x, -args.max_angular_z, args.max_angular_z)
                    if abs(error_x) <= args.center_tolerance:
                        linear_x = args.linear_x if area >= float(args.min_area) else args.weak_linear_x
                    else:
                        linear_x = args.slow_linear_x if abs(error_x) <= args.weak_center_tolerance else 0.0
            elif not args.force_no_spin:
                consecutive_reach_hits = 0
                angular_z = args.search_angular_z
            else:
                consecutive_reach_hits = 0

            if front_distance <= args.slow_stop_distance:
                linear_x = min(linear_x, args.slow_linear_x)

            if reached:
                spin_duration = 0.0
                if args.reach_spin_turns > 0:
                    spin_duration = await _spin_for_turns(
                        ws,
                        angular_z=args.reach_spin_angular_z,
                        turns=args.reach_spin_turns,
                        interval=args.reach_spin_interval,
                    )
                await _send_cmd_vel(ws, 0.0, 0.0, 0.0)

                return_result = None
                if args.return_to_start and start_pose is not None:
                    return_result = await _return_to_pose(
                        args,
                        x=start_pose["x"],
                        y=start_pose["y"],
                        yaw=start_pose["yaw"],
                        frame=start_pose["frame"],
                    )

                _out(
                    {
                        "success": return_result is None or return_result.get("success", False),
                        "reached": True,
                        "stop_reason": "target_reached",
                        "iterations": iteration,
                        "scan": last_scan,
                        "selected_front_distance": None if math.isinf(front_distance) else front_distance,
                        "last_detection": detection,
                        "last_motion": {"linear_x": 0.0, "angular_z": 0.0, "linear_y": 0.0},
                        "spin_duration": spin_duration,
                        "return_to_start": args.return_to_start,
                        "return_result": return_result,
                        "start_pose": start_pose,
                        "trace_points": len(trace),
                        "consecutive_reach_hits": consecutive_reach_hits,
                        "odom_delta": _calc_odom_delta(first_odom, last_odom),
                    }
                )
                return

            last_motion = {"linear_x": linear_x, "angular_z": angular_z, "linear_y": 0.0}
            await _drive_for(
                ws,
                linear_x=linear_x,
                angular_z=angular_z,
                linear_y=0.0,
                duration=args.step_duration,
            )

        await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
        _out(
            {
                "success": False,
                "error": "在最大迭代次数内未靠近目标",
                "scan": last_scan,
                "last_detection": last_detection,
                "last_motion": last_motion,
                "consecutive_reach_hits": consecutive_reach_hits,
                "odom_delta": _calc_odom_delta(first_odom, last_odom),
            }
        )


async def cmd_spin_in_place(args):
    ws = await _connect(args.host, args.port)
    async with ws:
        duration = await _spin_for_turns(ws, angular_z=args.angular_z, turns=args.turns, interval=args.interval)
    _out(
        {
            "success": True,
            "message": "原地转圈完成",
            "angular_z": args.angular_z,
            "turns": args.turns,
            "duration": duration,
        }
    )


async def cmd_return_to_start_pose(args):
    if args.x is not None and args.y is not None:
        x, y, yaw, frame = args.x, args.y, args.yaw, args.frame
        trace = []
    else:
        data = _load_json(args.start_pose_file)
        x = data.get("x")
        y = data.get("y")
        yaw = data.get("yaw", 0.0)
        frame = data.get("frame", args.frame)
        trace = data.get("trace", [])
    if x is None or y is None:
        _out({"success": False, "error": "请提供 --x --y 或有效的 --start-pose-file"})
        return
    result = await _return_along_trace(args, trace) if trace else None
    if result is None or result.get("fallback"):
        result = await _return_to_pose(args, x=x, y=y, yaw=yaw, frame=frame)
    if result.get("success"):
        _out({"success": True, "message": "已返回起点", "result": result})
    else:
        _out({"success": False, "error": result.get("error", "返回起点失败"), "result": result})


async def cmd_navigate(args):
    if args.waypoints:
        goals = _parse_waypoints(args.waypoints)
        payload = {
            "type": "navigate",
            "frame": args.frame,
            "timeout": args.timeout,
            "waypoints": [{"x": x, "y": y, "yaw": yaw} for x, y, yaw in goals],
        }
        wait_timeout = max(10.0, args.timeout * len(goals) + 5.0)
    else:
        if args.x is None or args.y is None:
            raise ValueError("请提供 --x --y，或使用 --waypoints")
        payload = {
            "type": "navigate",
            "frame": args.frame,
            "timeout": args.timeout,
            "x": args.x,
            "y": args.y,
            "yaw": args.yaw,
        }
        wait_timeout = max(10.0, args.timeout + 5.0)

    ws = await _connect(args.host, args.port)
    async with ws:
        result = await _navigate_request(ws, payload, timeout=wait_timeout)

    if result.get("success"):
        _out(
            {
                "success": True,
                "message": result.get("message", "导航完成"),
                "frame": result.get("frame", args.frame),
                "reached": result.get("reached"),
                "total": result.get("total"),
            }
        )
    else:
        _out(
            {
                "success": False,
                "error": result.get("error", "导航失败"),
                "reached": result.get("reached"),
                "total": result.get("total"),
                "failed_index": result.get("failed_index"),
                "status": result.get("status"),
            }
        )


def cmd_take_photo(args):
    ssh_target = f"{args.ssh_user}@{args.ssh_host}"
    ssh_cmd = [
        "sshpass",
        "-p",
        args.ssh_pass,
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        ssh_target,
        REMOTE_PHOTO_CMD,
    ]
    scp_cmd = [
        "sshpass",
        "-p",
        args.ssh_pass,
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        f"{ssh_target}:{REMOTE_PHOTO_PATH}",
        args.output,
    ]
    try:
        shot = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=20)
        if shot.returncode != 0:
            _out({"success": False, "error": f"拍照命令失败: {shot.stderr.strip()}"})
            return
        copy = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=20)
        if copy.returncode != 0:
            _out({"success": False, "error": f"图片传输失败: {copy.stderr.strip()}"})
            return
        _out({"success": True, "local_path": args.output, "remote_path": REMOTE_PHOTO_PATH})
    except FileNotFoundError:
        _out({"success": False, "error": "未找到 sshpass，请先安装 sshpass"})
    except subprocess.TimeoutExpired:
        _out({"success": False, "error": "SSH/SCP 操作超时"})


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="LIMO 机器人 AI 工具", formatter_class=argparse.RawDescriptionHelpFormatter)
    root.add_argument("--host", default=DEFAULT_WS_HOST, help=f"WebSocket 服务器 IP（默认 {DEFAULT_WS_HOST}）")
    root.add_argument("--port", default=DEFAULT_WS_PORT, type=int, help=f"WebSocket 端口（默认 {DEFAULT_WS_PORT}）")

    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("get_state", help="获取机器人当前状态快照")

    p_move = sub.add_parser("move", help="控制机器人运动指定时间后停车")
    p_move.add_argument("--linear-x", default=0.0, type=float)
    p_move.add_argument("--angular-z", default=0.0, type=float)
    p_move.add_argument("--linear-y", default=0.0, type=float)
    p_move.add_argument("--duration", default=1.0, type=float)
    p_move.add_argument("--no-verify-odom", action="store_true")
    p_move.add_argument("--min-odom-distance", default=0.005, type=float)
    p_move.add_argument("--min-odom-yaw", default=0.01, type=float)

    sub.add_parser("stop", help="立即停止机器人")

    p_image = sub.add_parser("get_image", help="通过 WebSocket 获取一帧摄像头图像")
    p_image.add_argument("--output", default="/tmp/limo_ws_image.jpg")
    p_image.add_argument("--quality", default=85, type=int)
    p_image.add_argument("--camera-topic", default="/usb_cam/image_raw")

    p_approach = sub.add_parser("approach_color", help="根据摄像头画面靠近指定颜色目标")
    p_approach.add_argument("--color", default="blue")
    p_approach.add_argument("--camera-topic", default="/usb_cam/image_raw")
    p_approach.add_argument("--quality", default=80, type=int)
    p_approach.add_argument("--linear-x", default=0.18, type=float)
    p_approach.add_argument("--slow-linear-x", default=0.08, type=float)
    p_approach.add_argument("--weak-linear-x", default=0.06, type=float)
    p_approach.add_argument("--search-angular-z", default=0.45, type=float)
    p_approach.add_argument("--max-angular-z", default=0.8, type=float)
    p_approach.add_argument("--angular-gain", default=0.9, type=float)
    p_approach.add_argument("--center-tolerance", default=0.18, type=float)
    p_approach.add_argument("--weak-center-tolerance", default=0.30, type=float)
    p_approach.add_argument("--min-area", default=180, type=int)
    p_approach.add_argument("--min-visible-area", default=60, type=int)
    p_approach.add_argument("--stop-min-area", default=800, type=int)
    p_approach.add_argument("--stop-area-ratio", default=0.02, type=float)
    p_approach.add_argument("--stop-distance", default=0.23, type=float)
    p_approach.add_argument("--stop-area-max-distance", default=0.30, type=float)
    p_approach.add_argument("--slow-stop-distance", default=0.34, type=float)
    p_approach.add_argument("--emergency-stop-distance", default=0.18, type=float)
    p_approach.add_argument("--stop-center-tolerance", default=0.24, type=float)
    p_approach.add_argument("--stop-confirm-frames", default=3, type=int)
    p_approach.add_argument("--front-basis-deg", default=0, choices=[0, 180], type=int)
    p_approach.add_argument("--step-duration", default=0.25, type=float)
    p_approach.add_argument("--max-steps", default=220, type=int)
    p_approach.add_argument("--record-start-pose", action="store_true", default=True)
    p_approach.add_argument("--no-record-start-pose", action="store_true")
    p_approach.add_argument("--start-pose-file", default=DEFAULT_START_POSE_FILE)
    p_approach.add_argument("--return-to-start", action="store_true")
    p_approach.add_argument("--force-no-spin", action="store_true")
    p_approach.add_argument("--reach-spin-turns", default=0.0, type=float)
    p_approach.add_argument("--reach-spin-angular-z", default=0.7, type=float)
    p_approach.add_argument("--reach-spin-interval", default=0.05, type=float)
    p_approach.add_argument("--hsv-lower", default="")
    p_approach.add_argument("--hsv-upper", default="")
    p_approach.add_argument("--debug-output", default="")

    p_spin = sub.add_parser("spin_in_place", help="原地转圈指定圈数")
    p_spin.add_argument("--angular-z", default=0.7, type=float)
    p_spin.add_argument("--turns", default=2.0, type=float)
    p_spin.add_argument("--interval", default=0.05, type=float)

    p_return = sub.add_parser("return_to_start_pose", help="返回到指定的起点坐标")
    p_return.add_argument("--x", type=float)
    p_return.add_argument("--y", type=float)
    p_return.add_argument("--yaw", default=0.0, type=float)
    p_return.add_argument("--start-pose-file", default=DEFAULT_START_POSE_FILE)
    p_return.add_argument("--frame", default="odom")
    p_return.add_argument("--timeout", default=120.0, type=float)
    p_return.add_argument("--final-yaw-offset", default=0.0, type=float)
    p_return.add_argument("--refine-after-nav", action="store_true", default=True)
    p_return.add_argument("--no-refine-after-nav", action="store_true")
    p_return.add_argument("--refine-pos-tol", default=0.04, type=float)
    p_return.add_argument("--refine-yaw-tol", default=0.10, type=float)
    p_return.add_argument("--refine-max-steps", default=320, type=int)
    p_return.add_argument("--refine-step-duration", default=0.25, type=float)
    p_return.add_argument("--refine-linear-kp", default=1.2, type=float)
    p_return.add_argument("--refine-heading-kp", default=2.0, type=float)
    p_return.add_argument("--refine-yaw-kp", default=1.6, type=float)
    p_return.add_argument("--refine-heading-tolerance", default=0.60, type=float)
    p_return.add_argument("--refine-min-linear-x", default=0.08, type=float)
    p_return.add_argument("--refine-max-linear-x", default=0.45, type=float)
    p_return.add_argument("--refine-max-angular-z", default=0.8, type=float)

    p_nav = sub.add_parser("navigate", help="通过 move_base 执行单点或多点导航")
    p_nav.add_argument("--frame", default="map")
    p_nav.add_argument("--timeout", default=120.0, type=float)
    p_nav.add_argument("--x", type=float)
    p_nav.add_argument("--y", type=float)
    p_nav.add_argument("--yaw", default=0.0, type=float)
    p_nav.add_argument("--waypoints", type=str, default="")

    p_photo = sub.add_parser("take_photo", help="拍照并传输到本地")
    p_photo.add_argument("--output", default="/tmp/limo_photo.jpg")
    p_photo.add_argument("--ssh-host", default=DEFAULT_SSH_HOST)
    p_photo.add_argument("--ssh-user", default=DEFAULT_SSH_USER)
    p_photo.add_argument("--ssh-pass", default=DEFAULT_SSH_PASS)
    return root


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "no_record_start_pose", False):
        args.record_start_pose = False
    if getattr(args, "no_refine_after_nav", False):
        args.refine_after_nav = False

    try:
        if args.command == "get_state":
            asyncio.run(cmd_get_state(args))
        elif args.command == "move":
            asyncio.run(cmd_move(args))
        elif args.command == "stop":
            asyncio.run(cmd_stop(args))
        elif args.command == "get_image":
            asyncio.run(cmd_get_image(args))
        elif args.command == "approach_color":
            asyncio.run(cmd_approach_color(args))
        elif args.command == "spin_in_place":
            asyncio.run(cmd_spin_in_place(args))
        elif args.command == "return_to_start_pose":
            asyncio.run(cmd_return_to_start_pose(args))
        elif args.command == "navigate":
            asyncio.run(cmd_navigate(args))
        elif args.command == "take_photo":
            cmd_take_photo(args)
    except TimeoutError as e:
        _out({"success": False, "error": str(e)})
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


if __name__ == "__main__":
    main()
