"""
测试强制启用按钮后能否成功发布。
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


class PublishTester:
    """测试发布流程"""

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

        # 查找知乎写文章页
        for t in pages:
            if "zhuanlan.zhihu.com" in t.get("url", ""):
                ws_url = t["webSocketDebuggerUrl"]
                print(f"[测试] 连接到: {t.get('url')}")
                self.ws = ws_client.connect(ws_url)
                return

        if pages:
            ws_url = pages[0]["webSocketDebuggerUrl"]
            print(f"[测试] 连接到第一个标签页: {pages[0].get('url')}")
            self.ws = ws_client.connect(ws_url)
        else:
            raise Exception("没有可用的浏览器标签页")

    def disconnect(self):
        """断开连接"""
        if self.ws:
            self.ws.close()
            self.ws = None

    def _send(self, method, params=None):
        """发送 CDP 命令"""
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
        """执行 JavaScript"""
        result = self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        remote_obj = result.get("result", {})
        if remote_obj.get("subtype") == "error":
            raise Exception(f"JS 错误: {remote_obj.get('description', remote_obj)}")
        return remote_obj.get("value")

    def force_enable_button(self):
        """强制启用发布按钮"""
        print("\n[步骤1] 强制启用发布按钮...")

        result = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        // 移除 disabled 属性
                        btn.disabled = false;
                        btn.removeAttribute('disabled');

                        // 修改样式
                        btn.style.pointerEvents = 'auto';
                        btn.style.opacity = '1';
                        btn.style.cursor = 'pointer';

                        // 移除可能的禁用类名
                        btn.classList.remove('disabled');

                        const rect = btn.getBoundingClientRect();
                        return {
                            success: true,
                            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                        };
                    }
                }
                return { success: false };
            })()
        """)

        if result.get('success'):
            print("  ✅ 按钮已强制启用")
            return result.get('rect')
        else:
            print("  ❌ 未找到发布按钮")
            return None

    def click_button(self, rect):
        """点击发布按钮"""
        print("\n[步骤2] 点击发布按钮...")

        cx = rect["x"] + rect["width"] / 2
        cy = rect["y"] + rect["height"] / 2

        print(f"  点击位置: ({cx:.0f}, {cy:.0f})")

        # 移动鼠标
        self._send("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": cx,
            "y": cy,
        })

        time.sleep(0.1)

        # 点击
        self._send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": cx,
            "y": cy,
            "button": "left",
            "clickCount": 1,
        })
        self._send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": cx,
            "y": cy,
            "button": "left",
            "clickCount": 1,
        })

        print("  ✅ 已点击")

    def check_result(self):
        """检查发布结果"""
        print("\n[步骤3] 检查发布结果...")

        for i in range(5):
            time.sleep(1)
            print(f"  等待中... ({i+1}/5)")

            result = self._evaluate("""
                (() => {
                    const url = window.location.href;

                    // 检查是否跳转到文章页
                    if (url.includes('/p/') && !url.includes('/edit')) {
                        return {
                            status: 'published',
                            url: url,
                            message: '已跳转到文章页'
                        };
                    }

                    // 检查是否还在编辑页
                    if (url.includes('/write') || url.includes('/edit')) {
                        // 检查是否有错误提示
                        const errorMsg = document.querySelector('.Notification-message');
                        if (errorMsg) {
                            return {
                                status: 'error',
                                url: url,
                                message: errorMsg.textContent
                            };
                        }

                        // 检查是否有发布确认弹窗
                        const modal = document.querySelector('.Modal');
                        if (modal && modal.style.display !== 'none') {
                            return {
                                status: 'modal',
                                url: url,
                                message: '出现弹窗'
                            };
                        }

                        return {
                            status: 'editing',
                            url: url,
                            message: '仍在编辑页'
                        };
                    }

                    return {
                        status: 'unknown',
                        url: url,
                        message: '未知状态'
                    };
                })()
            """)

            status = result.get('status')

            if status == 'published':
                print(f"\n  ✅ 发布成功!")
                print(f"  文章链接: {result.get('url')}")
                return True

            elif status == 'error':
                print(f"\n  ❌ 发布失败: {result.get('message')}")
                return False

            elif status == 'modal':
                print(f"\n  ⚠️  出现弹窗，可能需要额外确认")
                # 尝试查找并点击确认按钮
                self._evaluate("""
                    (() => {
                        const buttons = document.querySelectorAll('.Modal button');
                        for (let btn of buttons) {
                            const text = btn.textContent.trim();
                            if (text === '确定' || text === '发布' || text === 'OK') {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    })()
                """)
                continue

        print(f"\n  ⚠️  超时: {result.get('message')}")
        print(f"  当前 URL: {result.get('url')}")
        return False


def main():
    """主测试流程"""
    print("=" * 60)
    print("知乎强制发布测试")
    print("=" * 60)

    tester = PublishTester()

    try:
        tester.connect()

        # 1. 强制启用按钮
        rect = tester.force_enable_button()
        if not rect:
            print("\n❌ 无法找到发布按钮")
            return

        time.sleep(0.5)

        # 2. 点击按钮
        tester.click_button(rect)

        # 3. 检查结果
        success = tester.check_result()

        print("\n" + "=" * 60)
        if success:
            print("✅ 测试成功：文章已发布")
        else:
            print("❌ 测试失败：文章未发布")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        tester.disconnect()


if __name__ == "__main__":
    main()
