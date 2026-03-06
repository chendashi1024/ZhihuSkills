# 知乎草稿保存功能使用说明

## 功能说明

新增 `save-draft` 命令，可以自动填充内容并保存为草稿，然后返回草稿的编辑链接。

## 使用方法

### 基本用法

```bash
python scripts/cdp_publish.py save-draft --title "文章标题" --content "文章正文"
```

### 从文件读取正文

```bash
python scripts/cdp_publish.py save-draft --title "文章标题" --content-file content.txt
```

### 包含图片

```bash
python scripts/cdp_publish.py save-draft --title "文章标题" --content "正文" --images img1.jpg img2.png
```

## 输出示例

```
[cdp_publish] 正在连接 ws://127.0.0.1:9222/devtools/page/...
[cdp_publish] 已连接到 Chrome 标签页。
[cdp_publish] 正在导航到 https://zhuanlan.zhihu.com/write
[cdp_publish] 正在设置标题: 测试草稿文章...
[cdp_publish] 标题已设置。
[cdp_publish] 正在设置正文 (62 字符)...
[cdp_publish] 正文已设置。

[cdp_publish] 内容已填写完成。请在浏览器中检查后发布。

[cdp_publish] 等待草稿 URL 生成...
[cdp_publish] 草稿链接: https://zhuanlan.zhihu.com/p/2013191591842571097/edit

============================================================
草稿已保存！
============================================================
草稿链接: https://zhuanlan.zhihu.com/p/2013191591842571097/edit
============================================================

DRAFT_URL: https://zhuanlan.zhihu.com/p/2013191591842571097/edit
```

## 草稿链接说明

- 草稿链接格式: `https://zhuanlan.zhihu.com/p/{文章ID}/edit`
- 可以直接在浏览器中打开此链接继续编辑
- 草稿会自动保存在知乎账号中
- 可以稍后手动发布或继续编辑

## 与其他命令的区别

| 命令 | 功能 | 是否发布 | 返回链接 |
|------|------|---------|---------|
| `fill` | 填充内容 | ❌ | ❌ |
| `save-draft` | 填充内容并保存草稿 | ❌ | ✅ |
| `publish` | 填充内容并发布 | ✅ | ❌ |

## 注意事项

1. **草稿自动保存**: 知乎会自动保存草稿，无需手动点击保存���钮
2. **URL 生成**: 脚本会等待知乎生成草稿 URL（最多等待 5 秒）
3. **发布按钮**: 草稿中的发布按钮仍然是禁用状态，需要手动输入字符后才能发布
4. **编辑链接**: 返回的链接是编辑页面，可以直接打开继续编辑

## 编程接口

```python
from cdp_publish import ZhihuPublisher

publisher = ZhihuPublisher()
publisher.connect()

# 填充内容
publisher.publish(
    title="文章标题",
    content="文章正文",
    image_paths=["img1.jpg"]  # 可选
)

# 获取草稿链接
draft_url = publisher.get_draft_url()
print(f"草稿链接: {draft_url}")

publisher.disconnect()
```

## 工作流程建议

### 方案 1: 保存草稿后手动发布

```bash
# 1. 保存草稿
python scripts/cdp_publish.py save-draft --title "标题" --content "正文"

# 2. 在浏览器中打开返回的链接

# 3. 手动输入一个字符（如空格）

# 4. 手动点击发布按钮
```

### 方案 2: 批量保存草稿

```bash
# 保存多篇草稿
for file in content/*.txt; do
    title=$(basename "$file" .txt)
    python scripts/cdp_publish.py save-draft \
        --title "$title" \
        --content-file "$file"
done
```

## 故障排除

### 问题: 无法获取草稿链接

**原因**: URL 生成超时

**解决**:
- 检查网络连接
- 确认已登录知乎
- 手动刷新页面后重试

### 问题: 草稿内容丢失

**原因**: 知乎自动保存失败

**解决**:
- 确保网络稳定
- 等待几秒后刷新页面
- 重新运行 save-draft 命令

---

**更新日期**: 2026-03-06
