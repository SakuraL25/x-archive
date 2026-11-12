"""Merge his original posts and his replies into one chronological timeline.

Input
    out/tweets.jsonl     his original posts (harvest.py)
    out/replies.jsonl    his replies      (harvest_replies2.py)
    out/context.jsonl    parent posts of replies (harvest_ctx.py)
    out/chain.jsonl      the rest of the reply chains (harvest_chain.py)

Output
    <X_ARCHIVE_DIR>/<screen>_timeline.md
    <X_ARCHIVE_DIR>/timeline.jsonl
    <X_ARCHIVE_DIR>/meta_timeline.json

Each entry is marked 【原创】 or 【回复 @xxx】; replies repeat the post they answer
so the thread reads in order. Posts that later receive his own reply carry a
「↩ 本期之后 n 条回复」 back-reference, which links split-off thoughts together.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN, X_ARCHIVE_DIR as DEST_DIR, OUT, POSTS, REPLIES, CTX, CHAIN  # noqa: E402
TZ = timezone(timedelta(hours=8))



def read_jsonl(path):
    recs = {}
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("id") and r.get("ts"):
                recs[r["id"]] = r
    return recs


def local(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).astimezone(TZ)


def clean(t):
    t = (t or "").replace("\r\n", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def fmt(n):
    n = int(n or 0)
    return f"{n / 1000:.1f}k" if n >= 10000 else str(n)


def media_lines(rec, prefix=""):
    out = []
    imgs = [m for m in (rec.get("media") or []) if m["type"] == "photo"]
    vids = [m for m in (rec.get("media") or []) if m["type"] in ("video", "gif")]
    for i, m in enumerate(imgs, 1):
        cap = f"图 {i}/{len(imgs)}" if len(imgs) > 1 else "图"
        out.append(f"{prefix}![{cap}]({m['url']})")
    return out


def entry_id(rec):
    return rec["id"]


def main():
    posts = read_jsonl(POSTS)
    replies = read_jsonl(REPLIES)
    ctx = read_jsonl(CTX)
    chain = read_jsonl(CHAIN)

    # only keep his own content; a reply must not appear twice (once as a
    # "post" captured from his profile timeline, once as a reply)
    items = []
    replied_ids = set(replies)
    own_ids = set(posts)
    dup = 0
    for r in posts.values():
        if (r.get("author") or "").lower() != SCREEN.lower():
            continue
        # a tweet that answers somebody else is filed as a reply, not as a post
        if r["id"] in replied_ids and (r.get("reply_to") or "") not in own_ids:
            dup += 1
            continue
        items.append({"kind": "post", "rec": r})
    kept_ids = {it["rec"]["id"] for it in items}
    for r in replies.values():
        if (r.get("author") or "").lower() != SCREEN.lower():
            continue
        # already rendered from the post stream above
        if r["id"] in kept_ids:
            continue
        items.append({"kind": "reply", "rec": r})
    print(f"posts kept {sum(1 for i in items if i['kind'] == 'post')}, "
          f"replies {sum(1 for i in items if i['kind'] == 'reply')}, "
          f"duplicates dropped {dup}")
    items.sort(key=lambda x: (x["rec"]["ts"], int(x["rec"]["id"])))

    # how many of his own replies hang under each post
    reply_under = Counter()
    for it in items:
        # a self-thread continuation now renders as a post, but it still hangs
        # under its parent, so count every item that answers one of his posts
        pid = it["rec"].get("reply_to")
        if pid and pid in own_ids:
            reply_under[pid] += 1

    table = {}
    table.update(chain)
    table.update(ctx)
    table.update(posts)

    def reply_count_to(post_id):
        rec = table.get(post_id)
        return reply_under.get(post_id, 0)

    lens = [len(clean(it["rec"].get("text"))) for it in items]
    months = {}
    for it in items:
        months.setdefault(local(it["rec"]["ts"]).strftime("%Y-%m"), []).append(it)
    first = local(items[0]["rec"]["ts"]).strftime("%Y-%m-%d")
    last = local(items[-1]["rec"]["ts"]).strftime("%Y-%m-%d")
    n_post = sum(1 for it in items if it["kind"] == "post")
    n_reply = len(items) - n_post
    imgs = sum(1 for it in items for m in (it["rec"].get("media") or [])
               if m["type"] == "photo")
    with_media = sum(1 for it in items if it["rec"].get("media"))
    threaded = sum(1 for it in items if it["kind"] == "reply"
                   and reply_count_to(it["rec"].get("reply_to")))

    p = [f"# @{SCREEN} 全量时间线（原创 + 回复）\n"]
    p.append(
        f"> 账号：https://x.com/{SCREEN}  \n"
        f"> 覆盖：{first} → {last}（北京时间）  \n"
        f"> 共 **{len(items)}** 条：原创 **{n_post}** · 回复 **{n_reply}**"
        f"｜带图 {with_media} 条（图片 {imgs} 张）"
        f"｜正文合计 {sum(lens):,} 字符（平均 {sum(lens) // max(len(lens), 1)}）  \n"
        f"> 生成：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}，"
        f"由 tweets.jsonl + replies.jsonl 合并、按时间升序  \n"
        f"> 读法：【原创】= 他发的推；【回复 @人】= 他在别人帖子下的回复，"
        f"先引原帖再写他的话；出现「↩ 之后 n 条回复」表示这条被他后来回复过  \n"
        f"> 视频/GIF 未收录（按你的要求跳过）  \n"
    )
    p.append("## 目录\n")
    for ym, its in months.items():
        p.append(f"- [{ym}](#t{ym.replace('-', '')}) — {len(its)} 条")
    p.append("")

    p.append("## 说明\n")
    p.append(
        f"原创帖来自 `UserTweets` + `SearchTimeline` 补漏；回复来自 `from:{SCREEN} "
        "filter:replies` 的时间窗二分回溯（窗口内不足 17 条即认定完整）。"
        "两者都受 X 网页端的索引限制：2021 年中、2022 年初、2024-10～2025-10 "
        "的稀疏是他本人发得少，不是抓漏。\n"
    )
    p.append(
        "回复里的「上下文原帖」补齐到最多 3 层父链（先走 GraphQL TweetDetail，"
        "再走免登录的 cdn.syndication 单帖接口，后者不受配额限制）；"
        "显示为「原文已不可见」的是原作者删帖或用了受限账号，X 只回空壳。\n"
    )

    cur = None
    idx = 0
    for it in items:
        rec = it["rec"]
        dt = local(rec["ts"])
        ym = dt.strftime("%Y-%m")
        if ym != cur:
            cur = ym
            p.append(f'\n<a id="t{ym.replace("-", "")}"></a>\n')
            p.append(f"## {dt.strftime('%Y 年 %m 月')}\n")
        idx += 1
        p.append(f"### {dt.strftime('%Y-%m-%d %H:%M')}  ·  #{idx}\n")
        if it["kind"] == "post":
            tag = "【原创】"
            if rec.get("reply_to") in own_ids:
                tag = "【原创 · 续贴】"
            elif rec.get("is_quote") and rec.get("quoted"):
                tag = "【原创 · 引用】"
            p.append(f"**{tag}**\n")
        else:
            who = rec.get("reply_to_user") or "?"
            pid = rec.get("reply_to")
            src = table.get(pid)
            head = f"**【回复 @{who}】**"
            if src:
                when = local(src["ts"]).strftime("%Y-%m-%d %H:%M")
                head += f" · 原帖 {when} · [↗]({src['url']})"
            p.append(head + "\n")
            if src:
                p.append("> 原帖正文：")
                body = clean(src.get("text"))
                for ln in (body.split("\n") if body else ["（无文字）"]):
                    p.append(("> " + ln) if ln.strip() else ">")
                p.append("")
            else:
                p.append(f"> 原文已不可见（{pid}）\n")
        body = clean(rec.get("text"))
        p.append((body or "（无文字）") + "\n")
        q = rec.get("quoted") or {}
        if q.get("id") and clean(q.get("text")):
            p.append(f"> 引用 @{q.get('author') or '?'}：")
            for ln in clean(q.get("text")).split("\n"):
                p.append(("> " + ln) if ln.strip() else ">")
            p.append("")
        ml = media_lines(rec)
        if ml:
            p.extend(ml)
            p.append("")
        stats = (f"❤ {fmt(rec.get('likes'))} · 🔁 {fmt(rec.get('retweets'))}"
                 f" · 💬 {fmt(rec.get('replies'))} · 🔖 {fmt(rec.get('bookmarks'))}"
                 f" · 👁 {fmt(rec.get('views'))}")
        back = ""
        n_back = reply_under.get(rec["id"], 0)
        if n_back:
            back = f" · ↩ 之后 {n_back} 条回复"
        p.append(f"{stats}{back} · [原帖 ↗]({rec['url']})\n")

    md = "\n".join(p).rstrip() + "\n"
    os.makedirs(DEST_DIR, exist_ok=True)
    with open(os.path.join(DEST_DIR, f"{SCREEN.lower()}_timeline.md"), "w", encoding="utf-8") as f:
        f.write(md)

    with open(os.path.join(DEST_DIR, "timeline.jsonl"), "w", encoding="utf-8") as f:
        for it in items:
            rec = dict(it["rec"])
            rec["kind"] = it["kind"]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "screen_name": SCREEN,
        "profile": f"https://x.com/{SCREEN}",
        "total": len(items),
        "posts": n_post,
        "replies": n_reply,
        "replies_with_known_parent": threaded,
        "first_local": local(items[0]["rec"]["ts"]).isoformat(),
        "last_local": local(items[-1]["rec"]["ts"]).isoformat(),
        "per_year": dict(sorted(Counter(
            local(it["rec"]["ts"]).year for it in items).items())),
        "per_month": dict(sorted((k, len(v)) for k, v in months.items())),
        "images": imgs,
        "items_with_media": with_media,
        "chain_tweets": len(chain),
        "md_chars": len(md),
        "generated": datetime.now(TZ).isoformat(),
    }
    with open(os.path.join(DEST_DIR, "meta_timeline.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in meta.items() if k not in ("per_month",)},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()