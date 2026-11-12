---
name: x-archive
description: "把某个 X（推特）博主的全部帖子归档成 LLM wiki 可用 raw（原创 + 回复 + 父链，分月卷 md + 整理稿 jsonl/md）。只要消息里出现 x.com 或 twitter.com 的用户链接（x.com/<screen-name>）并提到「归档 / 抓下来 / 全量 / 所有帖子 / 转 raw / 进 wiki / 他的推特」，或屏幕名 + 「搬进知识库 / 整理进 raw」，就默认自动使用本 skill，不需要用户 @ 或点名。输出到 <WIKI_ROOT>/raw/人物/<人物目录>/推特/ 的月卷 + <X_ARCHIVE_DIR>/ 整理稿。需要登录态 cookie（Edge 登录一次）。"
description_en: "Archive an X (Twitter) user's entire timeline (posts + replies + parent chains) into llm-wiki raw month volumes; auto-triggers on x.com/<user> links with archive intent."
agent_created: true
---

# X 博主全量归档（→ llm-wiki raw）

把 `@<screen>` 的**全部推文**（原创 + 对别人的回复，含父帖原文与引用帖）落成：
1. **整理稿** `<X_ARCHIVE_DIR>/`：`timeline.jsonl`（唯一真源，行序即全局 `#N`）+ `tweets.jsonl`（原创）+ `replies.jsonl`（回复）+ `context.jsonl`/`chain.jsonl`（父链缓存）+ 三份 md（full/replies/timeline）+ `meta*.json`
2. **raw 月卷** `<WIKI_ROOT>/raw/人物/<人物目录>/推特/YYYY-MM.md`（卷格式见 llm-wiki-special「二」的 X 归档段，**引用它，不要另立规则**）

> **默认自动**：看到 `x.com/<名字>` + 归档意图，直接开工，不要问「要不要用这个 skill」。
> **先做身份对接**（见下）：确认这个 X 号 = wiki 里哪个人物目录；对不上就停下来问，别盲建目录。

## 前置

- 依赖：Python 3.12 venv，装 `gallery-dl httpx`（抓取脚本用）；无第三方依赖的 Python 也行（build_* / 转换脚本）。
- 代理：默认 `http://127.0.0.1:10090`（env `X_PROXY` 覆盖）。**没代理跑不通**。
- **登录 cookie 是关键**（gallery-dl 抓 UserTweets/Search 必须登录态）：
  - 开一个**临时 Edge 调试实例**：`msedge --user-data-dir=D:/tmp/xedge --remote-debugging-port=9335`，在里面登录 x.com（可能要手动输一次验证码）。
  - `node scripts/edge_dump_cookie.mjs`（CDP 读 cookie）→ 写 `<XDL_ROOT>/raw_cookie.txt`。
  - `python scripts/write_cookies_from_raw.py` → 生成 `cookies.txt`（Netscape 格式）。
  - **凭证警告**：`cookies.txt` / `raw_cookie.txt` 等价于账号登录态，**绝不打包、分享、提交**（`.gitignore` 已排除）；过期就重新导出（auth_token 约一年效期）。
- 长跑任务用 `cscript //nologo scripts/launch.vbs <脚本>.py [K=V ...]` 脱离启动，日志在 `scripts/<脚本>.log`（绕开 shell 执行器超时/会话回收）。

