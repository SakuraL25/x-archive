# x-archive

把某个 X（推特）博主的**全部推文**归档成 LLM wiki 可用的 raw 资料：原创 + 回复 + 父帖链，按月分卷成 Markdown，另附可追溯的整理稿。

> 这是一个 **Agent Skill**（`SKILL.md` + `scripts/`）。把整个目录放进 agent 的 skills 目录即可被自动发现，例如
> `~/.agents/skills/x-archive/`（DeepSeek Harness / Claude Code 风格）。

## 它做什么

```
x.com/<博主>
   │  ① 原创帖（UserTweets）
   │  ② 3 年窗口外的补漏（SearchTimeline since/until 回溯）
   │  ③ 回复全量（时间窗二分，绕过每查询 20 条上限）
   │  ④ 父帖原文（免登录 syndication 接口，不占 GraphQL 配额）
   ▼
整理稿 <X_ARCHIVE_DIR>/     timeline.jsonl（唯一真源，行序即全局 #N）
                                tweets.jsonl / replies.jsonl / context.jsonl / chain.jsonl
                                + 三份可读 md + meta
   ▼  ⑤ build_raw.py（自带逐字自检，失败不落库）
raw 月卷 <wiki>/raw/人物/<人物目录>/推特/YYYY-MM.md   ×  ~50 卷
```

## 产出长什么样

```markdown
### 2026-11-01 00:05  ·  #2201

**回复 @somebody** · 原帖 2026-10-31 23:43 · [↗](https://x.com/somebody/status/…)

**（原帖正文 · @somebody · 他人言论，非 <人名> 的话）**

别人说的话，原样保留

**→ <人名>：**

他的回复正文

![图](https://pbs.twimg.com/media/….jpg)
```

- `#N` 全局序号与整理稿一一对应 —— 卷内**不写互动统计、不写单帖链接**，溯源统一靠 `#N`。
- 他人的话一律用独占行的粗体标签隔开，**不用 `>` 引用块**（`verify_quotes.py` 的标点归一化不摘 `>`，会导致跨行引文定位失败）。
- 图片保留远程直链（不下载）；视频默认不收录，只留 `*（含视频 n 个，未收录）*`。

## 快速开始

```bash
set TARGET_SCREEN_NAME=SomeUser
set XDL_ROOT=D:\tmp\xdl-SomeUser
set X_ARCHIVE_DIR=D:\data\x\SomeUser
set X_PERSON_DIR=1 某某（ICT）        # 转 raw 时需要：wiki 里的人物目录名

# 登录态：开 Edge 调试实例登录 x.com，再导出 cookie
node scripts/edge_dump_cookie.mjs     # → <XDL_ROOT>/raw_cookie.txt
python scripts/write_cookies_from_raw.py  # → cookies.txt

python scripts/harvest.py             # 原创
python scripts/walk_back.py           # 补漏
python scripts/harvest_replies2.py    # 回复
python scripts/fill_syndication.py    # 父帖
python scripts/build_md.py
python scripts/build_replies_md.py
python scripts/build_timeline_md.py
python scripts/build_raw.py           # 转 raw（内置自检）
```

依赖：Python 3.12+、`gallery-dl`、`httpx`；需要一个能访问 X 的代理（默认 `http://127.0.0.1:10090`）。

## 环境变量

| 变量 | 必填 | 默认 |
|---|---|---|
| `TARGET_SCREEN_NAME` | ✅ | – |
| `XDL_ROOT` | | `D:\tmp\xdl-<screen>` |
| `X_ARCHIVE_DIR` | | `<资料根>/x/<screen>` |
| `WIKI_ROOT` | | –（转 raw 时必设） |
| `X_PERSON_DIR` | 转 raw 时 | – |
| `X_PROXY` | | `http://127.0.0.1:10090` |

## ⚠️ 凭证

`raw_cookie.txt` / `cookies.txt` 等价于账号登录态，已在 `.gitignore` 中排除。**不要**把它们提交、打包或分享。

## 踩过的坑

都写在 `SKILL.md` 的「已知坑」里，包括：UserTweets 只覆盖约 3 年、SearchTimeline 翻页第二页即死、`max_id` 必须写进 rawQuery、`tweet_detail()` 返回整段对话、syndication 免登录接口、queryId 会漂移、raw 里禁用引用块等。

## 许可

个人使用；引用的推文内容版权归原作者。
