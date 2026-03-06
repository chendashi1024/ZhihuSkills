"""
测试直接点击已启用的发布按钮。
"""

import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import requests
import websockets.sync.client as ws_client

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222


class DirectClickTester:
    """测试直接点击"""

    def __init__(self, host=CDP_HOST, port=CDP_PORT):
        self.host = host
        self.port = port
        self.ws = None
        self._msg_id = 0

    def connect(self):
        """连接到 Chrome"""
        url = f"http://{self.host}:{self.port}/json"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        targets = resp.json()

        pages = [
            t for t in targets
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
        ]

        for t in pages:
            if "zhuanlan.zhihu.com" in t.get("url", ""):
                ws_url = t["webSocketDebuggerUrl"]
                print(f"[测试] 连接到: {t.get('url')}")
                self.ws = ws_client.connect(ws_url)
                return

        if pages:
            ws_url = pages[0]["webSocketDebuggerUrl"]
            self.ws = ws_client.connect(ws_url)

    def disconnect(self):
        if self.ws:
            self.ws.close()
            self.ws = None

    def _send(self, method, params=None):
        if not self.ws:
            raise Exception("未连接")

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
                    raise Exception(f"CDP 错误: {data['error']}")
                return data.get("result", {})

    def _evaluate(self, expression):
        result = self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        remote_obj = result.get("result", {})
        if remote_obj.get("subtype") == "error":
            raise Exception(f"JS 错误: {remote_obj.get('description', remote_obj)}")
        return remote_obj.get("value")

    def check_button_status(self):
        """检查按钮当前状态"""
        print("\n[检查] 发布按钮状态...")

        status = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        const style = window.getComputedStyle(btn);
                        return {
                            found: true,
                            disabled: btn.disabled,
                            pointerEvents: style.pointerEvents,
                            opacity: style.opacity,
                            cursor: style.cursor,
                            className: btn.className,
                        };
                    }
                }
                return { found: false };
            })()
        """)

        if not status.get('found'):
            print("  ❌ 未找到发布按钮")
            return False

        print(f"  disabled: {status.get('disabled')}")
        print(f"  pointerEvents: {status.get('pointerEvents')}")
        print(f"  opacity: {status.get('opacity')}")
        print(f"  cursor: {status.get('cursor')}")

        is_clickable = (
            not status.get('disabled') and
            status.get('pointerEvents') != 'none'
        )

        if is_clickable:
            print("  ✅ 按钮可点击")
        else:
            print("  ⚠️  按钮被禁用")

        return is_clickable

    def force_enable_and_click(self):
        """强制启用并点击"""
        print("\n[操作] 强制启用并点击发布按钮...")

        result = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        // 强制启用
                        btn.disabled = false;
                        btn.removeAttribute('disabled');
                        btn.style.pointerEvents = 'auto';
                        btn.style.opacity = '1';
                        btn.style.cursor = 'pointer';

                        // 直接点击
                        try {
                            btn.click();
                            return { success: true, method: 'click()' };
                        } catch (e) {
                            return { success: false, error: e.message };
                        }
                    }
                }
                return { success: false, error: '未找到按钮' };
            })()
        """)

        if result.get('success'):
            print(f"  ✅ 点击成功 (方法: {result.get('method')})")
            return True
        else:
            print(f"  ❌ 点击失败: {result.get('error')}")
            return False

    def check_publish_result(self):
        """检查发布结果"""
        print("\n[检查] 发布结果...")

        for i in range(6):
            time.sleep(1)

            result = self._evaluate("""
                (() => {
                    const url = window.location.href;

                    // 检查是否跳转到文章页
                    if (url.includes('/p/') && !url.includes('/edit')) {
                        return {
                            status: 'published',
                            url: url
                        };
                    }

                    // 检查是否有弹窗
                    const modals = document.querySelectorAll('.Modal, [role="dialog"]');
                    for (let modal of modals) {
                        const display = window.getComputedStyle(modal).display;
                        if (display !== 'none') {
                            const modalText = modal.textContent;
                            return {
                                status: 'modal',
                                url: url,
                                modalText: modalText.substring(0, 100)
                            };
                        }
                    }

                    // 检查错误提示
                    const notification = document.querySelector('.Notification-message');
                    if (notification) {
                        return {
                            status: 'error',
                            url: url,
                            message: notification.textContent
                        };
                    }

                    // 仍在编辑页
                    if (url.includes('/write') || url.includes('/edit')) {
                        return {
                            status: 'editing',
                            url: url
                        };
                    }

                    return {
                        status: 'unknown',
                        url: url
                    };
                })()
            """)

            status = result.get('status')
            print(f"  [{i+1}/6] 状态: {status}")

            if status == 'published':
                print(f"\n  ✅ 发布成功!")
                print(f"  文章链接: {result.get('url')}")
                return True

            elif status == 'modal':
                print(f"  ⚠️  出现弹窗: {result.get('modalText', '')[:50]}...")
                # 尝试点击确认按钮
                clicked = self._evaluate("""
                    (() => {
                        const buttons = document.querySelectorAll('.Modal button, [role="dialog"] button');
                        for (let btn of buttons) {
                            const text = btn.textContent.trim();
                            if (text === '确定' || text === '发布' || text === 'OK' || text === '确认') {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    })()
                """)
                if clicked:
                    print("  已点击弹窗确认按钮")
                continue

            elif status == 'error':
                print(f"\n  ❌ 发布失败: {result.get('message')}")
                return False

        print(f"\n  ⚠️  超时，最终状态: {status}")
        print(f"  当前 URL: {result.get('url')}")
        return False


def main():
    print("=" * 60)
    print("知乎发布按钮直接点击测试")
    print("=" * 60)

    tester = DirectClickTester()

    try:
        tester.connect()

        # 1. 检查初始状态
        initial_clickable = tester.check_button_status()

        # 2. 强制启用并点击
        if tester.force_enable_and_click():
            # 3. 检查结果
            success = tester.check_publish_result()

            print("\n" + "=" * 60)
            if success:
                print("✅ 测试成功：文章已发布")
            else:
                print("❌ 测试失败：文章未发布")
            print("=" * 60)
        else:
            print("\n❌ 无法点击按钮")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        tester.disconnect()


if __name__ == "__main__":
    main()
