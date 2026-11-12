"""Fill the *upper* ancestors of the reply chains (depth 2+).

fill_syndication.py resolved the direct parents; 696 of those parents themselves
answer someone, and 52 of those grandparents answer someone too.  This pass walks
up until a chain reaches a root or a tweet that no longer exists.
"""

import json, os, time, random, sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import OUT, POSTS, CTX, CHAIN, REPLIES, PROXY  # noqa: E402
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0")
MAX_DEPTH = int(os.environ.get("MAX_DEPTH", "6"))
CAP = int(os.environ.get("CAP", "0"))

from fill_syndication import load, usable, write_atomic, norm  # noqa: E402


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

    def known(pid):
        return usable(posts.get(pid)) or usable(ctx.get(pid)) or usable(chain.get(pid))

    roots, seen = [], set()
    for line in open(REPLIES, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        pid = json.loads(line).get("reply_to")
        if pid and pid not in seen:
            seen.add(pid)
            roots.append(pid)

    todo, frontier = [], list(roots)
    for depth in range(MAX_DEPTH):
        nxt = []
        for pid in frontier:
            if pid in gone:
                continue
            if not known(pid):
                if pid not in todo:
                    todo.append(pid)
                continue
            rec = posts.get(pid) or ctx.get(pid) or chain.get(pid)
            up = (rec or {}).get("reply_to")
            if up and up not in gone and up not in seen:
                seen.add(up)
                nxt.append(up)
        print(f"depth {depth}: frontier {len(frontier)}, queued {len(todo)}",
              flush=True)
        if not nxt:
            break
        frontier = nxt

    if CAP:
        todo = todo[:CAP]
    print(f"ancestors to fetch: {len(todo)}", flush=True)
    if not todo:
        return

    ok = bad = 0
    with httpx.Client(proxy=PROXY, timeout=25, headers={"User-Agent": UA}) as c:
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
            time.sleep(0.3 + random.random() * 0.3)

    write_atomic(CTX, ctx)
    with open(MISSING, "w", encoding="utf-8") as f:
        json.dump(sorted(gone), f)
    print(f"done ok={ok} gone={bad} cache={len(ctx)}", flush=True)


if __name__ == "__main__":
    main()