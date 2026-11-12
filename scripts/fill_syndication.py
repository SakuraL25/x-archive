"""Fill the parent-post cache from the keyless syndication endpoint.

`https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=a` returns one
public tweet as plain JSON, with no cookies and no GraphQL quota, so the ~900
parents that GraphQL could not reach in an hour take a couple of minutes here.
Records are normalised into the same shape harvest.tweet_record() produces.
"""

import json, os, sys, time, random, re
import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN, OUT, REPLIES, POSTS, CTX, CHAIN, PROXY  # noqa: E402
MISSING = os.path.join(OUT, "context_missing.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0")
CAP = int(os.environ.get("CAP", "0"))


def load(path):
    recs = {}
    if not os.path.exists(path):
        return recs
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("id"):
            recs[r["id"]] = r
    return recs


def usable(r):
    return bool(r and r.get("ts") and (r.get("text") or r.get("media")))


def write_atomic(path, recs):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for rid in sorted(recs, key=lambda i: int(i)):
            f.write(json.dumps(recs[rid], ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def norm(d):
    tid = d.get("id_str")
    if not tid:
        return None
    text = d.get("text") or ""
    for u in (d.get("entities") or {}).get("urls") or []:
        if u.get("url") and u.get("expanded_url"):
            text = text.replace(u["url"], u["expanded_url"])
    media = []
    for m in (d.get("mediaDetails") or (d.get("entities") or {}).get("media") or []):
        kind = m.get("type")
        entry = {"type": "photo" if kind == "photo" else "video",
                 "url": m.get("media_url_https")}
        if kind in ("video", "animated_gif"):
            entry["type"] = "video" if kind == "video" else "gif"
            variants = ((m.get("video_info") or {}).get("variants")
                        or ((m.get("original_info") or {}).get("variants")) or [])
            mp4 = [v for v in variants if v.get("content_type") == "video/mp4"]
            if mp4:
                entry["url"] = max(mp4, key=lambda v: v.get("bitrate") or 0)["url"]
        if m.get("ext_alt_text"):
            entry["alt"] = m["ext_alt_text"]
        media.append(entry)
    for p in (d.get("photos") or []):
        media.append({"type": "photo", "url": p.get("url")})
    # mediaDetails and photos describe the same pictures; keep one of each
    seen_urls, uniq = set(), []
    for m in media:
        if not m.get("url") or m["url"] in seen_urls:
            continue
        seen_urls.add(m["url"])
        uniq.append(m)
    media = uniq
    user = d.get("user") or {}
    created = d.get("created_at") or ""
    ts = None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", created)
    if m:
        ts = "%s-%s-%sT%s:%s:%sZ" % m.groups()
    if not text and not media:
        return None
    return {
        "id": str(tid),
        "url": f"https://x.com/{user.get('screen_name') or 'i'}/status/{tid}",
        "author": user.get("screen_name"),
        "name": user.get("name"),
        "created_at": created,
        "ts": ts,
        "text": text,
        "lang": d.get("lang"),
        "reply_to": d.get("in_reply_to_status_id_str"),
        "is_retweet": False,
        "retweeted": None,
        "is_quote": False,
        "quoted": None,
        "media": media,
        "likes": int(d.get("favorite_count") or 0),
        "replies": 0,
        "retweets": 0,
        "quotes": 0,
        "bookmarks": 0,
        "views": 0,
    }


def main():
    gone = set()
    if os.path.exists(MISSING):
        try:
            gone = set(json.load(open(MISSING, encoding="utf-8")))
        except ValueError:
            pass
    ctx = {k: v for k, v in load(CTX).items() if usable(v)}
    posts = load(POSTS)
    chain = load(CHAIN)
    parents, seen = [], set()
    for line in open(REPLIES, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        pid = json.loads(line).get("reply_to")
        if pid and pid not in seen:
            seen.add(pid)
            parents.append(pid)

    todo = [p for p in parents
            if not (usable(posts.get(p)) or usable(ctx.get(p))
                    or usable(chain.get(p))) and p not in gone]
    print(f"parents {len(parents)}, unresolved {len(todo)}", flush=True)
    if CAP:
        todo = todo[:CAP]

    ok = bad = 0
    with httpx.Client(proxy=PROXY, timeout=25,
                      headers={"User-Agent": UA}) as c:
        for i, tid in enumerate(todo, 1):
            got = None
            for token in ("a", "0", "b"):
                url = (f"https://cdn.syndication.twimg.com/tweet-result"
                       f"?id={tid}&token={token}&lang=zh")
                try:
                    r = c.get(url)
                except Exception:  # noqa: BLE001
                    continue
                if r.status_code == 200 and r.text.strip().startswith("{"):
                    got = r.json()
                    break
                if r.status_code in (403, 404):
                    break
            rec = norm(got) if got else None
            if rec:
                ctx[rec["id"]] = rec
                ok += 1
            else:
                gone.add(tid)
                bad += 1
            if i % 25 == 0:
                write_atomic(CTX, ctx)
                with open(MISSING, "w", encoding="utf-8") as f:
                    json.dump(sorted(gone), f)
                print(f"  {i}/{len(todo)} ok={ok} gone={bad} cache={len(ctx)}",
                      flush=True)
            time.sleep(0.35 + random.random() * 0.3)

    write_atomic(CTX, ctx)
    with open(MISSING, "w", encoding="utf-8") as f:
        json.dump(sorted(gone), f)
    print(f"done ok={ok} gone={bad} cache={len(ctx)}", flush=True)


if __name__ == "__main__":
    main()