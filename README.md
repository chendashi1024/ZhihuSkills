# ZhihuSkills

自动发布文章到知乎专栏的命令行工具，也支持仅启动测试浏览器（不发布）。
通过 Chrome DevTools Protocol (CDP) 实现自动化发布，支持多账号管理、无头模式运行。

## 功能特性
- **自动化发布**：自动填写标题、正文、上传图片
- **纯文字发布**：知乎文章支持无图片发布
- **多账号支持**：支持管理多个知乎账号，各账号 Cookie 隔离
- **无头模式**：支持后台运行，无需显示浏览器窗口
- **远程 CDP 支持**：可通过 `--host` / `--port` 连接远程 Chrome 调试端口
- **图片下载**：支持从 URL 自动下载图片，自动添加 Referer 绕过防盗链
- **登录检测**：自动检测登录状态，未登录时自动切换到有窗口模式
- **登录状态缓存**：`check_login` 默认本地缓存 12 小时，减少重复跳转校验

## 安装

### 环境要求

- Python 3.10+
- Google Chrome 浏览器

### 安装依赖

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 首次登录

```bash
python scripts/cdp_publish.py login
```

在弹出的 Chrome 窗口中登录知乎。

### 2. 启动/测试浏览器（不发布）

```bash
# 启动测试浏览器（有窗口，推荐）
python scripts/chrome_launcher.py

# 无头启动测试浏览器
python scripts/chrome_launcher.py --headless

# 检查当前登录状态
python scripts/cdp_publish.py check-login

# 可选：优先复用已有标签页
python scripts/cdp_publish.py check-login --reuse-existing-tab

# 重启测试浏览器
python scripts/chrome_launcher.py --restart

# 关闭测试浏览器
python scripts/chrome_launcher.py --kill
```

### 3. 发布文章

```bash
# 无头模式发布（推荐，默认自动发布）
python scripts/publish_pipeline.py --headless \
    --title "文章标题" \
    --content "文章正文" \
    --image-urls "https://example.com/image.jpg"

# 纯文字发布（无图片）
python scripts/publish_pipeline.py --headless \
    --title "文章标题" \
    --content "文章正文"

# 有窗口预览模式（仅填充，不自动点发布）
python scripts/publish_pipeline.py \
    --preview \
    --title "文章标题" \
    --content "文章正文"

# 从文件读取内容
python scripts/publish_pipeline.py --headless \
    --title-file title.txt \
    --content-file content.txt \
    --image-urls "https://example.com/image.jpg"

# 使用本地图片
python scripts/publish_pipeline.py --headless \
    --title "文章标题" \
    --content "文章正文" \
    --images "/path/to/image.jpg"
```

### 4. 多账号管理

```bash
# 列出所有账号
python scripts/cdp_publish.py list-accounts

# 添加新账号
python scripts/cdp_publish.py add-account myaccount --alias "我的账号"

# 登录指定账号
python scripts/cdp_publish.py --account myaccount login

# 使用指定账号发布
python scripts/publish_pipeline.py --account myaccount --headless \
    --title "标题" --content "正文"

# 设置默认账号
python scripts/cdp_publish.py set-default-account myaccount

# 切换账号（清除当前登录，重新登录）
python scripts/cdp_publish.py switch-account
```

## 命令参考

### publish_pipeline.py

统一发布入口，一条命令完成全部流程。

```bash
python scripts/publish_pipeline.py [选项]

选项:
  --title TEXT           文章标题
  --title-file FILE      从文件读取标题
  --content TEXT         文章正文
  --content-file FILE    从文件读取正文
  --image-urls URL...    图片 URL 列表（可选）
  --images FILE...       本地图片文件列表（可选）
  --skip-file-check      跳过本地文件存在性检查
  --host HOST            CDP 主机地址（默认 127.0.0.1）
  --port PORT            CDP 端口（默认 9222）
  --headless             无头模式
  --reuse-existing-tab   优先复用已有标签页
  --account NAME         指定账号
  --preview              预览模式：仅填充内容，不点击发布
```

### cdp_publish.py

底层发布控制，支持分步操作。

```bash
# 检查登录状态
python scripts/cdp_publish.py check-login

# 填写表单（不发布）
python scripts/cdp_publish.py fill --title "标题" --content "正文"

# 点击发布按钮
python scripts/cdp_publish.py click-publish

# 账号管理
python scripts/cdp_publish.py login
python scripts/cdp_publish.py list-accounts
python scripts/cdp_publish.py add-account NAME [--alias ALIAS]
python scripts/cdp_publish.py remove-account NAME [--delete-profile]
python scripts/cdp_publish.py set-default-account NAME
python scripts/cdp_publish.py switch-account
```

### chrome_launcher.py

Chrome 浏览器管理。

```bash
python scripts/chrome_launcher.py              # 启动
python scripts/chrome_launcher.py --headless    # 无头启动
python scripts/chrome_launcher.py --restart     # 重启
python scripts/chrome_launcher.py --kill        # 关闭
```

## 注意事项

1. **仅供学习研究**：请遵守知乎平台规则，不要用于违规内容发布
2. **登录安全**：Cookie 存储在本地 Chrome Profile 中，请勿泄露
3. **选择器更新**：如果知乎页面结构变化导致发布失败，需要更新 `cdp_publish.py` 中的选择器

## 许可证

MIT License
