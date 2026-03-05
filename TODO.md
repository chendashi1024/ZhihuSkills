# ZhihuSkills 改造 TODO

## 知乎写文章页 DOM 结构（zhuanlan.zhihu.com/write）

```
页面容器: .WriteIndexLayout-main.WriteIndex
编辑器容器: .PostEditor.Editable

标题输入: textarea.Input[placeholder="请输入标题（最多 100 个字）"]
正文编辑器: .public-DraftEditor-content[contenteditable="true"]  (Draft.js)
正文占位符: .public-DraftEditorPlaceholder-inner

图片上传（正文内插图）: input[type="file"][accept*="image/webp"]  (hidden, multiple)
封面上传: input.UploadPicture-input[accept=".jpeg, .jpg, .png"]

发布按钮: button.Button--primary.Button--blue 含文本"发布"
预览按钮: button 含文本"预览"
发布设置按钮: button 含文本"发布设置" (class css-9dyic7)

专栏选择: input.RadioButton-input[type="radio"]
工具栏: div.toolbarV3

初始数据: #js-initialData (JSON, 含 initialState.currentUser)
登录检测: 检查 #js-initialData 中 initialState.currentUser 是否存在
```

## 改造任务

### 1. cdp_publish.py（核心，改动最大）
- [x] 文件头部文档字符串：小红书 → 知乎
- [x] 移除小红书特有的 import（feed_explorer 相关）
- [x] URL 常量替换
  - `XHS_CREATOR_URL` → `ZHIHU_WRITE_URL = "https://zhuanlan.zhihu.com/write"`
  - `XHS_HOME_URL` → `ZHIHU_HOME_URL = "https://www.zhihu.com"`
  - `XHS_CREATOR_LOGIN_CHECK_URL` → `ZHIHU_WRITE_URL`（写文章页即可检测登录）
  - 移除 `XHS_NOTIFICATION_URL`、`XHS_CONTENT_DATA_URL`、`XHS_CONTENT_DATA_API_PATH`、`XHS_NOTIFICATION_MENTIONS_API_PATH`、`XHS_SEARCH_RECOMMEND_API_PATH`、`XHS_FEED_INACCESSIBLE_KEYWORDS`、`XHS_HOME_LOGIN_MODAL_KEYWORD`
- [x] SELECTORS 替换为知乎 DOM 选择器（见上方 DOM 结构）
- [x] 类名 `XiaohongshuPublisher` → `ZhihuPublisher`
- [x] `check_login()` 改为通过 `#js-initialData` 检测 `currentUser`
- [x] `check_home_login()` 改为知乎首页登录检测（或移除，合并到 check_login）
- [x] `clear_cookies()` domain 改为 `.zhihu.com`
- [x] `open_login_page()` 改为知乎登录页
- [x] `_fill_title()` 适配 textarea（不是 input，不能用 HTMLInputElement.prototype.value setter）
- [x] `_fill_content()` 适配 Draft.js 编辑器（不是 TipTap/ProseMirror）
- [x] `_upload_images()` 适配知乎的 file input 选择器
- [x] `_click_publish()` 适配知乎发布按钮选择器
- [x] 移除小红书特有功能方法：
  - `_click_tab` / `_click_image_text_tab` / `_click_video_tab`（知乎无 tab 切换）
  - `_upload_video` / `_wait_video_processing`（知乎文章不支持直接上传视频）
  - `search_feeds` / `get_feed_detail` / `post_comment_to_feed`
  - `get_notification_mentions` / `_fetch_notification_mentions_via_page`
  - `_schedule_click_notification_mentions_tab`
  - `get_content_data` / `_check_feed_page_accessible` / `_fill_comment_content`
  - `_prepare_search_input_keyword` / `_capture_search_recommendations_via_network`
  - `_extract_recommend_keywords_from_payload`
  - `_like_note` / `_collect_note`
- [x] `publish()` 流程改为：导航到写文章页 → 填标题 → 填正文 → （可选上传图片）
- [x] 移除 `publish_video()`
- [x] CLI main() 中移除小红书特有子命令（search-feeds、get-feed-detail、post-comment-to-feed、get-notification-mentions、content-data）
- [x] CLI 描述文字改为知乎
- [x] `_find_or_create_tab()` 中新标签页 URL 改为知乎写文章页
- [x] `click-publish` 的 target_url_prefix 改为知乎
- [x] 单实例锁名称 `post_to_xhs_publish` → `zhihu_publish`
- [x] 移除 `_map_note_infos_to_content_rows`、`_write_content_data_csv`、`_format_*` 等辅助函数

### 2. publish_pipeline.py
- [x] 文档字符串：小红书 → 知乎
- [x] import 类名 `XiaohongshuPublisher` → `ZhihuPublisher`
- [x] 移除视频发布相关逻辑（`--video`、`--video-url`）
- [x] 移除话题标签提取和输入逻辑（知乎文章无话题标签输入）
- [x] 发布流程适配：导航 → 填标题 → 填正文 → 可选上传图片 → 发布
- [x] 图片改为可选（知乎文章可以纯文字发布）
- [x] 单实例锁名称改为知乎

### 3. chrome_launcher.py
- [x] Profile 目录名 `XiaohongshuProfiles` → `ZhihuProfiles`
- [x] 日志前缀和注释中的小红书引用改为知乎

### 4. account_manager.py
- [x] Profile 目录名 `XiaohongshuProfiles` → `ZhihuProfiles`
- [x] 注释和文档字符串改为知乎

### 5. feed_explorer.py
- [x] 整个文件已删除（知乎不需要 feed 搜索功能）

### 6. image_downloader.py
- [x] 基本不用改，通用下载工具
- [x] 移除视频相关方法（知乎文章不需要视频下载）

### 7. run_lock.py
- [x] 不用改，通用锁工具

### 8. README.md
- [x] 全部重写为知乎版本

### 9. SKILL.md
- [x] 全部重写为知乎文章发布助手

### 10. requirements.txt
- [x] 检查依赖是否需要调整（基本不变）

### 11. .gitignore / LICENSE
- [x] 不用改
