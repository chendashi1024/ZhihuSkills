"""
测试知乎发布按钮状态的脚本。

检测发布按钮是否可点击，并尝试通过模拟人工输入来激活按钮。
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


class PublishButtonTester:
    """测试知乎发布按钮状态"""

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
            if "zhuanlan.zhihu.com/write" in t.get("url", ""):
                ws_url = t["webSocketDebuggerUrl"]
                print(f"[测试] 连接到知乎写文章页: {t.get('url')}")
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
        print("\n[测试] 检查发布按钮状态...")

        status = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        const rect = btn.getBoundingClientRect();
                        return {
                            found: true,
                            disabled: btn.disabled,
                            className: btn.className,
                            ariaDisabled: btn.getAttribute('aria-disabled'),
                            computedStyle: {
                                pointerEvents: window.getComputedStyle(btn).pointerEvents,
                                opacity: window.getComputedStyle(btn).opacity,
                                cursor: window.getComputedStyle(btn).cursor,
                            },
                            rect: {
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height,
                            },
                            textContent: btn.textContent.trim(),
                        };
                    }
                }
                return { found: false };
            })()
        """)

        if not status.get("found"):
            print("❌ 未找到发布按钮")
            return False

        print(f"\n✅ 找到发布按钮:")
        print(f"  - disabled 属性: {status.get('disabled')}")
        print(f"  - aria-disabled: {status.get('ariaDisabled')}")
        print(f"  - className: {status.get('className')}")
        print(f"  - pointerEvents: {status['computedStyle']['pointerEvents']}")
        print(f"  - opacity: {status['computedStyle']['opacity']}")
        print(f"  - cursor: {status['computedStyle']['cursor']}")
        print(f"  - 位置: ({status['rect']['x']:.0f}, {status['rect']['y']:.0f})")

        # 判断按钮是否可点击
        is_clickable = (
            not status.get('disabled') and
            status.get('ariaDisabled') != 'true' and
            status['computedStyle']['pointerEvents'] != 'none' and
            float(status['computedStyle']['opacity']) > 0.5
        )

        if is_clickable:
            print("\n✅ 发布按钮可点击")
        else:
            print("\n⚠️  发布按钮被禁用")

        return is_clickable, status

    def simulate_manual_input(self):
        """模拟手动输入一个字符来激活按钮"""
        print("\n[测试] 模拟手动输入以激活发布按钮...")

        # 在标题末尾添加一个空格再删除
        result = self._evaluate("""
            (() => {
                const titleInput = document.querySelector('textarea[placeholder*="请输入标题"]');
                if (!titleInput) {
                    return { success: false, error: '未找到标题输入框' };
                }

                // 聚焦
                titleInput.focus();

                // 获取当前值
                const originalValue = titleInput.value;

                // 模拟输入一个空格
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeSetter.call(titleInput, originalValue + ' ');

                // 触发输入事件
                titleInput.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    cancelable: true,
                    inputType: 'insertText',
                    data: ' '
                }));
                titleInput.dispatchEvent(new Event('change', { bubbles: true }));

                // 等待一下
                return new Promise(resolve => {
                    setTimeout(() => {
                        // 删除空格
                        nativeSetter.call(titleInput, originalValue);
                        titleInput.dispatchEvent(new InputEvent('input', {
                            bubbles: true,
                            cancelable: true,
                            inputType: 'deleteContentBackward'
                        }));
                        titleInput.dispatchEvent(new Event('change', { bubbles: true }));

                        resolve({ success: true, originalValue: originalValue });
                    }, 100);
                });
            })()
        """)

        if result.get('success'):
            print("✅ 已模拟手动输入")
            time.sleep(0.5)  # 等待页面响应
            return True
        else:
            print(f"❌ 模拟输入失败: {result.get('error')}")
            return False

    def try_click_button(self):
        """尝试点击发布按钮"""
        print("\n[测试] 尝试点击发布按钮...")

        result = self._evaluate("""
            (() => {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        const rect = btn.getBoundingClientRect();

                        // 尝试点击
                        try {
                            btn.click();
                            return {
                                success: true,
                                clicked: true,
                                rect: { x: rect.x, y: rect.y }
                            };
                        } catch (e) {
                            return {
                                success: false,
                                error: e.message,
                                rect: { x: rect.x, y: rect.y }
                            };
                        }
                    }
                }
                return { success: false, error: '未找到发布按钮' };
            })()
        """)

        if result.get('success'):
            print("✅ 发布按钮点击成功")
            return True
        else:
            print(f"❌ 发布按钮点击失败: {result.get('error')}")
            return False

    def check_publish_result(self):
        """检查是否成功发布"""
        print("\n[测试] 等待发布结果...")
        time.sleep(3)

        result = self._evaluate("""
            (() => {
                const url = window.location.href;

                // 检查是否跳转到文章页
                if (url.includes('/p/')) {
                    return {
                        published: true,
                        url: url,
                        message: '已跳转到文章页'
                    };
                }

                // 检查是否还在编辑页
                if (url.includes('/write')) {
                    // 检查是否有错误提示
                    const errorMsg = document.querySelector('.Notification-message');
                    if (errorMsg) {
                        return {
                            published: false,
                            url: url,
                            message: '发布失败: ' + errorMsg.textContent
                        };
                    }

                    return {
                        published: false,
                        url: url,
                        message: '仍在编辑页，可能未发布'
                    };
                }

                return {
                    published: false,
                    url: url,
                    message: '未知状态'
                };
            })()
        """)

        if result.get('published'):
            print(f"✅ 发布成功!")
            print(f"   文章链接: {result.get('url')}")
        else:
            print(f"⚠️  {result.get('message')}")
            print(f"   当前 URL: {result.get('url')}")

        return result.get('published')


def main():
    """主测试流程"""
    print("=" * 60)
    print("知乎发布按钮状态测试")
    print("=" * 60)

    tester = PublishButtonTester()

    try:
        # 1. 连接
        tester.connect()

        # 2. 检查按钮初始状态
        is_clickable, status = tester.check_button_status()

        if not is_clickable:
            # 3. 如果按钮被禁用，尝试模拟手动输入
            print("\n" + "=" * 60)
            print("按钮被禁用，尝试模拟手动输入激活...")
            print("=" * 60)

            if tester.simulate_manual_input():
                # 4. 再次检查按钮状态
                is_clickable_after, status_after = tester.check_button_status()

                if is_clickable_after:
                    print("\n✅ 模拟输入后按钮已激活!")
                else:
                    print("\n❌ 模拟输入后按钮仍被禁用")
                    print("\n建议: 这可能是知乎��反爬虫机制，需要真实的用户交互")
                    return

        # 5. 尝试点击按钮
        print("\n" + "=" * 60)
        print("尝试点击发布按钮...")
        print("=" * 60)

        if tester.try_click_button():
            # 6. 检查发布结果
            tester.check_publish_result()

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        tester.disconnect()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
