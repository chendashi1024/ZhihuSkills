"""
知乎文章发布统一流水线。

单一 CLI 入口，编排完整流程：
  chrome_launcher → 登录检查 → 图片下载 → 表单填写 → 发布（默认）

用法:
    # 默认自动发布
    python publish_pipeline.py --title "标题" --content "正文"
    python publish_pipeline.py --title-file t.txt --content-file body.txt --image-urls URL1

    # 预览模式（仅填充，不点发布）
    python publish_pipeline.py --title "标题" --content "正文" --preview

    # 无头模式
    python publish_pipeline.py --headless --title-file t.txt --content-file body.txt

    # 使用本地图片
    python publish_pipeline.py --title "标题" --content "正文" --images img1.jpg img2.jpg

Exit codes:
    0 = 成功 (PUBLISHED, 或预览模式下 READY_TO_PUBLISH)
    1 = 未登录 (NOT_LOGGED_IN)
    2 = 错误 (见 stderr)
"""

import argparse
import json
import os
import random
import sys
import time

# Windows 控制台 UTF-8 输出
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 将 scripts 目录加入 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from chrome_launcher import ensure_chrome, restart_chrome
from cdp_publish import ZhihuPublisher, CDPError
from image_downloader import ImageDownloader
from run_lock import SingleInstanceError, single_instance


MAX_TIMING_JITTER_RATIO = 0.7


def _normalize_timing_jitter(value: float) -> float:
    """将 timing jitter 限制在安全范围内。"""
    return max(0.0, min(MAX_TIMING_JITTER_RATIO, value))


def _is_local_host(host: str) -> bool:
    """判断 host 是否指向本机。"""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _resolve_account_name(account_name: str | None) -> str:
    """解析显式或默认账号名称。"""
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


