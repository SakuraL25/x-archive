"""Walk backwards in time with `until:` search queries to recover posts older than the
UserTweets cursor cap. Each round takes the oldest result and re-queries before it."""

import os, sys, json, time, traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN as TARGET, XDL_ROOT as ROOT, COOKIES, OUT, PROXY  # noqa: E402

os.environ["GALLERY_DL_CONFIG"] = os.path.join(ROOT, "gallery-dl.json")
from gallery_dl import config, extractor  # noqa: E402
from harvest import tweet_record  # noqa: E402

CFG = ("extractor", "twitter")
config.clear(); config.load()
for k, v in (("cookies", COOKIES),
             ("proxy", PROXY),
             ("ratelimit", "wait:30")):
    config.set(CFG, k, v)

FLOOR = datetime(2010, 1, 1, tzinfo=timezone.utc)
MAX_ROUNDS = int(os.environ.get("MAX_ROUNDS", "60"))
PAGES = int(os.environ.get("PAGES", "2"))
JSONL = os.path.join(OUT, "tweets.jsonl")
EP = "/graphql/4fpceYZ6-YQCx_JSl_Cn_A/SearchTimeline"


def ts_of(tid):
    return datetime.fromtimestamp(((int(tid) >> 22) + 1288834974657) / 1000, timezone.utc)


def load_owned():
    owned = {}
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if (r.get("author") or "").lower() == TARGET.lower():
                    owned[r["id"]] = r
    return owned


def collect(api, query, owned, pages):
    """Run a query (cursor paginated), return (new_records, oldest_ts_or_None, n_ids)."""
    cursor, new, ids_seen, oldest = None, [], 0, None
    for _ in range(pages):
        variables = {"rawQuery": query, "count": 20, "querySource": "typed_query",
                     "product": "Latest", "withGrokTranslatedBio": False}
        if cursor:
            variables["cursor"] = cursor
        try:
            data = api._call(EP, {"variables": json.dumps(variables)})
            inst = data["data"]["search_by_raw_query"]["search_timeline"]["timeline"]["instructions"]
        except (KeyError, TypeError):
            break
        ents = []
        for i in inst:
            ents.extend(i.get("entries") or [])
            if i.get("type") == "TimelineAddToModule":
                ents.extend(i.get("moduleItems") or [])
        bottom, page_ids = None, []
        for e in ents:
            eid = e.get("entryId") or ""
            if eid.startswith("cursor-bottom-"):
                bottom = (e.get("content") or {}).get("value")
                continue
            if not eid.startswith("tweet-"):
                continue
            page_ids.append(eid.rpartition("-")[2])
            res = (((e.get("content") or e.get("item") or {}).get("itemContent") or {})
                   .get("tweet_results") or {}).get("result") or {}
            if "tweet" in res:
                res = res["tweet"]
            if "legacy" not in res:
                continue
            try:
                rec = tweet_record(res)
            except Exception:
                continue
            if not rec or (rec.get("author") or "").lower() != TARGET.lower():
                continue
            d = ts_of(rec["id"])
            oldest = d if oldest is None or d < oldest else oldest
            if rec["id"] not in owned:
                new.append(rec)
        ids_seen += len(page_ids)
        if not bottom or not page_ids:
            break
        cursor = bottom
        time.sleep(5)
    return new, oldest, ids_seen


def main():
    ex = extractor.find(f"https://x.com/{TARGET}/tweets")
    ex.initialize(); ex.login()
    api = ex.api

    owned = load_owned()
    print(f"owned start: {len(owned)}", flush=True)
    since_floor = FLOOR.strftime("%Y-%m-%d")
    until = min(ts_of(i) for i in owned).strftime("%Y-%m-%d")
    print(f"walking back from {until}", flush=True)

    total_new, zeros = 0, 0
    fh = open(JSONL, "a", encoding="utf-8")
    try:
        for rnd in range(MAX_ROUNDS):
            query = f"since:{since_floor} until:{until} from:{TARGET}"
            t0 = time.time()
            new, oldest, n_ids = collect(api, query, owned, PAGES)
            for rec in new:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                owned[rec["id"]] = rec
            fh.flush()
            total_new += len(new)
            print(f"round {rnd}: until={until} ids={n_ids} new={len(new)} "
                  f"oldest={oldest.date() if oldest else None} owned={len(owned)} "
                  f"{time.time()-t0:.1f}s", flush=True)
            if not oldest:
                zeros += 1
                if zeros >= 3:
                    print("3 empty rounds, stop", flush=True)
                    break
                # step back a year to skip dead zone
                until = (datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                         - timedelta(days=365)).strftime("%Y-%m-%d")
                if until < since_floor:
                    break
                continue
            zeros = 0
            nxt = (oldest - timedelta(days=1)).strftime("%Y-%m-%d")
            if nxt == until:
                nxt = (oldest - timedelta(days=2)).strftime("%Y-%m-%d")
            until = nxt
            if until < since_floor:
                print("reached floor", flush=True)
                break
            time.sleep(4)
    finally:
        fh.close()
    if owned:
        tl = sorted(ts_of(i) for i in owned)
        print(f"done: added={total_new} owned={len(owned)} span {tl[0].date()} .. {tl[-1].date()}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise