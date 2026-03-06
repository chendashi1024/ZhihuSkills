"""
测试多种方法激活知乎发布按钮。
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


class ActivationTester:
    """测试多种激活方法"""

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

    def check_button_status(self):
        """检查发布按钮状态"""
        status = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        return {
                            disabled: btn.disabled,
                            pointerEvents: window.getComputedStyle(btn).pointerEvents,
                            opacity: window.getComputedStyle(btn).opacity,
                        };
                    }
                }
                return null;
            })()
        """)

        if not status:
            return False

        is_enabled = (
            not status.get('disabled') and
            status.get('pointerEvents') != 'none'
        )

        return is_enabled

    def method_1_js_input_event(self):
        """方法1: JavaScript InputEvent"""
        print("\n[方法1] JavaScript InputEvent...")

        self._evaluate("""
            (() => {
                const titleInput = document.querySelector('textarea[placeholder*="请输入标题"]');
                if (!titleInput) return false;

                titleInput.focus();
                const originalValue = titleInput.value;

                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeSetter.call(titleInput, originalValue + ' ');

                titleInput.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    cancelable: true,
                    inputType: 'insertText',
                    data: ' '
                }));

                setTimeout(() => {
                    nativeSetter.call(titleInput, originalValue);
                    titleInput.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'deleteContentBackward'
                    }));
                }, 100);

                return true;
            })()
        """)

        time.sleep(0.5)
        return self.check_button_status()

    def method_2_cdp_keyboard(self):
        """方法2: CDP Input.dispatchKeyEvent"""
        print("\n[方法2] CDP Input.dispatchKeyEvent...")

        # 聚焦标题输入框
        self._evaluate("""
            (() => {
                const titleInput = document.querySelector('textarea[placeholder*="请输入标题"]');
                if (titleInput) {
                    titleInput.focus();
                    return true;
                }
                return false;
            })()
        """)

        time.sleep(0.2)

        # 输入空格
        self._send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": " ",
            "code": "Space",
            "text": " ",
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "char",
            "text": " ",
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": " ",
            "code": "Space",
        })

        time.sleep(0.1)

        # 删除空格
        self._send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": "Backspace",
            "code": "Backspace",
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": "Backspace",
            "code": "Backspace",
        })

        time.sleep(0.5)
        return self.check_button_status()

    def method_3_click_title(self):
        """方法3: CDP 鼠标点击标题输入框"""
        print("\n[方法3] CDP 鼠标点击标题输入框...")

        rect = self._evaluate("""
            (() => {
                const titleInput = document.querySelector('textarea[placeholder*="请输入标题"]');
                if (!titleInput) return null;

                const r = titleInput.getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height };
            })()
        """)

        if not rect:
            print("  未找到标题输入框")
            return False

        cx = rect["x"] + rect["width"] / 2
        cy = rect["y"] + rect["height"] / 2

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

        time.sleep(0.3)

        # 然后输入字符
        self._send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": " ",
            "code": "Space",
            "text": " ",
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "char",
            "text": " ",
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": " ",
            "code": "Space",
        })

        time.sleep(0.1)

        self._send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "key": "Backspace",
            "code": "Backspace",
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": "Backspace",
            "code": "Backspace",
        })

        time.sleep(0.5)
        return self.check_button_status()

    def method_4_force_enable(self):
        """方法4: 强制启用按钮（可能被知乎检测）"""
        print("\n[方法4] 强制启用按钮...")

        result = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        btn.disabled = false;
                        btn.style.pointerEvents = 'auto';
                        btn.style.opacity = '1';
                        return true;
                    }
                }
                return false;
            })()
        """)

        time.sleep(0.3)
        return self.check_button_status()

    def check_what_zhihu_monitors(self):
        """检查知乎可能监控的事件"""
        print("\n[检查] 知乎监控的事件...")

        info = self._evaluate("""
            (() => {
                const titleInput = document.querySelector('textarea[placeholder*="请输入标题"]');
                if (!titleInput) return { error: '未找到标题输入框' };

                // 检查是否有特殊属性
                const hasReactProps = Object.keys(titleInput).some(k => k.startsWith('__react'));

                return {
                    hasReactProps: hasReactProps,
                    value: titleInput.value,
                    valueLength: titleInput.value.length,
                };
            })()
        """)

        print(f"  React Props: {info.get('hasReactProps')}")
        print(f"  标题长度: {info.get('valueLength')}")


def main():
    """主测试流程"""
    print("=" * 60)
    print("知乎发布按钮激活方法测试")
    print("=" * 60)

    tester = ActivationTester()

    try:
        tester.connect()

        # 检查初始状态
        print("\n[初始状态]")
        initial_status = tester.check_button_status()
        print(f"  发布按钮可用: {initial_status}")

        if initial_status:
            print("\n✅ 按钮已经可用，无需测试")
            return

        # 检查知乎监控什么
        tester.check_what_zhihu_monitors()

        # 测试各种方法
        methods = [
            ("JavaScript InputEvent", tester.method_1_js_input_event),
            ("CDP Keyboard", tester.method_2_cdp_keyboard),
            ("CDP Mouse + Keyboard", tester.method_3_click_title),
            ("强制启用", tester.method_4_force_enable),
        ]

        results = []
        for name, method in methods:
            try:
                success = method()
                results.append((name, success))
                print(f"  结果: {'✅ 成功' if success else '❌ 失败'}")
            except Exception as e:
                results.append((name, False))
                print(f"  结果: ❌ 错误 - {e}")

            time.sleep(1)

        # 总结
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        for name, success in results:
            status = "✅ 成功" if success else "❌ 失败"
            print(f"  {name}: {status}")

        if not any(success for _, success in results):
            print("\n⚠️  所有自动化方法均失败")
            print("建议: 知乎可能使用了高级反爬虫检测，需要真实用户交互")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        tester.disconnect()


if __name__ == "__main__":
    main()
