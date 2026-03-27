#!/usr/bin/env python3
"""
visual_locator_server.py - 在 Mac 宿主机上运行的 HTTP 服务，
暴露本地 MLX VLM 推理能力，供 Docker 容器内的 visual_locator.py (remote 模式) 调用。

用法:
    # 启动服务（默认端口 8420）
    python visual_locator_server.py

    # 指定端口
    python visual_locator_server.py --port 9000

    # 指定模型
    python visual_locator_server.py --model mlx-community/Qwen2.5-VL-7B-Instruct-4bit

API:
    POST /locate
    Content-Type: application/json
    {
        "image_base64": "<base64 encoded png/jpg>",
        "description": "按钮描述...",
        "screen_width": 1080,   // 可选
        "screen_height": 2280,  // 可选
        "debug": false          // 可选
    }

    Response 200:
    {"x1": 120, "y1": 340, "x2": 280, "y2": 400, "center": [200, 370]}

    Response 404:
    {"error": "Element not found"}

    GET /health
    Response 200: {"status": "ok", "model": "..."}
"""

import argparse
import base64
import json
import os
import sys
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SKILL_DIR)

import visual_locator  # noqa: E402


class LocatorHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({
                "status": "ok",
                "model": visual_locator._loaded_model_path or "not loaded yet",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/locate":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)

        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "Invalid JSON"})
            return

        image_b64 = req.get("image_base64")
        description = req.get("description")
        if not image_b64 or not description:
            self._json_response(400, {"error": "Missing image_base64 or description"})
            return

        screen_w = req.get("screen_width")
        screen_h = req.get("screen_height")
        debug = req.get("debug", False)

        # 将 base64 图片写入临时文件
        try:
            img_bytes = base64.b64decode(image_b64)
        except Exception:
            self._json_response(400, {"error": "Invalid base64 image"})
            return

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(img_bytes)

            result = visual_locator.find_element(
                tmp_path,
                description,
                debug=debug,
                screen_width=screen_w,
                screen_height=screen_h,
                backend_override="local",
            )

            if result is None:
                self._json_response(404, {"error": "Element not found"})
            else:
                self._json_response(200, result)

        except Exception as e:
            self._json_response(500, {"error": str(e)})
        finally:
            os.unlink(tmp_path)

    def _json_response(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # 带时间戳的简洁日志
        sys.stderr.write(f"[locator-server] {args[0]}\n")


def main():
    parser = argparse.ArgumentParser(description="Visual Locator HTTP 服务（Mac 宿主机运行）")
    parser.add_argument("--port", type=int, default=8420, help="监听端口（默认 8420）")
    parser.add_argument("--model", type=str, default=None, help="指定模型路径")
    parser.add_argument("--preload", action="store_true", help="启动时预加载模型")
    args = parser.parse_args()

    if args.preload:
        print(f"[locator-server] 预加载模型...", file=sys.stderr)
        visual_locator._load_model(args.model)
        print(f"[locator-server] 模型加载完成: {visual_locator._loaded_model_path}", file=sys.stderr)

    server = HTTPServer(("0.0.0.0", args.port), LocatorHandler)
    print(f"[locator-server] 启动在 http://0.0.0.0:{args.port}", file=sys.stderr)
    print(f"[locator-server] Docker 容器内访问: http://host.docker.internal:{args.port}", file=sys.stderr)
    print(f"[locator-server] POST /locate  -  GET /health", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[locator-server] 已停止", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
