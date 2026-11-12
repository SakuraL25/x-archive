"""Build the reply archive from out/replies.jsonl (chronological).

Replies carry a `reply_to_user` / `reply_to_id`; the parent context is resolved
from out/tweets.jsonl (his own post) or from out/context.jsonl (someone else's
post, collected by harvest_ctx.py). Output:
    <X_ARCHIVE_DIR>/<screen>_replies.md
    <X_ARCHIVE_DIR>/replies.jsonl
    <X_ARCHIVE_DIR>/meta_replies.json
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN, X_ARCHIVE_DIR as DEST_DIR, REPLIES as JSONL, POSTS, CTX, CHAIN  # noqa: E402
TZ = timezone(timedelta(hours=8))


def read_jsonl(path, want_author=None):
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
            if not r.get("ts") or not r.get("id"):
                continue
            if want_author and (r.get("author") or "").lower() != want_author.lower():
                continue
            recs[r["id"]] = r
    return recs


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


def media_lines(rec, prefix=""):
    out = []
    imgs = [m for m in (rec.get("media") or []) if m["type"] == "photo"]
    vids = [m for m in (rec.get("media") or []) if m["type"] in ("video", "gif")]
    for i, m in enumerate(imgs, 1):
        cap = f"图 {i}/{len(imgs)}" if len(imgs) > 1 else "图"
        out.append(f"{prefix}![{cap}]({m['url']})")
    for m in vids:
        dur = m.get("duration_ms")
        kind = "GIF" if m["type"] == "gif" else "视频"
        secs = f"（{dur / 1000:.1f} 秒）" if dur else ""
        out.append(f"{prefix}*（原帖含{kind}{secs}，按要求未收录）*")
    return out


def _quote_lines(rec, indent=">", tag=""):
    """One ancestor post rendered as a blockquote body."""
    when = local(rec["ts"]).strftime("%Y-%m-%d %H:%M")
    who = rec.get("author") or "?"
    out = [f"{indent} {indent}**{tag}@{who}** · {when} · [↗]({rec['url']})",
           f"{indent} {indent}"]
    body = clean(rec.get("text"))
    for ln in (body.split("\n") if body else ["（无文字）"]):
        out.append(f"{indent} {indent}{ln}" if ln.strip() else f"{indent} {indent}")
    for ln in media_lines(rec, f"{indent} {indent}"):
        out.append(ln)
    return out


def parent_block(rec, posts, ctx, chain=None):
    """The conversation he replied into: parent post plus its own ancestors."""
    chain = chain or {}
    pid = rec.get("reply_to")
    who = rec.get("reply_to_user") or ""
    head = f"> **回复 @{who}**"

    # walk upward from the direct parent, at most CHAIN_HOPS ancestors
    anc, cur, guard = [], pid, 0
    while cur and guard < 4:
        src = posts.get(cur) or ctx.get(cur) or chain.get(cur)
        if not src:
            break
        anc.append(src)
        cur = src.get("reply_to")
        guard += 1

    if not anc:
        return [head, ">",
                f"> 原文已不可见（{pid}，多为被原作者删除、隐藏或保护，X 只回空壳）"]

    direct = anc[0]
    when = local(direct["ts"]).strftime("%Y-%m-%d %H:%M")
    more = len(anc) - 1
    tail = f" · 其上方还有 {more} 层对话" if more else ""
    out = [f"{head} · 上下文原帖 {when} · [↗]({direct['url']}){tail}", ">"]
    body = clean(direct.get("text"))
    for ln in (body.split("\n") if body else ["（无文字）"]):
        out.append(("> " + ln) if ln.strip() else ">")
    for ln in media_lines(direct, "> "):
        out.append(ln)
    q = direct.get("quoted") or {}
    if q.get("id") and (q.get("text") or q.get("media")):
        out.append(">")
        out.extend(_quote_lines(q, tag="引用 "))
    # ancestors above the direct parent, oldest first, nested one level deeper
    for prev in reversed(anc[1:]):
        out.append(">")
        out.extend(_quote_lines(prev, tag="更早对话 "))
    return out


def render(recs, posts, ctx, chain=None, moved=0):
    recs.sort(key=lambda r: (r["ts"], int(r["id"])))
    imgs = sum(1 for r in recs for m in (r.get("media") or []) if m["type"] == "photo")
    vids = sum(1 for r in recs for m in (r.get("media") or [])
               if m["type"] in ("video", "gif"))
    with_media = sum(1 for r in recs if r.get("media"))
    chain = chain or {}
    table = {}
    table.update(chain)
    table.update(ctx)
    table.update(posts)

    def has_thread(r):
        q = table.get(r.get("reply_to"))
        return bool(q and q.get("reply_to") and q["reply_to"] != r.get("reply_to"))

    solved = sum(1 for r in recs if r.get("reply_to") in table)
    hops = sum(1 for r in recs if has_thread(r))
    first = local(recs[0]["ts"]).strftime("%Y-%m-%d")
    last = local(recs[-1]["ts"]).strftime("%Y-%m-%d")
    months = {}
    for r in recs:
        months.setdefault(local(r["ts"]).strftime("%Y-%m"), []).append(r)
    partners = Counter((r.get("reply_to_user") or "?") for r in recs)
    lens = [len(clean(r.get("text"))) for r in recs]

    p = [f"# @{SCREEN} 推文归档（回复）\n"]
    p.append(
        f"> 账号：https://x.com/{SCREEN}  \n"
        f"> 覆盖：{first} → {last}（北京时间）  \n"
        f"> 共 **{len(recs)}** 条回复（他自己发出的、带 @ 的回复；不含原创帖、不含转推）"
        f"｜带图 {with_media} 条（图片 {imgs} 张，视频/GIF 按要求未收录）"
        f"｜正文合计 {sum(lens):,} 字符（平均 {sum(lens) // max(len(lens), 1)}）  \n"
        f"> 抓取：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}，"
        f"按时间窗二分 `from:{SCREEN} filter:replies` 逐段取尽  \n"
        f"> 另有 {moved} 条他回复自己帖子的续贴，归在同目录 `{SCREEN.lower()}_full.md`  \n"
        f"> 阅读：时间升序；每帖含「回复对象 + 上下文原帖」→ 他的回复 → 媒体 → 互动数据与原帖链接  \n"
        f"> 上下文原帖 {solved}/{len(recs)} 条取到原文，其余是原作者已删除或隐藏的  \n"
    )
    p.append("## 目录\n")
    for ym, rs in months.items():
        p.append(f"- [{ym}](#m{ym.replace('-', '')}) — {len(rs)} 条")
    p.append("")
    p.append("## 数据说明\n")
    top = "、".join(f"@{u}（{n}）" for u, n in partners.most_common(12))
    p.append(
        f"回复数据来自 X 搜索接口 `from:{SCREEN} filter:replies`。该接口每页固定 20 条、"
        "`cursor` 翻页在第二页即失效，所以改用**时间窗二分**：一个窗口里不足 17 条即认定"
        "已抓全，否则把窗口对半劈开分别再抓，直到每段都取尽。"
        "2020-10 到 2026-11 全程都是这样走完的，不是抽样。\n\n"
        f"回复对象分布（前 12）：{top}。\n\n"
        f"上下文原帖：{solved}/{len(recs)} 条取到原文（含被回复者更早的对话层）。"
        "剩下的标注为「原文已不可见」——那是原作者删了帖、锁了号或设了保护，"
        "X 只回一个空壳，任何客户端都取不到正文，不是抓漏。\n\n"
        "时间段与他原创帖一致：2020-10 建档，2023—2026 活跃，2024 下半年—2025 年的稀疏期"
        "（重心在 B 站/YouTube）在这里同样稀疏。\n"
    )
    cur = None
    for r in recs:
        dt = local(r["ts"])
        ym = dt.strftime("%Y-%m")
        if ym != cur:
            cur = ym
            p.append(f'\n<a id="m{ym.replace("-", "")}"></a>\n')
            p.append(f"## {dt.strftime('%Y 年 %m 月')}\n")
        p.append(f"### {dt.strftime('%Y-%m-%d %H:%M')}\n")
        p.extend(parent_block(r, posts, ctx, chain))
        p.append("")
        body = clean(r.get("text"))
        p.append(f"**→ {SCREEN}：**\n")
        p.append((body or "（无文字）") + "\n")
        mlines = media_lines(r)
        if mlines:
            p.extend(mlines)
            p.append("")
        stats = (f"❤ {fmt(r.get('likes'))} · 🔁 {fmt(r.get('retweets'))}"
                 f" · 💬 {fmt(r.get('replies'))} · 🔖 {fmt(r.get('bookmarks'))}"
                 f" · 👁 {fmt(r.get('views'))}")
        p.append(f"{stats} · [原帖 ↗]({r['url']})\n")
    md = "\n".join(p).rstrip() + "\n"
    facts = {"solved": solved, "hops": hops, "imgs": imgs, "vids": vids,
             "with_media": with_media, "first": first, "last": last}
    return md, facts


def main():
    recs = list(read_jsonl(JSONL, SCREEN).values())
    if not recs:
        raise SystemExit("no replies")
    posts = read_jsonl(POSTS, SCREEN)
    # Replies to his OWN posts that already sit in the posts archive are thread
    # continuations and belong to <screen>_full.md; a self-thread reply the
    # profile harvest never returned stays here so nothing is dropped.
    keep = [r for r in recs
            if not (r["id"] in posts and (r.get("reply_to") or "") in posts)]
    moved = len(recs) - len(keep)
    print(f"moved {moved} self-thread replies to the posts archive")
    recs = keep
    ctx = read_jsonl(CTX)
    chain = read_jsonl(CHAIN)
    os.makedirs(DEST_DIR, exist_ok=True)
    md, facts = render(recs, posts, ctx, chain, moved)
    with open(os.path.join(DEST_DIR, f"{SCREEN.lower()}_replies.md"), "w", encoding="utf-8") as f:
        f.write(md)
    recs.sort(key=lambda r: r["ts"])
    with open(os.path.join(DEST_DIR, "replies.jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    years = Counter(local(r["ts"]).year for r in recs)
    months = Counter(local(r["ts"]).strftime("%Y-%m") for r in recs)
    meta = {
        "screen_name": SCREEN,
        "profile": f"https://x.com/{SCREEN}",
        "replies": len(recs),
        "first_local": local(min(r["ts"] for r in recs)).isoformat(),
        "last_local": local(max(r["ts"] for r in recs)).isoformat(),
        "per_year": dict(sorted(years.items())),
        "per_month": dict(sorted(months.items())),
        "images": sum(1 for r in recs for m in (r.get("media") or []) if m["type"] == "photo"),
        "videos": sum(1 for r in recs for m in (r.get("media") or [])
                      if m["type"] in ("video", "gif")),
        "replies_with_media": sum(1 for r in recs if r.get("media")),
        "context_resolved": sum(1 for r in recs
                                if r.get("reply_to") in posts or r.get("reply_to") in ctx
                                or r.get("reply_to") in chain),
        "chain_tweets": len(chain),
        "replies_with_deeper_thread": facts["hops"],
        "md_chars": len(md),
        "source": (f"X GraphQL SearchTimeline from:{SCREEN} filter:replies, "
                   "binary time-window sweep; parents via syndication endpoint"),
        "generated": datetime.now(TZ).isoformat(),
    }
    with open(os.path.join(DEST_DIR, "meta_replies.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in meta.items() if k != "per_month"},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()