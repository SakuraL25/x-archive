# -*- coding: utf-8 -*-
"""把 X 归档整理稿落成 llm-wiki raw 分月卷（通用版）。

输入（全部只读）：
  <X_ARCHIVE_DIR>/timeline.jsonl   ← 唯一真源，按行序即全局 #N
  <X_ARCHIVE_DIR>/tweets.jsonl     ← 判定「续自己的帖」
  <X_ARCHIVE_DIR>/meta_timeline.json
  <XDL_ROOT>/out/context.jsonl / chain.jsonl ← 父帖原文

输出：
  <WIKI_ROOT>/raw/人物/<X_PERSON_DIR>/推特/YYYY-MM.md × N
  <XDL_ROOT>/raw_check.json

约束：全部内容先在内存里生成并跑完逐字自检，通过后才原子写盘；自检失败直接 exit 2。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import (SCREEN, X_ARCHIVE_DIR as SRC, XDL_ROOT, POSTS, CTX, CHAIN,  # noqa: E402
                   RAW_DIR as DEST, PERSON_DIR)
from build_timeline_md import read_jsonl, local, clean, fmt, media_lines  # noqa: E402

if not DEST:
    raise SystemExit("xconf: 转 raw 需要 X_PERSON_DIR（wiki 里的人物目录名，含档位前缀）")
PERSON = os.environ.get("X_PERSON_NAME") or re.sub(r"^\d+(\.\d+)? ", "", PERSON_DIR)
SHORT = os.environ.get("X_PERSON_SHORT") or re.sub(r"\s*（.*?）\s*", "", PERSON)
TIMELINE = os.path.join(SRC, "timeline.jsonl")
META = os.path.join(SRC, "meta_timeline.json")
REPORT = os.path.join(XDL_ROOT, "raw_check.json")
CREATED = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
PUNC = r'[\s，。：；、？！,.:;?!·—…（）()「」“”"\'\-*]'


def flat(s: str) -> str:
    """与 verify_quotes.py 的 PUNC 归一化一致：只用它判断能否逐字命中。"""
    return "".join(ch for ch in (s or "") if not re.match(PUNC, ch))


def lines_of(text: str) -> list:
    """他人言论 / 正文都写成不带行前缀的连续文本段。

    verify_quotes.py 的 PUNC 不摘 `>`（实测 flat('> a\\n> b') == '>a>b'），
    所以 raw 里绝不能用 markdown 引用块：逐行 `> ` 会让跨行引文定位失败。
    分隔只靠**独占一行的标签**，标签不落进被引正文内部。
    """
    body = clean(text)
    return body.split("\n") if body else ["（无文字）"]


def local_date(ts: str) -> str:
    return local(ts).strftime("%Y-%m-%d %H:%M")


def read_order(path: str) -> list:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("id") and r.get("ts"):
                out.append(r)
    return out


def main() -> int:
    items = read_order(TIMELINE)
    posts = read_jsonl(POSTS)
    ctx = read_jsonl(CTX)
    chain = read_jsonl(CHAIN)
    own_ids = set(posts)
    meta = json.load(open(META, encoding="utf-8"))

    if len(items) != meta["total"]:
        raise SystemExit(f"timeline.jsonl {len(items)} != meta.total {meta['total']}")

    reply_under = Counter()
    for r in items:
        pid = r.get("reply_to")
        if pid and pid in own_ids:
            reply_under[pid] += 1

    def parent_of(pid: str):
        return posts.get(pid) or ctx.get(pid) or chain.get(pid)

    def render_entry(n: int, r: dict) -> list:
        dt = local(r["ts"])
        pid = r.get("reply_to") or ""
        kind = r.get("kind") or ("reply" if pid else "post")
        is_rt = bool(r.get("is_retweet"))
        body = clean(r.get("text"))
        out = [f"### {dt.strftime('%Y-%m-%d %H:%M')}  ·  #{n}", ""]

        if is_rt:
            out += ["**转推**", ""]
            out += [f"**（以下为被转帖原文 · 他人言论，非 {SHORT} 的话）**", ""]
            out += lines_of(body)
        elif kind == "reply":
            head = f"**回复 @{r.get('reply_to_user') or '?'}**"
            src = parent_of(pid)
            if src:
                head += f" · 原帖 {local_date(src['ts'])} · [↗]({src['url']})"
            out += [head, ""]
            if src:
                out += [f"**（原帖正文 · @{src.get('author') or '?'}"
                        f" · 他人言论，非 {SHORT} 的话）**", ""]
                out += lines_of(src.get("text"))
                out += media_lines(src)
            else:
                out += [f"**（原帖已不可见 · {pid}，"
                        "多为被原作者删除、隐藏或保护）**"]
            out += ["", f"**→ {SHORT}：**", "", body or "（无文字）"]
        else:
            if pid in own_ids:
                tag = "**原创 · 续贴**"
            elif r.get("is_quote") and r.get("quoted"):
                tag = "**原创 · 引用**"
            else:
                tag = "**原创**"
            out += [tag, "", body or "（无文字）"]

        q = r.get("quoted") or {}
        if q.get("id") and (clean(q.get("text")) or q.get("media")):
            out += ["", f"**（引用 @{q.get('author') or '?'} · 他人言论）**", ""]
            out += lines_of(q.get("text"))
            out += media_lines(q)

        ml = media_lines(r)
        if ml:
            out += [""] + ml
        vids = [m for m in (r.get("media") or []) if m["type"] in ("video", "gif")]
        if vids:
            out += ["", f"*（含视频 {len(vids)} 个，未收录）*"]

        # 卷内不写互动统计行，也不写单帖链接（溯源统一靠 #N 回查整理稿）
        return out

    # ---- 分桶 + 渲染 ----------------------------------------------------
    months: dict = {}
    for i, r in enumerate(items, 1):
        ym = local(r["ts"]).strftime("%Y-%m")
        months.setdefault(ym, []).append((i, r))

    if {k: len(v) for k, v in months.items()} != meta["per_month"]:
        raise SystemExit("月份分桶与 meta_timeline.per_month 不一致")

    files: dict = {}
    for ym in sorted(months):
        head = [
            "---",
            f'title: "{SCREEN} 推特 {ym}"',
            f'source: "X @{SCREEN} 登录态抓取（原创 + 对他人的回复）；'
            f'整理稿 {SRC.replace(chr(92), chr(47))}"',
            "author:",
            f'  - "{SHORT}"',
            f"published: {ym}-01",
            f"created: {CREATED}",
            "tags:",
            '  - "推特"',
            f'  - "{SHORT}"',
            "---",
            "",
            "## Transcript",
            "",
        ]
        for n, r in months[ym]:
            head += render_entry(n, r)
            head.append("")
        files[ym] = "\n".join(head).rstrip() + "\n"

    # ---- 逐字自检（写盘前） --------------------------------------------
    bad, checked, parent_checked, parent_missing = [], 0, 0, 0
    for ym in sorted(months):
        ff = flat(files[ym])
        for n, r in months[ym]:
            t = flat(clean(r.get("text")))
            if t:
                checked += 1
                if t not in ff:
                    bad.append({"month": ym, "n": n, "id": r["id"], "what": "self"})
            if (r.get("kind") == "reply") and r.get("reply_to"):
                src = parent_of(r["reply_to"])
                if src:
                    pt = flat(clean(src.get("text")))
                    if pt:
                        parent_checked += 1
                        if pt not in ff:
                            bad.append({"month": ym, "n": n, "id": r["id"],
                                        "what": "parent"})
                else:
                    parent_missing += 1
            q = r.get("quoted") or {}
            qt = flat(clean(q.get("text")))
            if q.get("id") and qt and qt not in ff:
                bad.append({"month": ym, "n": n, "id": r["id"], "what": "quoted"})

    ids = [r["id"] for r in items]
    summary = {
        "months": len(months),
        "entries": len(items),
        "posts": sum(1 for r in items if r.get("kind") == "post"),
        "replies": sum(1 for r in items if r.get("kind") == "reply"),
        "retweets": sum(1 for r in items if r.get("is_retweet")),
        "ids_unique": len(set(ids)),
        "seq_ok": [n for n, _ in [(i, r) for i, r in enumerate(items, 1)]] == list(
            range(1, len(items) + 1)),
        "images": sum(1 for r in items for m in (r.get("media") or [])
                      if m["type"] == "photo"),
        "videos": sum(1 for r in items for m in (r.get("media") or [])
                      if m["type"] in ("video", "gif")),
        "parents_resolved": parent_checked,
        "parents_missing": parent_missing,
        "verbatim_checked": checked,
        "verbatim_failed": bad[:20],
        "verbatim_fail_total": len(bad),
        "bytes": sum(len(v.encode("utf-8")) for v in files.values()),
        "per_month": {k: len(v) for k, v in sorted(months.items())},
        "month_bytes": {k: len(v.encode("utf-8")) for k, v in sorted(files.items())},
        "generated": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    if bad:
        dbg = r"D:\tmp\xdl\rawdbg"
        os.makedirs(dbg, exist_ok=True)
        for ym, text in files.items():
            with open(os.path.join(dbg, f"{ym}.md"), "w", encoding="utf-8",
                      newline="\n") as f:
                f.write(text)
        print(json.dumps({"FAILED": len(bad), "sample": bad[:5], "dbg": dbg},
                         ensure_ascii=False), file=sys.stderr)
        return 2

    # ---- 原子写盘 ------------------------------------------------------
    os.makedirs(DEST, exist_ok=True)
    for ym, text in files.items():
        p = os.path.join(DEST, f"{ym}.md")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, p)
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("per_month", "month_bytes", "verbatim_failed")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
