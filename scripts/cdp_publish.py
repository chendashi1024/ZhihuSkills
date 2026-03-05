"""
基于 CDP 的知乎文章发布器。

通过 Chrome DevTools Protocol 连接 Chrome 实例，自动化在知乎专栏发布文章。

CLI 用法:
    python cdp_publish.py [--host HOST] [--port PORT] check-login [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] fill --title "标题" --content "正文" [--images img1.jpg] [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] publish --title "标题" --content "正文" [--images img1.jpg] [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] click-publish [--headless] [--account NAME] [--reuse-existing-tab]

    # 账号管理
    python cdp_publish.py login [--account NAME]
    python cdp_publish.py re-login [--account NAME]
    python cdp_publish.py switch-account [--account NAME]
    python cdp_publish.py list-accounts
    python cdp_publish.py add-account NAME [--alias ALIAS]
    python cdp_publish.py remove-account NAME
    python cdp_publish.py set-default-account NAME

Library 用法:
    from cdp_publish import ZhihuPublisher

    publisher = ZhihuPublisher()
    publisher.connect()
    publisher.check_login()
    publisher.publish(
        title="文章标题",
        content="文章正文",
        image_paths=["/path/to/img1.jpg"],  # 可选
    )
"""

import json
import os
import random
import time
import sys
from typing import Any

# 将 scripts 目录加入 path，支持兄弟模块导入
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Windows 控制台 UTF-8 输出
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
import websockets.sync.client as ws_client
from run_lock import SingleInstanceError, single_instance

# ---------------------------------------------------------------------------
# 配置 - 集中管理选择器和 URL，便于维护
# ---------------------------------------------------------------------------

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

# 知乎 URL
ZHIHU_WRITE_URL = "https://zhuanlan.zhihu.com/write"
ZHIHU_HOME_URL = "https://www.zhihu.com"

# 知乎写文章页 DOM 选择器
SELECTORS = {
    # 标题输入框 - textarea
    "title_input": 'textarea[placeholder*="请输入标题"]',
    "title_input_alt": 'textarea.Input',
    # 正文编辑器 - Draft.js contenteditable div
    "content_editor": '.public-DraftEditor-content[contenteditable="true"]',
    "content_editor_alt": '.public-DraftEditor-content',
    # 图片上传 - 正文内插图的 file input
    "upload_input": 'input[type="file"][accept*="image/webp"]',
    "upload_input_alt": 'input[type="file"][accept*="image"]',
    # 封面上传
    "cover_upload_input": 'input.UploadPicture-input[accept=".jpeg, .jpg, .png"]',
    # 发布按钮
    "publish_button_text": "发布",
}

# 时间参数
PAGE_LOAD_WAIT = 3  # 导航后等待秒数
UPLOAD_WAIT = 6  # 图片上传后等待秒数
ACTION_INTERVAL = 1  # 操作间隔秒数
MAX_TIMING_JITTER_RATIO = 0.7
DEFAULT_LOGIN_CACHE_TTL_HOURS = 12.0
LOGIN_CACHE_FILE = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "tmp", "login_status_cache.json")
)


def _normalize_timing_jitter(value: float) -> float:
    """将 timing jitter 限制在安全范围内。"""
    return max(0.0, min(MAX_TIMING_JITTER_RATIO, value))


def _is_local_host(host: str) -> bool:
    """判断 host 是否指向本机。"""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _resolve_account_name(account_name: str | None) -> str:
    """解析显式或默认账号名称，用于登录缓存作用域。"""
    if account_name and account_name.strip():
        return account_name.strip()
    try:
        from account_manager import get_default_account
        resolved = get_default_account()
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
    except Exception:
        pass
    return "default"


class CDPError(Exception):
    """CDP 通信错误。"""


