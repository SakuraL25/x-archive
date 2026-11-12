"""Build <screen> markdown from out/tweets.jsonl (posts only, chronological)."""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN, X_ARCHIVE_DIR as DEST_DIR, POSTS as JSONL  # noqa: E402
TZ = timezone(timedelta(hours=8))
GAPS = [("2020-10-10", "2021-05-01"), ("2021-06-27", "2021-10-01"),
        ("2021-11-11", "2021-11-24"), ("2022-01-10", "2022-03-31")]


def load():
    recs = {}
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if (r.get("author") or "").lower() != SCREEN.lower():
                continue
            if not r.get("ts"):
                continue
            recs[r["id"]] = r
    return list(recs.values())


def local(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).astimezone(TZ)


def fmt(n):
    n = int(n or 0)
    if n >= 10000:
        return f"{n / 1000:.1f}k"
    return str(n)


def clean(t):
    t = (t or "").replace("\r\n", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def media_block(rec):
    out = []
    imgs = [m for m in rec["media"] if m["type"] == "photo"]
    vids = [m for m in rec["media"] if m["type"] in ("video", "gif")]
    for i, m in enumerate(imgs, 1):
        cap = f"图 {i}/{len(imgs)}" if len(imgs) > 1 else "图"
        out.append(f"![{cap}]({m['url']})")
        if m.get("alt"):
            out.append(f"*{m['alt']}*")
        out.append("")
    for m in vids:
        dur = m.get("duration_ms")
        kind = "GIF" if m["type"] == "gif" else "视频"
        secs = f"（{dur / 1000:.1f} 秒）" if dur else ""
        out.append(f"*（含{kind}{secs}，按要求未收录）*")
    if vids:
        out.append("")
    return out


def quote_block(q):
    if not q:
        return []
    who = f"@{q.get('author')}" if q.get("author") else "引用帖"
    when = local(q["ts"]).strftime("%Y-%m-%d") if q.get("ts") else ""
    out = [f"> **引用 {who}**{(' · ' + when) if when else ''}", ">"]
    body = clean(q.get("text"))
    for ln in (body.split("\n") if body else ["（无文字）"]):
        out.append("> " + ln if ln.strip() else ">")
    for m in q.get("media") or []:
        out.append(f"> ![{m['type']}]({m['url']})")
    return out


def in_gap(d):
    day = d.strftime("%Y-%m-%d")
    return any(a <= day <= b for a, b in GAPS)


def render(recs):
    recs.sort(key=lambda r: (r["ts"], int(r["id"])))
    imgs = sum(1 for r in recs for m in r["media"] if m["type"] == "photo")
    vids = sum(1 for r in recs for m in r["media"] if m["type"] in ("video", "gif"))
    quotes = sum(1 for r in recs if r.get("quoted"))
    media_posts = sum(1 for r in recs if r["media"])
    first = local(recs[0]["ts"]).strftime("%Y-%m-%d")
    last = local(recs[-1]["ts"]).strftime("%Y-%m-%d")
    months = {}
    for r in recs:
        months.setdefault(local(r["ts"]).strftime("%Y-%m"), []).append(r)

    p = [f"# @{SCREEN} 推文归档（原创帖）\n"]
    p.append(
        f"> 账号：https://x.com/{SCREEN}  \n"
        f"> 覆盖：{first} → {last}（北京时间）  \n"
        f"> 共 **{len(recs)}** 条原创帖（不含转推）｜带图 {media_posts} 条（图片 {imgs} 张，视频/GIF {vids} 个按要求未收录）｜引用帖 {quotes} 条  \n"
        f"> 他发给别人的回复不在这里，见同目录 `{SCREEN.lower()}_replies.md`；"
        f"两者合并的完整时间线见 `{SCREEN.lower()}_timeline.md`  \n"
        f"> 抓取：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}，登录态 X GraphQL（UserTweets 全量 + 按时间窗回溯补漏）  \n"
        f"> 阅读：时间升序；每帖含正文 → 引用 → 媒体直链 → 互动数据与原帖链接\n"
    )
    p.append("## 目录\n")
    for ym, rs in months.items():
        p.append(f"- [{ym}](#m{ym.replace('-', '')}) — {len(rs)} 条")
    p.append("")
    p.append("## 数据说明\n")
    p.append(
        "X 网页端「帖子」只保留最近约 3 年可直接翻页的窗口，更早的旧帖只能通过搜索时间窗挖回来，"
        "因此本归档在下列时间段存在缺口（博主发帖极少或已被 X 索引丢弃）：\n"
        + "\n".join(f"- {a} → {b}" for a, b in GAPS)
        + "\n\n另外，下列月份条数明显偏少（个位数），同样可能是这段时间发帖稀疏、不是抓漏：\n"
        + "2023-11、2023-12、2024-08、2024-09、2025-01 ~ 2025-05、2025-11、2025-12、2026-06、2026-08。\n\n"
        "补漏方法：X 搜索每页只返回 20 条且没有 `until_id`，因此用 `max_id` 按 ID 窗口逐步回溯"
        "（脚本 `D:\\tmp\\xdl\\exhaust4.py`，环境变量 `START_AT=YYYY-MM-DD` 指定起点），"
        "或者在页面里按日期区间补。所有原始记录追加在 `tweets.jsonl`，可用 `build_md.py` 重出本文件。\n"
    )

    cur = None
    for r in recs:
        dt = local(r["ts"])
        ym = dt.strftime("%Y-%m")
        if ym != cur:
            cur = ym
            p.append(f'\n<a id="m{ym.replace("-", "")}"></a>\n')
            p.append(f"## {dt.strftime('%Y 年 %m 月')}\n")
            if in_gap(dt):
                pass
        p.append(f"### {dt.strftime('%Y-%m-%d %H:%M')}\n")
        body = clean(r.get("text"))
        if body:
            p.append(body + "\n")
        if r.get("quoted"):
            p.extend(quote_block(r["quoted"]))
            p.append("")
        p.extend(media_block(r))
        stats = (f"❤ {fmt(r['likes'])} · 🔁 {fmt(r['retweets'])} · 💬 {fmt(r['replies'])}"
                 f" · 🔖 {fmt(r['bookmarks'])} · 👁 {fmt(r['views'])}")
        p.append(f"{stats} · [原帖 ↗]({r['url']})\n")
    return "\n".join(p).rstrip() + "\n"


def main():
    recs = load()
    if not recs:
        raise SystemExit("no records")
    # A reply he sends to someone else still shows on his profile timeline, so the
    # UserTweets harvest picked up 269 of them; they live in the replies archive
    # now.  Replies to his *own* posts (26) are thread continuations and stay.
    own_ids = {r["id"] for r in recs}
    dropped = [r for r in recs
               if r.get("reply_to") and r["reply_to"] not in own_ids]
    recs = [r for r in recs
            if not r.get("reply_to") or r["reply_to"] in own_ids]
    print(f"dropped {len(dropped)} replies to others "
          f"(kept in {SCREEN.lower()}_replies.md)")
    os.makedirs(DEST_DIR, exist_ok=True)
    md = render(recs)
    path = os.path.join(DEST_DIR, f"{SCREEN.lower()}_full.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    years = Counter(local(r["ts"]).year for r in recs)
    meta = {
        "screen_name": SCREEN,
        "profile": f"https://x.com/{SCREEN}",
        "posts": len(recs),
        "first_local": local(min(r["ts"] for r in recs)).isoformat(),
        "last_local": local(max(r["ts"] for r in recs)).isoformat(),
        "per_year": dict(sorted(years.items())),
        "images": sum(1 for r in recs for m in r["media"] if m["type"] == "photo"),
        "videos": sum(1 for r in recs for m in r["media"] if m["type"] in ("video", "gif")),
        "quotes": sum(1 for r in recs if r.get("quoted")),
        "posts_with_media": sum(1 for r in recs if r["media"]),
        "md_chars": len(md),
        "gaps": [dict(zip(("from", "to"), g)) for g in GAPS],
        "source": "X GraphQL UserTweets + until-walk SearchTimeline backfill",
        "generated": datetime.now(TZ).isoformat(),
    }
    with open(os.path.join(DEST_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    recs.sort(key=lambda r: r["ts"])
    with open(os.path.join(DEST_DIR, "tweets.jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()