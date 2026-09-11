"""
myccusage_lib.web.server:
轻量嵌入式 Web 服务与 RESTful API:
- 基于 Python 标准库 http.server.ThreadingHTTPServer
- 提供 /api/agents, /api/data, /api/all, /api/refresh, /api/ping, /api/leave 接口
- 自动托管静态资源 (HTML5 SPA)
- 网页关闭心跳联动退出守护 (关闭网页自动安全退出后台)
- 零第三方外部依赖 (Zero pip dependencies)
"""

import os
import sys
import json
import time
import threading
import mimetypes
import webbrowser
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from ..core import (
    SUPPORTED_AGENTS,
    get_daily_data,
    get_session_data,
    get_all_agents_summary
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "static")

class DataCache:
    """
    轻量线程安全内存缓存池:
    - 用于 Web 服务运行期间对会话数据提供亚毫秒级（< 1ms）快速响应
    - 针对 (agent, mode, sort) 建立 30 秒短 TTL 缓存，消除反复切 Tab 与刷新的子进程开销
    - 当用户点击“刷新”或执行强制同步时，支持精准或全局失效
    """
    _lock = threading.Lock()
    _cache = {}
    TTL = 30.0

    @classmethod
    def get(cls, key):
        with cls._lock:
            if key in cls._cache:
                ts, val = cls._cache[key]
                if time.time() - ts < cls.TTL:
                    return val
                del cls._cache[key]
            return None

    @classmethod
    def set(cls, key, data):
        with cls._lock:
            cls._cache[key] = (time.time(), data)

    @classmethod
    def invalidate(cls, agent=None):
        with cls._lock:
            if agent is None or agent == "all":
                cls._cache.clear()
            else:
                to_del = [k for k in cls._cache if k[0] == agent]
                for k in to_del:
                    del cls._cache[k]

class ServerState:
    has_client_connected = False
    last_heartbeat_time = 0.0
    server = None
    shutdown_initiated = False
    HEARTBEAT_TIMEOUT = 6.0  # 6秒无心跳则判定所有网页已关闭

def watchdog_loop(server):
    while not ServerState.shutdown_initiated:
        time.sleep(1.0)
        if ServerState.has_client_connected:
            elapsed = time.time() - ServerState.last_heartbeat_time
            if elapsed > ServerState.HEARTBEAT_TIMEOUT:
                ServerState.shutdown_initiated = True
                print("\n🌐 检测到浏览器网页已关闭，后台服务已自动安全退出。")
                threading.Thread(target=server.shutdown, daemon=True).start()
                break

class DashboardRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 保持控制台清爽，仅记录非 200 请求或简要日志，过滤高频 ping 心跳
        if len(args) >= 2 and str(args[1]) not in ("200", "304"):
            sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 网页卸载离线通知 (Beacon API)
        if path == "/api/leave":
            self.send_json({"left": True})
            return

        if path == "/api/refresh":
            agent = query.get("agent", ["agy"])[0]
            if agent not in SUPPORTED_AGENTS and agent != "all":
                self.send_json({"error": f"不支持的 Agent: {agent}"}, 400)
                return
            try:
                # 显式刷新穿透失效对应缓存
                DataCache.invalidate(agent)
                if agent == "all":
                    # 重新拉取所有
                    for ag in SUPPORTED_AGENTS:
                        get_daily_data(ag, force_refresh=True)
                    res = get_all_agents_summary()
                    DataCache.set(("all", "summary", False), res)
                else:
                    res = get_daily_data(agent, force_refresh=True)
                    DataCache.set((agent, "daily", False), res)
                self.send_json({"success": True, "data": res})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_json({"error": "Not Found"}, 404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 心跳保活接口
        if path == "/api/ping":
            ServerState.has_client_connected = True
            ServerState.last_heartbeat_time = time.time()
            self.send_json({"pong": True})
            return

        # 1. API 路由
        if path == "/api/agents":
            agents_list = []
            for k, v in SUPPORTED_AGENTS.items():
                agents_list.append({
                    "id": k,
                    "name": v["name"],
                    "subcmd": v["subcmd"]
                })
            self.send_json({"agents": agents_list})
            return

        if path == "/api/all":
            try:
                cache_key = ("all", "summary", False)
                cached = DataCache.get(cache_key)
                if cached is not None:
                    self.send_json(cached)
                    return
                res = get_all_agents_summary()
                DataCache.set(cache_key, res)
                self.send_json(res)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        if path == "/api/data":
            agent = query.get("agent", ["agy"])[0]
            mode = query.get("mode", ["daily"])[0]
            sort_by_tokens = query.get("sort", ["time"])[0] == "tokens"

            if agent not in SUPPORTED_AGENTS:
                self.send_json({"error": f"不支持的 Agent: {agent}"}, 400)
                return

            cache_key = (agent, mode, sort_by_tokens)
            cached = DataCache.get(cache_key)
            if cached is not None:
                self.send_json(cached)
                return

            try:
                if mode == "session":
                    data = get_session_data(agent, sort_by_tokens=sort_by_tokens)
                else:
                    data = get_daily_data(agent, sort_by_tokens=sort_by_tokens)
                DataCache.set(cache_key, data)
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        # 2. 静态文件路由
        clean_path = path.lstrip("/")
        if not clean_path or clean_path == "index.html":
            file_path = os.path.join(STATIC_DIR, "index.html")
        else:
            file_path = os.path.join(STATIC_DIR, clean_path)

        if not os.path.exists(file_path) or os.path.isdir(file_path):
            file_path = os.path.join(STATIC_DIR, "index.html")

        if os.path.exists(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"
            if mime_type.startswith("text/") or mime_type in ("application/javascript", "application/json"):
                mime_type += "; charset=utf-8"

            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_json({"error": f"读取静态文件失败: {e}"}, 500)
        else:
            self.send_json({"error": "静态文件未找到"}, 404)

def start_server(port=8488, default_agent="agy", auto_open=True):
    # 端口自增重试（如果指定端口被占用）
    server_address = ("127.0.0.1", port)
    server = None
    for p in range(port, port + 10):
        try:
            server_address = ("127.0.0.1", p)
            server = ThreadingHTTPServer(server_address, DashboardRequestHandler)
            port = p
            break
        except OSError:
            continue

    if not server:
        print(f"❌ 无法绑定端口 {port} ~ {port + 9}，请使用 --port 指定其他可用端口", file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print("=" * 78)
    print("  🚀 myccusage Web Dashboard 已启动")
    print("=" * 78)
    print(f"  📡 本地地址: {url}")
    print(f"  📊 默认 Agent: {SUPPORTED_AGENTS.get(default_agent, {}).get('name', default_agent)}")
    print("  💡 按 Ctrl+C 停止服务，或直接关闭浏览器网页自动退出")
    print("=" * 78)

    ServerState.server = server
    ServerState.has_client_connected = False
    ServerState.last_heartbeat_time = time.time()
    ServerState.shutdown_initiated = False

    # 启动看门狗守护线程 (网页关闭联动安全退出)
    watchdog = threading.Thread(target=watchdog_loop, args=(server,), daemon=True)
    watchdog.start()

    # 启动后台异步预热线程 (预加载默认 Agent 会话数据入内存，实现首屏秒开体验)
    def warmup_worker():
        try:
            w_agent = default_agent or "agy"
            data = get_daily_data(w_agent)
            DataCache.set((w_agent, "daily", False), data)
        except Exception:
            pass

    threading.Thread(target=warmup_worker, daemon=True).start()

    if auto_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已安全停止 myccusage Web Dashboard 服务。")
    finally:
        server.server_close()