def _verify_local_files_exist(
    file_paths: list[str],
    media_label: str,
    skip_file_check: bool,
):
    """验证本地文件是否存在（除非显式跳过）。"""
    if skip_file_check:
        print(f"[pipeline] 步骤3: 跳过本地 {media_label} 文件检查 (--skip-file-check)。")
        return
    for file_path in file_paths:
        if not os.path.isfile(file_path):
            print(f"错误: {media_label} 文件不存在: {file_path}", file=sys.stderr)
            sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="知乎文章发布流水线")

    # 标题
    title_group = parser.add_mutually_exclusive_group(required=True)
    title_group.add_argument("--title", help="文章标题")
    title_group.add_argument("--title-file", help="从 UTF-8 文件读取标题")

    # 正文
    content_group = parser.add_mutually_exclusive_group(required=True)
    content_group.add_argument("--content", help="文章正文")
    content_group.add_argument("--content-file", help="从 UTF-8 文件读取正文")

    # 图片（可选，知乎文章可以纯文字发布）
    media_group = parser.add_mutually_exclusive_group(required=False)
    media_group.add_argument("--image-urls", nargs="+", help="图片 URL 列表")
    media_group.add_argument("--images", nargs="+", help="本地图片文件路径")

    # 发布模式
    parser.add_argument(
        "--auto-publish", action="store_true", default=False,
        help="兼容参数：发布已是默认行为，可省略",
    )
    parser.add_argument(
        "--preview", action="store_true", default=False,
        help="预览模式：仅填充内容，不点击发布按钮",
    )

    # 无头模式
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="无头模式运行 Chrome。未登录时自动回退到有窗口模式。",
    )
    parser.add_argument(
        "--timing-jitter", type=float, default=0.25,
        help="操作延时抖动比例 (默认: 0.25)，设为 0 禁用",
    )
    parser.add_argument(
        "--reuse-existing-tab", action="store_true", default=False,
        help="优先复用已有标签页",
    )
    parser.add_argument("--temp-dir", default=None, help="图片下载临时目录")
    parser.add_argument(
        "--skip-file-check", action="store_true", default=False,
        help="跳过本地文件存在性检查（WSL/远程 CDP/UNC 路径可用）",
    )
    parser.add_argument("--account", default=None, help="指定账号")
    parser.add_argument("--host", default="127.0.0.1", help="CDP 主机 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9222, help="CDP 端口 (默认: 9222)")

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
        print(f"[pipeline] 警告: --timing-jitter 超出范围，已限制为 {timing_jitter:.2f}。")

    # --- 解析标题 ---
    if args.title_file:
        with open(args.title_file, encoding="utf-8") as f:
            title = f.read().strip()
    else:
        title = args.title
    if not title:
        print("错误: 标题为空。", file=sys.stderr)
        sys.exit(2)

    # --- 解析正文 ---
    if args.content_file:
        with open(args.content_file, encoding="utf-8") as f:
            content = f.read().strip()
    else:
        content = args.content
    if not content:
        print("错误: 正文为空。", file=sys.stderr)
        sys.exit(2)

    # --- 步骤1: 确保 Chrome 运行 ---
    mode_label = "无头" if headless else "有窗口"
    print(
        f"[pipeline] 步骤1: 确保 Chrome 运行中 "
        f"({mode_label}, 账号: {cache_account_name}, {host}:{port})..."
    )
    print(f"[pipeline] Timing jitter: {timing_jitter:.2f}")
    if reuse_existing_tab:
        print("[pipeline] 标签页模式: 优先复用已有标签页。")
    if local_mode:
        if not ensure_chrome(port=port, headless=headless, account=account):
            print("错误: 启动 Chrome 失败。", file=sys.stderr)
            sys.exit(2)
    else:
        print(f"[pipeline] 远程 CDP 模式: {host}:{port}。跳过本地 Chrome 启动。")

    # --- 步骤2: 连接并检查登录 ---
    print("[pipeline] 步骤2: 检查登录状态...")
    publisher = ZhihuPublisher(
        host=host, port=port,
        timing_jitter=timing_jitter,
        account_name=cache_account_name,
    )
    try:
        publisher.connect(reuse_existing_tab=reuse_existing_tab)
        logged_in = publisher.check_login()
        if not logged_in:
            publisher.disconnect()
            if headless:
                if local_mode:
                    print("[pipeline] 无头模式未登录，切换到有窗口模式登录...")
                    restart_chrome(port=port, headless=False, account=account)
                    publisher.connect(reuse_existing_tab=reuse_existing_tab)
                    publisher.open_login_page()
                else:
                    print("[pipeline] 无头+远程模式，尝试在远程浏览器打开登录页...")
                    publisher.connect(reuse_existing_tab=reuse_existing_tab)
                    publisher.open_login_page()
            print("NOT_LOGGED_IN")
            sys.exit(1)
    except CDPError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(2)

    # --- 步骤3: 准备图片 ---
    image_paths = []
    downloader = None

    if args.image_urls:
        print(f"[pipeline] 步骤3: 下载 {len(args.image_urls)} 张图片...")
        downloader = ImageDownloader(temp_dir=args.temp_dir)
        image_paths = downloader.download_all(args.image_urls)
        if not image_paths:
            print("错误: 所有图片下载失败。", file=sys.stderr)
            sys.exit(2)
    elif args.images:
        image_paths = args.images
        _verify_local_files_exist(
            file_paths=image_paths,
            media_label="图片",
            skip_file_check=args.skip_file_check,
        )
        print(f"[pipeline] 步骤3: 使用 {len(image_paths)} 张本地图片。")
    else:
        print("[pipeline] 步骤3: 无图片，将发布纯文字文章。")

    # --- 步骤4: 填写表单 ---
    print("[pipeline] 步骤4: 填写表单...")
    try:
        publisher.publish(
            title=title, content=content,
            image_paths=image_paths if image_paths else None,
        )
        print("FILL_STATUS: READY_TO_PUBLISH")
    except CDPError as e:
        print(f"表单填写错误: {e}", file=sys.stderr)
        if downloader:
            downloader.cleanup()
        sys.exit(2)

    # --- 步骤5: 发布（可选） ---
    should_publish = not args.preview
    if args.auto_publish:
        print("[pipeline] --auto-publish 已是默认行为，可省略。")
    if args.preview:
        print("[pipeline] 预览模式，跳过发布点击。")

    if should_publish:
        print("[pipeline] 步骤5: 点击发布按钮...")
        try:
            publisher._click_publish()
            print("PUBLISH_STATUS: PUBLISHED")
        except CDPError as e:
            print(f"发布点击错误: {e}", file=sys.stderr)
            if downloader:
                downloader.cleanup()
            sys.exit(2)

    # --- 清理 ---
    publisher.disconnect()
    if downloader:
        downloader.cleanup()

    print("[pipeline] 完成。")


if __name__ == "__main__":
    try:
        with single_instance("zhihu_publish"):
            main()
    except SingleInstanceError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(3)