## 环境变量（xconf.py 统一读）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `TARGET_SCREEN_NAME` | ✅ | – | 博主 screen name，不带 @（如 `SomeTrader`） |
| `XDL_ROOT` | | `<工作区>/xdl-<screen>` | 工作区（out/*.jsonl、cookies、日志） |
| `X_ARCHIVE_DIR` | | `<资料根>/x/<screen>` | 整理稿目录 |
| `WIKI_ROOT` | | –（转 raw 时必设） | 库根（raw/ 与 wiki/ 的父目录） |
| `X_PERSON_DIR` | 转 raw 时✅ | – | wiki 人物目录名含档位前缀，如 `1 某某（方向）` |
| `X_PERSON_NAME`/`X_PERSON_SHORT` | | 从目录推 | 全名 / 标签简称（默认去前缀去括号） |
| `X_PROXY` | | `http://127.0.0.1:10090` | 代理 |

## 第 0 步：身份对接（新博主必做）

把 X 号对到 wiki 已有的人物目录，**凭据写进 `_README.md`**：
1. 翻他最近推文，找自曝的其他平台链接（YouTube / B 站 space / 公众号）。
2. B 站：`https://api.bilibili.com/x/web-interface/view?bvid=<BV>` 返回 `owner.mid`/`owner.name`，与库里 `raw/人物/<人>/视频/` 的 `source` 对照。
3. 对上就落库；对不上（或库中无此人）→ 告诉用户你判成哪个目录/要不要新建，**等确认再写库**。

## 抓取流程（按序，每步可断点续跑）

```bash
# 已设好 env 后（Windows cmd）：
set TARGET_SCREEN_NAME=xxx
set XDL_ROOT=D:\tmp\xdl-xxx
set X_ARCHIVE_DIR=D:\data\x\xxx
set X_PERSON_DIR=1 某某（...）

# 1) 原创帖（UserTweets，gallery-dl）
python scripts/harvest.py

# 2) 3 年窗口补漏（SearchTimeline since/until 回溯）——UserTweets cursor 只覆盖约 3 年
python scripts/walk_back.py

# 3) 回复全量（时间窗二分）
python scripts/harvest_replies2.py

# 4) 父帖原文（免登录 syndication 接口，主力批量）
python scripts/fill_syndication.py
#    再补链上二层祖先（可选，chain 深挖）
python scripts/fill_ancestors.py

# 5) 整理稿三件（full / replies / timeline）
python scripts/build_md.py
python scripts/build_replies_md.py
python scripts/build_timeline_md.py

# 6) 转 raw 月卷（见下，含内置逐字自检）
python scripts/build_raw.py
```

**限流事实**（实战测得，别浪费窗口）：
- 搜索类 GraphQL（SearchTimeline）约 **50 请求/15 分钟**；TweetDetail 更紧。脚本已带 sleep-429，慢但稳。
- SearchTimeline：**cursor 翻页第二页即死**，且 `max_id` **必须写进 rawQuery**（variables 里无效）；`until_id` 参数不存在；结果每查询 **≤20 条** → 时间窗二分，窗内 <17 条（SAT）即认定完整。
- `api.tweet_detail()` 返回**整个对话流**的 generator，**第一个元素是对话根帖不是目标帖** → 必须遍历全量按各自 `rest_id` 入库。
- `cdn.syndication.twimg.com/tweet-result?id=<id>&token=a&lang=zh` 免登录不占配额，回复父帖的批量补全走它。
- queryId（`/graphql/<hash>/UserTweets` 等）会随 X 更换失效 → 报错先升级 gallery-dl 或从页面 Network 重取。

## 转 raw（build_raw.py）

输入 = `<X_ARCHIVE_DIR>/timeline.jsonl`（**唯一真源，行序即全局 `#N`**）+ `tweets.jsonl`（判「续自己的帖」）+ `<XDL_ROOT>/out/context.jsonl`/`chain.jsonl`（父帖）。

- 输出 = `<WIKI_ROOT>/raw/人物/<X_PERSON_DIR>/推特/YYYY-MM.md`（几十卷，逐月） + `<XDL_ROOT>/raw_check.json`。
- **自带逐字自检**：每条正文 + 父帖/引用帖文字按 verify_quotes 的 PUNC 归一化后在对应月卷 `find()`，**失败即 exit 2 不写库**（现场留在 `scripts/rawdbg/`）。
- 覆盖判据与格式**引用 llm-wiki-special「二」**：`### YYYY-MM-DD HH:MM  ·  #N`、独占行粗体标签（`**原创**`/`**回复 @人**`/`**（原帖正文 · 他人言论）**`/`**→ 简称：**`）、**不用 `> ` 引用块**（verify PUNC 不摘 `>`，坑 29）、**卷内不写互动统计行与单帖链接**（溯源靠 `#N` 回查整理稿）。
- 图片留 `![图](https://pbs.twimg.com/…)` 远程直链不下载；视频默认不收录只留 `*（含视频 n 个，未收录）*`。

## 收尾（库侧，每一步都要做）

1. 结构校验：各月卷 `#N` 集合 = `{1..总共}` 无缺无重；每月条数 = `meta_timeline.json.per_month`；frontmatter 能被 `_common.parse_frontmatter` 解析。
2. 库侧三件套：`lint.py --summary-only`（硬项 0）、`verify_quotes.py --no-timestamps`（可定位通过率 100%）、`audit.py --root`（alias_conflict/self_link/dangling_link = 0）。
3. `raw_coverage.py --root <WIKI_ROOT>`（若尚未给新平台目录加 mapping，先补 `category_of()` 的 mapping 行，如 `("推特", "X推文")`）。
4. wiki 规范文档回写：平台目录清单 + changelog + SCHEMA raw 组织表补平台目录。
5. `snapshot.py create --root <WIKI_ROOT>` + git add/commit（若 vault 有自动提交 bot，**只 add 涉及路径，绝不整目录回滚**）。

## 已知坑（全部实战踩过）

- UserTweets 只给约 3 年 → 老推文靠 `since:`/`until:` 搜索回溯（walk_back）。
- 搜索翻页 cursor 第二页即死 → 永不依赖翻页，直接时间窗二分。
- `max_id` 只在 rawQuery 生效 → 写错地方表现为「永远拿到同一批 20 条」。
- tweet_detail 返回整段对话 → 逐条按 id 入库，别只取第一条。
- syndication 接口 → 无 cookie 无配额，父帖批量补全首选（GraphQL 一小时 ~900 条，它几分钟）。
- verify_quotes PUNC 不摘 `>` → raw 禁用引用块（详见 llm-wiki-special 坑 29）。
- 回复互动数接口不返回 → raw 卷不写统计行。
- 超长抓取（回复回溯可能数小时）→ `cscript launch.vbs` 脱离跑，日志落文件。
- 视频下载默认关闭（脚本里已配好；用户要视频另议）。

## 工作流与输出

完成后用中文向用户汇报：身份对接结论（为什么这个 X 号 = 这个人物目录）、条数（原创/回复/转推/引用/图片）、覆盖时间范围、父帖获取率（x/n）、校验三件套数字、提交 hash、下个会话 skill 才在目录里出现（本会话 catalog 是启动时固定的）。

## 改动记录

### 2026-11-12 · 从一个 X 博主全量归档实战沉淀成 skill

- 素材：某博主全量抓取（2020-10→2026-11，50 月卷 / 2,349 条 / 878 图）走通后的整套脚本与坑。
- 脚本：harvest/walk_back/harvest_replies2/fill_syndication/fill_ancestors/build_md/build_replies_md/build_timeline_md/build_raw + 两个 cookie 脚本，统一参数化（xconf.py 读 env；硬编码 screen/路径全清）。
- 回归：参数化 build_raw 以同一博主的既有数据重跑，产出与库内 50 卷逐字节一致（仅 `created` 日期推进）。
- 触发：x.com/<user> + 归档意图自动启用；需要 cookie（Edge 登录一次）。
