# kisssub.org(爱恋动漫)→ MoviePilot v2 站点适配

把 [kisssub.org](https://www.kisssub.org/)(爱恋动漫,自研程序 **MioBT**)接入 MoviePilot v2。

MoviePilot 内建站点列表(闭源 `user.sites.v2.bin`)不含 kisssub,且添加站点时强制校验域名必须在索引器列表内(否则提示"该站点不支持"),因此需要一个**自定义索引器注入插件 + 本站点的索引器模板**。本仓库两者都已备好:

```
kisssub-moviepilot/          ← 本仓库同时是标准插件市场仓库(package.v2.json 位于根目录)
├── README.md                ← 本说明
├── package.v2.json
├── kisssub_indexer.json     ← 索引器模板(选择器已按真实页面结构编写)
├── paste_config.txt         ← 插件里要粘贴的一行配置(域名|base64)
└── plugins.v2/customindexersite/__init__.py
```

官方原版 `customindexer` 插件只适配 MoviePilot v1,本仓库的 `customindexersite` 是按 v2.15.x 插件基类(`_PluginBase`)适配的等价实现,核心同样是调用 `SitesHelper().add_indexer(域名, 索引配置)`。

---

## 一、安装插件(两种方式任选)

### 方式 A:本地插件仓库(推荐,可从插件市场正常安装/卸载)

1. 把本仓库克隆/下载到能被 MoviePilot 容器读到的位置(需保证 `package.v2.json` 在目录根),例如挂载 `./kisssub-moviepilot:/mp-plugins-local`。
2. 给 MoviePilot 增加环境变量:

   ```yaml
   PLUGIN_LOCAL_REPO_PATHS: /mp-plugins-local
   ```

3. 重启 MoviePilot → `插件` → `插件市场`(本地仓库来源)→ 安装 **自定义索引站点**。

### 方式 B:直接放入插件目录

把 `plugins.v2/customindexersite/` 整个文件夹拷入容器内 `/app/plugins/customindexersite/`,重启 MoviePilot 即可(MP v2 从 `app/plugins` 加载插件)。

### 方式 C:插件市场在线安装(最省事)

在 MoviePilot `设定 → 系统 → 插件市场` 中确认已包含本仓库地址 `https://github.com/xieqiong111/kisssub-moviepilot`,刷新插件市场后直接安装 **自定义索引站点**。

## 二、配置插件

`插件 → 自定义索引站点 → 启用`,在"站点索引配置"中粘贴 `paste_config.txt` 的整行内容:

```
kisssub.org|<JSON 的 base64,见 paste_config.txt>
```

保存。日志中应出现 `自定义索引站点已加载:kisssub.org(爱恋动漫)`。

> 修改了 `kisssub_indexer.json` 后,重新生成 base64 再更新插件配置:
> `python -c "import base64;print(base64.b64encode(open('kisssub_indexer.json','rb').read()).decode())"`

## 三、添加站点

`站点管理 → 新增站点`:

| 项 | 值 |
|---|---|
| 站点地址 | `https://www.kisssub.org/` |
| Cookie | **必须包含 `visitor_test=human`**。最简单:用浏览器打开 kisssub.org 点击一次人机验证,登录后 F12 → Application → Cookies 全选复制(含 visitor_test、uid 等) |
| User-Agent | 建议填 Chrome UA(模板里已内置同款兜底) |

添加后即可在"搜索/订阅/刷流"中正常使用。若在浏览器中重新做人机验证导致 `visitor_test` 更新,同步更新站点 Cookie 即可。

## 四、能力与限制(实测结论)

- **搜索**:走 `search.php?keyword={keyword}&page={page}`,单页 50 条,支持翻页、中文/日文关键词(URL 编码)。
- **最新种子刷新**:`browse` 指向首页列表,供"站点刷新/订阅"使用。
- **下载**:enclosure 由详情 hash 拼为 `http://v2.uploadbt.com/?r=down&hash=<infohash>`,实测免 Cookie、HTTP 200、返回真实 .torrent。(站点自身 `down.php?date=<时间戳>&hash=` 有精确时间戳防盗链,列表页拿不到时间戳,故不采用。)
- **做种/下载数**:列表页不提供该数据,seeders/leechers/grabs 恒为 0 → 依赖做种数排序、择优的规则对本站无效,其余功能不受影响。
- **免费/上传系数**:站点无 Free/2x/HR 体系,相应字段未配置(默认 1/1)。
- **站点用户数据**(上传量、魔力值、做种量):MioBT 非 NexusPHP,不支持。
- **发布时间**:列表页绝对日期(如 `2026/08/24`)正常解析;首页"今天/昨天 HH:MM"相对时间会被 MP 丢弃(无 pubdate,不影响下载)。
- **访客门**:不带 Cookie 访问会被 302 到人机验证页 → 搜索 0 结果,所以站点 Cookie 必须配置。

## 五、故障排查

1. 搜索 0 结果:九成是 Cookie 缺 `visitor_test=human` 或已过期 → 重抓 Cookie。
2. 添加站点提示"该站点不支持":插件未启用/未保存配置,先看日志有没有"自定义索引站点已加载"。
3. 改了模板不生效:插件保存配置会重新 `add_indexer`,无需重启;若仍不生效则重启 MP。
4. 站点改版导致解析错位:按新页面调整 `kisssub_indexer.json` 的选择器后重新生成 base64。

## 参考

- MoviePilot v2 源码(站点爬虫/字段协议):`app/modules/indexer/spider/__init__.py`(v2 分支)
- 官方 v1 插件出处:[jxxghp/MoviePilot-Plugins `plugins/customindexer`](https://github.com/jxxghp/MoviePilot-Plugins)
- [MoviePilot Wiki 站点管理](https://wiki.movie-pilot.org/site) / [配置参考](https://wiki.movie-pilot.org/configuration)
