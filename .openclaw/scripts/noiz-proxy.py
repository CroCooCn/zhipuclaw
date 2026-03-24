#!/usr/bin/env python3
"""OpenAI TTS to Noiz proxy server.

Listens on OpenAI-compatible endpoint and forwards to Noiz API.
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, Response, request, send_file

app = Flask(__name__)

# Global config
NOIZ_API_KEY: str = ""
NOIZ_BASE_URL: str = "https://noiz.ai/v1"
DEFAULT_VOICE_ID: str = "b4775100"  # 悦悦｜社交分享


def load_api_key() -> str:
    """Load Noiz API key from file or env."""
    key = os.environ.get("NOIZ_API_KEY", "")
    if key:
        return key

    key_path = Path.home() / ".config" / "noiz" / "api_key"
    if key_path.exists():
        return key_path.read_text().strip()

    return ""


def normalize_api_key(api_key: str) -> str:
    """Ensure API key is base64 encoded."""
    key = api_key.strip()
    if not key:
        return key
    try:
        decoded = base64.b64decode(key + "=" * (-len(key) % 4), validate=True)
        return key
    except Exception:
        return base64.b64encode(key.encode()).decode()


@app.route("/v1/audio/speech", methods=["POST"])
def text_to_speech():
    """OpenAI-compatible TTS endpoint."""
    try:
        data = request.get_json(force=True)
        text = data.get("input", "")
        voice = data.get("voice", DEFAULT_VOICE_ID)
        speed = data.get("speed", 1.0)
        model = data.get("model", "tts-1")

        if not text:
            return Response(
                json.dumps({"error": "input text is required"}),
                status=400,
                mimetype="application/json"
            )

        # Map OpenAI voices to Noiz voice IDs
        voice_map = {
            "alloy": "b4775100",      # 悦悦
            "echo": "77e15f2c",       # 婉青
            "fable": "ac09aeb4",      # 阿豪
            "onyx": "87cb2405",       # 建国
            "nova": "3b9f1e27",       # 小明
            "shimmer": "883b6b7c",    # The Mentor
        }
        voice_id = voice_map.get(voice, voice)

        # Call Noiz API
        resp = requests.post(
            f"{NOIZ_BASE_URL.rstrip('/')}/text-to-speech",
            headers={
                "Authorization": NOIZ_API_KEY,
            },
            data={
                "text": text,
                "voice_id": voice_id,
                "output_format": "opus",
                "speed": str(speed),
            },
            timeout=120,
        )

        if resp.status_code != 200:
            return Response(
                json.dumps({"error": f"Noiz API error: {resp.status_code}", "body": resp.text}),
                status=resp.status_code,
                mimetype="application/json"
            )

        # Return audio
        return Response(
            resp.content,
            mimetype="audio/ogg",
            headers={
                "Content-Type": "audio/ogg",
            }
        )

    except Exception as e:
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json"
        )


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


def main():
    global NOIZ_API_KEY, NOIZ_BASE_URL, DEFAULT_VOICE_ID

    parser = argparse.ArgumentParser(description="OpenAI TTS to Noiz proxy")
    parser.add_argument("--port", type=int, default=18790)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api-key", help="Noiz API key (or set NOIZ_API_KEY)")
    parser.add_argument("--base-url", default="https://noiz.ai/v1")
    parser.add_argument("--default-voice", default="b4775100")
    args = parser.parse_args()

    NOIZ_BASE_URL = args.base_url
    DEFAULT_VOICE_ID = args.default_voice

    if args.api_key:
        NOIZ_API_KEY = normalize_api_key(args.api_key)
    else:
        NOIZ_API_KEY = normalize_api_key(load_api_key())

    if not NOIZ_API_KEY:
        print("Error: No API key found. Set NOIZ_API_KEY or pass --api-key", file=sys.stderr)
        sys.exit(1)

    print(f"Starting Noiz proxy on {args.host}:{args.port}")
    print(f"Default voice: {DEFAULT_VOICE_ID}")
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
