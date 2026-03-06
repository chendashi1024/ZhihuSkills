"""
检查知乎发布的所有验证条件。
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


class ValidationChecker:
    """检查发布验证条件"""

    def __init__(self, host=CDP_HOST, port=CDP_PORT):
        self.host = host
        self.port = port
        self.ws = None
        self._msg_id = 0

    def connect(self):
        url = f"http://{self.host}:{self.port}/json"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        targets = resp.json()

        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]

        for t in pages:
            if "zhuanlan.zhihu.com" in t.get("url", ""):
                ws_url = t["webSocketDebuggerUrl"]
                print(f"[检查] 连接到: {t.get('url')}")
                self.ws = ws_client.connect(ws_url)
                return

    def disconnect(self):
        if self.ws:
            self.ws.close()

    def _send(self, method, params=None):
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

    def check_all_conditions(self):
        """检查所有可能的发布条件"""
        print("\n" + "=" * 60)
        print("检查发布条件")
        print("=" * 60)

        info = self._evaluate("""
            (() => {
                // 1. 标题
                const titleInput = document.querySelector('textarea[placeholder*="请输入标题"]');
                const title = titleInput ? titleInput.value : '';

                // 2. 正文
                const contentEditor = document.querySelector('.public-DraftEditor-content');
                const content = contentEditor ? contentEditor.textContent : '';

                // 3. 发布按钮
                let publishButton = null;
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.textContent.trim() === '发布') {
                        publishButton = btn;
                        break;
                    }
                }

                // 4. 检查 React 状态
                let reactState = null;
                try {
                    // 尝试从 React Fiber 获取状态
                    const reactKey = Object.keys(titleInput || {}).find(k => k.startsWith('__react'));
                    if (reactKey && titleInput[reactKey]) {
                        const fiber = titleInput[reactKey];
                        reactState = {
                            hasReactFiber: true,
                            fiberKeys: Object.keys(fiber).slice(0, 10)
                        };
                    }
                } catch (e) {
                    reactState = { error: e.message };
                }

                // 5. 检查是否有验证错误
                const errorMessages = [];
                document.querySelectorAll('.error, .Error, [class*="error"]').forEach(el => {
                    if (el.textContent && el.offsetParent !== null) {
                        errorMessages.push(el.textContent.trim());
                    }
                });

                // 6. 检查按钮的事件监听器数量
                let hasClickHandler = false;
                try {
                    // 检查 onclick 属性
                    hasClickHandler = publishButton && (
                        publishButton.onclick !== null ||
                        publishButton.getAttribute('onclick') !== null
                    );
                } catch (e) {}

                return {
                    title: {
                        value: title,
                        length: title.length,
                        isEmpty: title.trim().length === 0
                    },
                    content: {
                        value: content.substring(0, 100),
                        length: content.length,
                        isEmpty: content.trim().length === 0
                    },
                    button: publishButton ? {
                        disabled: publishButton.disabled,
                        pointerEvents: window.getComputedStyle(publishButton).pointerEvents,
                        opacity: window.getComputedStyle(publishButton).opacity,
                        hasClickHandler: hasClickHandler,
                        className: publishButton.className
                    } : null,
                    reactState: reactState,
                    errorMessages: errorMessages,
                    url: window.location.href
                };
            })()
        """)

        # 打印结果
        print("\n[标题]")
        print(f"  长度: {info['title']['length']}")
        print(f"  为空: {info['title']['isEmpty']}")
        print(f"  内容: {info['title']['value'][:50]}...")

        print("\n[正文]")
        print(f"  长度: {info['content']['length']}")
        print(f"  为空: {info['content']['isEmpty']}")
        print(f"  内容: {info['content']['value'][:50]}...")

        print("\n[发布按钮]")
        if info['button']:
            print(f"  disabled: {info['button']['disabled']}")
            print(f"  pointerEvents: {info['button']['pointerEvents']}")
            print(f"  opacity: {info['button']['opacity']}")
            print(f"  hasClickHandler: {info['button']['hasClickHandler']}")
        else:
            print("  ❌ 未找到")

        print("\n[React 状态]")
        print(f"  {info['reactState']}")

        print("\n[错误信息]")
        if info['errorMessages']:
            for msg in info['errorMessages']:
                print(f"  - {msg}")
        else:
            print("  无")

        print("\n[当前 URL]")
        print(f"  {info['url']}")

        # 判断是否满足发布条件
        print("\n" + "=" * 60)
        print("条件检查结果")
        print("=" * 60)

        checks = []
        checks.append(("标题不为空", not info['title']['isEmpty']))
        checks.append(("正文不为空", not info['content']['isEmpty']))
        checks.append(("按钮存在", info['button'] is not None))
        if info['button']:
            checks.append(("按钮未禁用", not info['button']['disabled']))
            checks.append(("按钮可交互", info['button']['pointerEvents'] != 'none'))
        checks.append(("无错误信息", len(info['errorMessages']) == 0))

        all_passed = True
        for name, passed in checks:
            status = "✅" if passed else "❌"
            print(f"  {status} {name}")
            if not passed:
                all_passed = False

        return all_passed, info


def main():
    print("=" * 60)
    print("知乎发布条件检查")
    print("=" * 60)

    checker = ValidationChecker()

    try:
        checker.connect()
        all_passed, info = checker.check_all_conditions()

        print("\n" + "=" * 60)
        if all_passed:
            print("✅ 所有条件都满足，理论上应该可以发布")
            print("\n建议: 如果点击后仍无法发布，可能是:")
            print("  1. 知乎检测到自动化填充的内容")
            print("  2. 需要额外的用户交互（如鼠标移动、焦点切换）")
            print("  3. React 内部状态验证失败")
        else:
            print("❌ 存在未满足的条件")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        checker.disconnect()


if __name__ == "__main__":
    main()