class ZhihuPublisher:
    """通过 CDP 自动化发布知乎文章。"""

    def __init__(
        self,
        host: str = CDP_HOST,
        port: int = CDP_PORT,
        timing_jitter: float = 0.25,
        account_name: str | None = None,
    ):
        self.host = host
        self.port = port
        self.ws = None
        self._msg_id = 0
        self.timing_jitter = _normalize_timing_jitter(timing_jitter)
        self.account_name = (account_name or "default").strip() or "default"
        self.login_cache_ttl_hours = DEFAULT_LOGIN_CACHE_TTL_HOURS
        self.login_cache_ttl_seconds = self.login_cache_ttl_hours * 3600
        self.login_cache_file = LOGIN_CACHE_FILE

    # ------------------------------------------------------------------
    # 登录缓存
    # ------------------------------------------------------------------

    def _login_cache_key(self, scope: str) -> str:
        """构建唯一的缓存 key。"""
        return f"{self.host}:{self.port}:{self.account_name}:{scope}"

    def _load_login_cache(self) -> dict[str, Any]:
        """从本地 JSON 文件加载登录缓存。"""
        if not os.path.exists(self.login_cache_file):
            return {"entries": {}}
        try:
            with open(self.login_cache_file, "r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
        except Exception:
            return {"entries": {}}
        if not isinstance(payload, dict):
            return {"entries": {}}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            payload["entries"] = {}
        return payload

    def _save_login_cache(self, payload: dict[str, Any]):
        """持久化登录缓存到本地 JSON 文件。"""
        parent = os.path.dirname(self.login_cache_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.login_cache_file, "w", encoding="utf-8") as cache_file:
            json.dump(payload, cache_file, ensure_ascii=False, indent=2)

    def _get_cached_login_status(self, scope: str) -> bool | None:
        """缓存未过期时返回登录状态。"""
        if self.login_cache_ttl_seconds <= 0:
            return None
        payload = self._load_login_cache()
        entries = payload.get("entries", {})
        entry = entries.get(self._login_cache_key(scope))
        if not isinstance(entry, dict):
            return None
        checked_at = entry.get("checked_at")
        logged_in = entry.get("logged_in")
        if not isinstance(checked_at, (int, float)) or not isinstance(logged_in, bool):
            return None
        age_seconds = time.time() - float(checked_at)
        if age_seconds < 0 or age_seconds > self.login_cache_ttl_seconds:
            return None
        if not logged_in:
            return None
        age_minutes = int(age_seconds // 60)
        print(
            "[cdp_publish] 使用缓存的登录状态 "
            f"({scope}, age={age_minutes}m, ttl={self.login_cache_ttl_hours:g}h)."
        )
        return logged_in

    def _set_login_cache(self, scope: str, logged_in: bool):
        """保存登录状态缓存。"""
        if not logged_in:
            self._clear_login_cache(scope=scope)
            return
        payload = self._load_login_cache()
        entries = payload.setdefault("entries", {})
        entries[self._login_cache_key(scope)] = {
            "logged_in": True,
            "checked_at": int(time.time()),
        }
        self._save_login_cache(payload)

    def _clear_login_cache(self, scope: str | None = None):
        """清除当前 host/port/account 的登录缓存。"""
        payload = self._load_login_cache()
        entries = payload.get("entries", {})
        if not isinstance(entries, dict) or not entries:
            return
        changed = False
        if scope:
            key = self._login_cache_key(scope)
            if key in entries:
                entries.pop(key, None)
                changed = True
        else:
            prefix = self._login_cache_key("")
            for key in list(entries.keys()):
                if key.startswith(prefix):
                    entries.pop(key, None)
                    changed = True
        if changed:
            payload["entries"] = entries
            self._save_login_cache(payload)

    def _sleep(self, base_seconds: float, minimum_seconds: float = 0.05):
        """带随机抖动的延时，避免固定时间模式。"""
        base = max(minimum_seconds, float(base_seconds))
        if self.timing_jitter <= 0:
            time.sleep(base)
            return
        delta = base * self.timing_jitter
        low = max(minimum_seconds, base - delta)
        high = max(low, base + delta)
        time.sleep(random.uniform(low, high))

    # ------------------------------------------------------------------
    # CDP 连接管理
    # ------------------------------------------------------------------

    def _get_targets(self) -> list[dict]:
        """获取可用的浏览器标签页列表，失败时重试一次。"""
        url = f"http://{self.host}:{self.port}/json"
        for attempt in range(2):
            try:
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt == 0:
                    if _is_local_host(self.host):
                        print(f"[cdp_publish] CDP 连接失败 ({e})，正在重启 Chrome...")
                        from chrome_launcher import ensure_chrome
                        ensure_chrome(port=self.port)
                    else:
                        print(
                            f"[cdp_publish] CDP 连接失败 ({e})，正在重试远程端点 "
                            f"{self.host}:{self.port}..."
                        )
                    self._sleep(2, minimum_seconds=1.0)
                else:
                    raise CDPError(f"无法连接 Chrome ({self.host}:{self.port}): {e}")

    def _find_or_create_tab(
        self,
        target_url_prefix: str = "",
        reuse_existing_tab: bool = False,
    ) -> str:
        """查找或创建标签页用于连接。"""
        targets = self._get_targets()
        pages = [
            t for t in targets
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
        ]

        if target_url_prefix:
            for t in pages:
                if t.get("url", "").startswith(target_url_prefix):
                    return t["webSocketDebuggerUrl"]

        if reuse_existing_tab and pages:
            url = pages[0].get("url", "")
            print(f"[cdp_publish] 复用已有标签页: {url}")
            return pages[0]["webSocketDebuggerUrl"]

        # 创建新标签页
        resp = requests.put(
            f"http://{self.host}:{self.port}/json/new?{ZHIHU_WRITE_URL}",
            timeout=5,
        )
        if resp.ok:
            ws_url = resp.json().get("webSocketDebuggerUrl", "")
            if ws_url:
                return ws_url

        # 回退：使用第一个可用页面
        if pages:
            return pages[0]["webSocketDebuggerUrl"]

        raise CDPError("没有可用的浏览器标签页。")

    def connect(self, target_url_prefix: str = "", reuse_existing_tab: bool = False):
        """通过 WebSocket 连接到 Chrome 标签页。"""
        ws_url = self._find_or_create_tab(
            target_url_prefix=target_url_prefix,
            reuse_existing_tab=reuse_existing_tab,
        )
        if not ws_url:
            raise CDPError("无法获取任何标签页的 WebSocket URL。")

        print(f"[cdp_publish] 正在连接 {ws_url}")
        self.ws = ws_client.connect(ws_url)
        print("[cdp_publish] 已连接到 Chrome 标签页。")

    def disconnect(self):
        """关闭 WebSocket 连接。"""
        if self.ws:
            self.ws.close()
            self.ws = None

    # ------------------------------------------------------------------
    # CDP 命令辅助
    # ------------------------------------------------------------------

    def _send(self, method: str, params: dict | None = None) -> dict:
        """发送 CDP 命令并返回结果。"""
        if not self.ws:
            raise CDPError("未连接。请先调用 connect()。")

        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params

        self.ws.send(json.dumps(msg))

        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                if "error" in data:
                    raise CDPError(f"CDP 错误: {data['error']}")
                return data.get("result", {})

    def _evaluate(self, expression: str) -> Any:
        """在页面中执行 JavaScript 并返回结果值。"""
        result = self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        remote_obj = result.get("result", {})
        if remote_obj.get("subtype") == "error":
            raise CDPError(f"JS 错误: {remote_obj.get('description', remote_obj)}")
        return remote_obj.get("value")

    def _navigate(self, url: str):
        """导航当前标签页到指定 URL 并等��加载。"""
        print(f"[cdp_publish] 正在导航到 {url}")
        self._send("Page.enable")
        self._send("Page.navigate", {"url": url})
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=1.0)

    def _move_mouse(self, x: float, y: float):
        """通过 CDP 移动鼠标光标。"""
        self._send("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": float(x),
            "y": float(y),
        })

    def _click_mouse(self, x: float, y: float):
        """通过 CDP 在指定坐标执行鼠标左键点击。"""
        for event_type in ("mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": float(x),
                "y": float(y),
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.05)

    def _click_element_by_cdp(self, description: str, js_get_rect: str):
        """通过 CDP 鼠标事件点击元素（比 JS .click() 更可靠）。"""
        rect = self._evaluate(js_get_rect)
        if not rect:
            raise CDPError(
                f"找不到 {description}。请在浏览器中手动点击。"
            )
        cx = rect["x"] + rect["width"] / 2
        cy = rect["y"] + rect["height"] / 2
        print(f"[cdp_publish] 正在点击 {description} ({cx:.0f}, {cy:.0f})...")
        for event_type in ("mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": cx,
                "y": cy,
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # 登录检测
    # ------------------------------------------------------------------

    def check_login(self) -> bool:
        """
        导航到知乎写文章页，检测登录状态。
        多重策略：URL 重定向检测 → 编辑器元素检测 → #js-initialData 检测。
        返回 True 表示已登录。
        """
        scope = "zhihu"
        cached_status = self._get_cached_login_status(scope)
        if cached_status is not None:
            if cached_status:
                print("[cdp_publish] 登录已确认（缓存）。")
            return cached_status

        self._navigate(ZHIHU_WRITE_URL)
        self._sleep(3, minimum_seconds=2.0)

        current_url = self._evaluate("window.location.href")
        print(f"[cdp_publish] 当前 URL: {current_url}")

        # 策略1: URL 被重定向到登录页
        if isinstance(current_url, str) and ("login" in current_url.lower() or "signin" in current_url.lower()):
            self._set_login_cache(scope, logged_in=False)
            print("\n[cdp_publish] 未登录（URL 重定向到登录页）。\n")
            return False

        # 策略2: 检查页面上是否存在编辑器元素（只有登录后才会渲染）
        has_editor = self._evaluate("""
            (() => {
                if (document.querySelector('textarea[placeholder*="请输入标题"]')) return true;
                if (document.querySelector('textarea.Input')) return true;
                if (document.querySelector('.public-DraftEditor-content')) return true;
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    if (buttons[i].textContent.trim() === '发布') return true;
                }
                return false;
            })()
        """)

        if has_editor:
            self._set_login_cache(scope, logged_in=True)
            print("[cdp_publish] 登录已确认（检测到编辑器）。")
            return True

        # 策略3: 通过 #js-initialData 检测
        has_user = self._evaluate("""
            (() => {
                try {
                    const el = document.getElementById('js-initialData');
                    if (!el) return false;
                    const data = JSON.parse(el.textContent);
                    const state = data && data.initialState;
                    if (!state) return false;
                    const user = state.currentUser || state.user || state.login;
                    if (user && typeof user === 'object') {
                        return !!(user.uid || user.id || user.name || user.urlToken);
                    }
                    return false;
                } catch (e) {
                    return false;
                }
            })()
        """)

        if has_user:
            self._set_login_cache(scope, logged_in=True)
            print("[cdp_publish] 登录已确认（#js-initialData）。")
            return True

        # 策略4: URL 仍在写文章页，再等一下重试编辑器检测
        if isinstance(current_url, str) and "zhuanlan.zhihu.com/write" in current_url:
            self._sleep(3, minimum_seconds=2.0)
            has_editor_retry = self._evaluate("""
                (() => {
                    if (document.querySelector('textarea[placeholder*="请输入标题"]')) return true;
                    if (document.querySelector('.public-DraftEditor-content')) return true;
                    return false;
                })()
            """)
            if has_editor_retry:
                self._set_login_cache(scope, logged_in=True)
                print("[cdp_publish] 登录已确认（重试检��到编辑器）。")
                return True

        self._set_login_cache(scope, logged_in=False)
        print("\n[cdp_publish] 未登录。请在 Chrome 窗口中登录知乎后重试。\n")
        return False

    def clear_cookies(self, domain: str = ".zhihu.com"):
        """清除指定域名的所有 Cookie，用于切换账号。"""
        print(f"[cdp_publish] 正在清除 {domain} 的 Cookie...")
        self._send("Network.enable")
        self._send("Network.clearBrowserCookies")
        self._send("Storage.clearDataForOrigin", {
            "origin": "https://www.zhihu.com",
            "storageTypes": "cookies,local_storage,session_storage",
        })
        self._send("Storage.clearDataForOrigin", {
            "origin": "https://zhuanlan.zhihu.com",
            "storageTypes": "cookies,local_storage,session_storage",
        })
        self._clear_login_cache()
        print("[cdp_publish] Cookie 和存储已清除。")

    def open_login_page(self):
        """导航到知乎登录页面。"""
        self._navigate("https://www.zhihu.com/signin")
        self._sleep(2, minimum_seconds=1.0)
        self._clear_login_cache()
        print("\n[cdp_publish] 登录页面已打开。请在 Chrome 窗口中完成登录。\n")

    # ------------------------------------------------------------------
    # 表单填写
    # ------------------------------------------------------------------

    def _fill_title(self, title: str):
        """填写文章标题（知乎使用 textarea）。"""
        print(f"[cdp_publish] 正在设置标题: {title[:40]}...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        for selector in (SELECTORS["title_input"], SELECTORS["title_input_alt"]):
            found = self._evaluate(f"!!document.querySelector('{selector}')")
            if found:
                escaped_title = json.dumps(title)
                self._evaluate(f"""
                    (function() {{
                        var el = document.querySelector('{selector}');
                        var nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLTextAreaElement.prototype, 'value'
                        ).set;
                        el.focus();
                        nativeSetter.call(el, {escaped_title});
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }})();
                """)
                print("[cdp_publish] 标题已设置。")
                return

        raise CDPError("找不到标题输入框。")

    def _fill_content(self, content: str):
        """填写文章正文（知乎使用 Draft.js 编辑器）。"""
        print(f"[cdp_publish] 正在设置正文 ({len(content)} 字符)...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        for selector in (SELECTORS["content_editor"], SELECTORS["content_editor_alt"]):
            found = self._evaluate(f"!!document.querySelector('{selector}')")
            if found:
                escaped = json.dumps(content)
                self._evaluate(f"""
                    (function() {{
                        var el = document.querySelector('{selector}');
                        el.focus();
                        var text = {escaped};
                        var lines = text.split('\\n');
                        var html = [];
                        for (var i = 0; i < lines.length; i++) {{
                            var line = lines[i];
                            if (line.trim()) {{
                                html.push('<div data-block="true"><div class="public-DraftStyleDefault-block"><span>' + line + '</span></div></div>');
                            }} else {{
                                html.push('<div data-block="true"><div class="public-DraftStyleDefault-block"><br></div></div>');
                            }}
                        }}
                        el.innerHTML = html.join('');
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }})();
                """)
                print("[cdp_publish] 正文已设置。")
                return

        raise CDPError("找不到正文编辑器。")

    def _upload_images(self, image_paths: list[str]):
        """通过 file input 上传图片。"""
        if not image_paths:
            print("[cdp_publish] 没有图片需要上传，跳过。")
            return

        normalized = [p.replace("\\", "/") for p in image_paths]
        print(f"[cdp_publish] 正在上传 {len(image_paths)} 张图片...")

        self._send("DOM.enable")
        doc = self._send("DOM.getDocument")
        root_id = doc["root"]["nodeId"]

        node_id = 0
        for selector in (SELECTORS["upload_input"], SELECTORS["upload_input_alt"]):
            result = self._send("DOM.querySelector", {
                "nodeId": root_id,
                "selector": selector,
            })
            node_id = result.get("nodeId", 0)
            if node_id:
                break

        if not node_id:
            raise CDPError("找不到文件上传元素。页面结构可能已变化。")

        self._send("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": normalized,
        })

        print("[cdp_publish] 图片已上传，等待处理...")
        self._sleep(UPLOAD_WAIT, minimum_seconds=2.0)

    def _click_publish(self):
        """通过 CDP 鼠标事件点击发布按钮。"""
        print("[cdp_publish] 正在点击发布按钮...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        btn_text = SELECTORS["publish_button_text"]
        js_get_rect = f"""
            (function() {{
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {{
                    var t = buttons[i].textContent.trim();
                    if (t === '{btn_text}') {{
                        var r = buttons[i].getBoundingClientRect();
                        return {{ x: r.x, y: r.y, width: r.width, height: r.height }};
                    }}
                }}
                var primaryBtns = document.querySelectorAll('button.Button--primary');
                for (var j = 0; j < primaryBtns.length; j++) {{
                    if (primaryBtns[j].textContent.trim().indexOf('{btn_text}') !== -1) {{
                        var r = primaryBtns[j].getBoundingClientRect();
                        return {{ x: r.x, y: r.y, width: r.width, height: r.height }};
                    }}
                }}
                return null;
            }})();
        """
        self._click_element_by_cdp("发布按钮", js_get_rect)
        print("[cdp_publish] 发布按钮已点击。")
        self._sleep(5, minimum_seconds=2.0)
        return None

    # ------------------------------------------------------------------
    # 主发布流程
    # ------------------------------------------------------------------

    def publish(
        self,
        title: str,
        content: str,
        image_paths: list[str] | None = None,
    ):
        """
        执行完整的发布流程：
        1. 确保在知乎写文章页
        2. 填写标题
        3. 填写正文
        4. 可选上传图片
        """
        if not self.ws:
            raise CDPError("未连接。请先调用 connect()。")

        # 检查当前是否已在写文章页，避免重复导航刷新页面
        current_url = self._evaluate("window.location.href") or ""
        if "zhuanlan.zhihu.com/write" not in current_url:
            self._navigate(ZHIHU_WRITE_URL)
            self._sleep(3, minimum_seconds=2.0)
        else:
            # 已在写文章页，等待页面就绪
            self._sleep(1, minimum_seconds=0.5)

        self._fill_title(title)
        self._fill_content(content)

        if image_paths:
            self._upload_images(image_paths)

        print("\n[cdp_publish] 内容已填写完成。请在浏览器中检查后发布。\n")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main():
    import argparse
    from chrome_launcher import ensure_chrome, restart_chrome

    parser = argparse.ArgumentParser(description="知乎 CDP 文章发布器")
    parser.add_argument("--host", default=CDP_HOST, help=f"CDP 主机 (默认: {CDP_HOST})")
    parser.add_argument("--port", type=int, default=CDP_PORT, help=f"CDP 端口 (默认: {CDP_PORT})")
    parser.add_argument("--headless", action="store_true", help="无头模式（无浏览器窗口）")
    parser.add_argument("--account", help="指定账号名称（默认: 默认账号）")
    parser.add_argument(
        "--timing-jitter", type=float, default=0.25,
        help="操作延时抖动比例 (默认: 0.25)，设为 0 禁用随机抖动",
    )
    parser.add_argument(
        "--reuse-existing-tab", action="store_true",
        help="优先复用已有标签页，减少有窗口模式下的前台切换",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # check-login
    sub.add_parser("check-login", help="检查登录状态 (exit 0=已登录, 1=未登录)")

    # fill - 填写表单但不发布
    p_fill = sub.add_parser("fill", help="填写标题/正文/图片，不发布")
    p_fill.add_argument("--title", required=True)
    p_fill.add_argument("--content", default=None)
    p_fill.add_argument("--content-file", default=None, help="从文件读取正文")
    p_fill.add_argument("--images", nargs="+", help="本地图片文件路径")

    # publish - 填写表单并发布
    p_pub = sub.add_parser("publish", help="填写表单并点击发布")
    p_pub.add_argument("--title", required=True)
    p_pub.add_argument("--content", default=None)
    p_pub.add_argument("--content-file", default=None, help="从文件读取正文")
    p_pub.add_argument("--images", nargs="+", help="本地图片文件路径")

    # click-publish - 仅点击发布按钮
    sub.add_parser("click-publish", help="在已填写的页面上点击发布按钮")

    # login
    sub.add_parser("login", help="打开浏览器进行登录（始终有窗口模式）")

    # re-login
    sub.add_parser("re-login", help="清除 Cookie 并重新登录同一账号")

    # switch-account
    sub.add_parser("switch-account", help="清除 Cookie 并打开登录页切换账号")

    # list-accounts
    sub.add_parser("list-accounts", help="列出所有已配置的账号")

    # add-account
    p_add = sub.add_parser("add-account", help="添加新账号")
    p_add.add_argument("name", help="账号名称（唯一标识）")
    p_add.add_argument("--alias", help="显示名称/描述")

    # remove-account
    p_rm = sub.add_parser("remove-account", help="移除账号")
    p_rm.add_argument("name", help="要移除的账号名称")
    p_rm.add_argument("--delete-profile", action="store_true", help="同时删除 Chrome Profile 目录")

    # set-default-account
    p_def = sub.add_parser("set-default-account", help="设置默认账号")
    p_def.add_argument("name", help="要设为默认的账号名称")

    args = parser.parse_args()
    host = args.host
    port = args.port
    headless = args.headless
    account = args.account
    cache_account_name = _resolve_account_name(account)
    reuse_existing_tab = args.reuse_existing_tab
    timing_jitter = _normalize_timing_jitter(args.timing_jitter)
    local_mode = _is_local_host(host)

    if timing_jitter != args.timing_jitter:
        print(f"[cdp_publish] 警告: --timing-jitter 超出范围，已限制为 {timing_jitter:.2f}。")

    # 不需要 Chrome 的账号管理命令
    if args.command == "list-accounts":
        from account_manager import list_accounts
        accounts = list_accounts()
        if not accounts:
            print("没有已配置的账号。")
            return
        print(f"{'名称':<20} {'别名':<25} {'默认':<10}")
        print("-" * 55)
        for acc in accounts:
            default_mark = "*" if acc["is_default"] else ""
            print(f"{acc['name']:<20} {acc['alias']:<25} {default_mark:<10}")
        return

    elif args.command == "add-account":
        from account_manager import add_account, get_profile_dir
        if add_account(args.name, args.alias):
            print(f"账号 '{args.name}' 已添加。")
            print(f"Profile 目录: {get_profile_dir(args.name)}")
            print(f"\n登录此账号: python cdp_publish.py --account {args.name} login")
        else:
            print(f"错误: 账号 '{args.name}' 已存在。", file=sys.stderr)
            sys.exit(1)
        return

    elif args.command == "remove-account":
        from account_manager import remove_account
        if remove_account(args.name, args.delete_profile):
            print(f"账号 '{args.name}' 已移除。")
        else:
            print(f"错误: 无法移除账号 '{args.name}'。", file=sys.stderr)
            sys.exit(1)
        return

    elif args.command == "set-default-account":
        from account_manager import set_default_account
        if set_default_account(args.name):
            print(f"默认账号已设为 '{args.name}'。")
        else:
            print(f"错误: 账号 '{args.name}' 不存在。", file=sys.stderr)
            sys.exit(1)
        return

    # 需要 Chrome 的命令 - login/re-login/switch-account 始终有窗口
    if args.command in ("login", "re-login", "switch-account"):
        headless = False

    if local_mode:
        if not ensure_chrome(port=port, headless=headless, account=account):
            print("启动 Chrome 失败。退出。")
            sys.exit(1)
    else:
        print(f"[cdp_publish] 远程 CDP 模式: {host}:{port}。跳过本地 Chrome 启动。")

    print(f"[cdp_publish] Timing jitter: {timing_jitter:.2f}")
    print(f"[cdp_publish] 登录缓存: 已启用 (ttl={DEFAULT_LOGIN_CACHE_TTL_HOURS:g}h)。")
    if reuse_existing_tab:
        print("[cdp_publish] 标签页模式: 优先复用已有标签页。")

    publisher = ZhihuPublisher(
        host=host, port=port,
        timing_jitter=timing_jitter,
        account_name=cache_account_name,
    )
    try:
        if args.command == "check-login":
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            logged_in = publisher.check_login()
            if not logged_in and headless:
                print("[cdp_publish] 无头模式下无法登录。请使用 login 命令或去掉 --headless。")
            sys.exit(0 if logged_in else 1)

        elif args.command in ("fill", "publish"):
            content = args.content
            if args.content_file:
                with open(args.content_file, encoding="utf-8") as f:
                    content = f.read().strip()
            if not content:
                print("错误: 需要 --content 或 --content-file。", file=sys.stderr)
                sys.exit(1)

            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.publish(
                title=args.title, content=content,
                image_paths=args.images,
            )
            print("FILL_STATUS: READY_TO_PUBLISH")

            if args.command == "publish":
                publisher._click_publish()
                print("PUBLISH_STATUS: PUBLISHED")

        elif args.command == "click-publish":
            publisher.connect(
                target_url_prefix="https://zhuanlan.zhihu.com",
                reuse_existing_tab=reuse_existing_tab,
            )
            publisher._click_publish()
            print("PUBLISH_STATUS: PUBLISHED")

        elif args.command == "login":
            if local_mode:
                restart_chrome(port=port, headless=False, account=account)
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.open_login_page()
            print("LOGIN_READY")

        elif args.command == "re-login":
            if local_mode:
                restart_chrome(port=port, headless=False, account=account)
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.clear_cookies()
            publisher._sleep(1, minimum_seconds=0.5)
            publisher.open_login_page()
            print("RE_LOGIN_READY")

        elif args.command == "switch-account":
            if local_mode:
                restart_chrome(port=port, headless=False, account=account)
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.clear_cookies()
            publisher._sleep(1, minimum_seconds=0.5)
            publisher.open_login_page()
            print("SWITCH_ACCOUNT_READY")

    finally:
        publisher.disconnect()


if __name__ == "__main__":
    try:
        with single_instance("zhihu_publish"):
            main()
    except SingleInstanceError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(3)
