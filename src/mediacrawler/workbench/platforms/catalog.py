"""Built-in website metadata, separate from navigation and execution code."""

PLATFORM_TYPES = [dict(id=k, name=n) for k, n in [
    ('video', '视频网站'), ('books', '书籍网站'), ('shopping', '购物网站'),
    ('community', '社区与图文'), ('other', '其他网站'),
]]

TEMPLATES = [
    dict(id='video_capture', name='网页视频捕获', collect=True, video=True, images=False,
         description='发现网页视频资源；预览播放不会下载，开始任务后解析明确关联的视频。',
         fields=[dict(key='selector', label='播放或目录元素选择器（可选）', type='text', default=''),
                 dict(key='wait_ms', label='页面等待时间（毫秒）', type='number', default=5000)]),
    dict(id='preview_only', name='网站预览', collect=False, video=False, images=False,
         description='保存网站配置并打开预览；书籍正文、商品与价格采集模板将在后续接入。', fields=[]),
]

PLATFORMS = []
for key, name, url, modes, comments, images, category, tags, engine in [
    ('meishiwang', '美石建工', 'http://edu.meishiwang100.com', ['detail'], False, False, 'video', ['课程'], 'course'),
    ('generic', '通用网页', '', ['detail'], False, False, 'other', [], 'video_capture'),
    ('bili', 'Bilibili', 'https://www.bilibili.com', ['detail', 'search', 'creator'], True, False, 'video', [], 'platform'),
    ('xhs', '小红书', 'https://www.xiaohongshu.com', ['search', 'detail', 'creator'], True, True, 'community', ['图文', '视频'], 'platform'),
    ('dy', '抖音', 'https://www.douyin.com', ['search', 'detail', 'creator'], True, True, 'video', [], 'platform'),
    ('ks', '快手', 'https://www.kuaishou.com', ['search', 'detail', 'creator'], True, False, 'video', [], 'platform'),
    ('wb', '微博', 'https://weibo.com', ['search', 'detail', 'creator'], True, True, 'community', ['图文', '视频'], 'platform'),
    ('tieba', '百度贴吧', 'https://tieba.baidu.com', ['search', 'detail', 'creator'], True, False, 'community', [], 'platform'),
    ('zhihu', '知乎', 'https://www.zhihu.com', ['search', 'detail', 'creator'], True, False, 'community', [], 'platform'),
]:
    PLATFORMS.append(dict(id=key, name=name, url=url, inputs=modes, comments=comments,
        images=images, video=True, media=True, media_modes=modes, video_modes=modes,
        outputs=['jsonl', 'json', 'csv', 'excel'], category=category, tags=tags,
        builtin=True, enabled=True, legacy=False, collect=True,
        template=engine, template_config={}, video_strategy='adapter_and_capture' if engine != 'video_capture' else 'capture',
        verification='requires_live_validation'))

# Preserve the old media flag's availability and meaning for existing integrations.
LEGACY_MEDIA_MODES = {
    'meishiwang': ['detail'], 'generic': ['detail'], 'bili': ['detail', 'search', 'creator'],
    'xhs': ['search', 'detail', 'creator'], 'dy': ['search', 'detail', 'creator'], 'wb': ['search'],
}
