"""Harvest @<screen>'s replies by slicing time windows in half when the search
API saturates.

Findings that drive the design
    * `Latest` search only serves tweets from roughly the last 3 years, and it
      repeats the SAME first page no matter what `max_id` / `cursor` you pass
      (20 distinct ids for any window, 36 for a whole month once the repeated
      page is dropped).
    * A window narrow enough to hold fewer than 20 matching tweets comes back
      complete, so the only way to see all of them is to keep bisecting the
      date range.

Algorithm: walk from NOW backwards. Query `since:NULL T WE
*`… i.e. `from:<screen> filter:replies since:S until:U`. If the window came back
saturated (>= 18 distinct ids) and spans more than one day, split it and recurse.
Otherwise the window is complete: record it and continue with the next window
that ends just before its oldest tweet.

Progress lives in out/replies.jsonl (deduplicated on id) and out/win_state.json
(next `until` to resume from), so a restart continues where it stopped.
"""

import os, sys, json, time, random
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN, XDL_ROOT as ROOT, COOKIES, REPLIES, OUT, PROXY  # noqa: E402

os.environ["GALLERY_DL_CONFIG"] = os.path.join(ROOT, "gallery-dl.json")
from gallery_dl import config, extractor  # noqa: E402

CFG = ("extractor", "twitter")
config.clear(); config.load()
for k, v in (("cookies", COOKIES),
             ("proxy", PROXY),
             ("ratelimit", "wait:30")):
    config.set(CFG, k, v)

from harvest import tweet_record  # noqa: E402

STATE = os.path.join(OUT, "win_state.json")
EP_SEARCH = "/graphql/4fpceYZ6-YQCx_JSl_Cn_A/SearchTimeline"
FLOOR = os.environ.get("FLOOR", "2020-10-01")
MAX_ITERS = int(os.environ.get("MAX_ITERS", "100000"))
SAT = int(os.environ.get("SAT", "17"))


def screen_of(tweet):
    try:
        u = tweet["core"]["user_results"]["result"]
    except (KeyError, TypeError):
        return None
    return ((u.get("legacy") or {}).get("screen_name")
            or (u.get("core") or {}).get("screen_name"))


def parse_entries(inst):
    out = []
    for i in inst:
        for e in (i.get("entries") or []):
            eid = e.get("entryId") or ""
            if eid.startswith("tweet-"):
                out.append(e)
            elif eid.startswith("profile-conversation-"):
                out.extend((e.get("content") or {}).get("items") or [])
    return out


class Harvest:
    def __init__(self):
        self.ex = extractor.find(f"https://x.com/{SCREEN}/tweets")
        self.ex.initialize(); self.ex.login()
        self.api = self.ex.api
        self.known = set()
        if os.path.exists(OUT):
            for line in open(OUT, encoding="utf-8"):
                line = line.strip()
                if line:
                    try:
                        self.known.add(json.loads(line)["id"])
                    except (ValueError, KeyError):
                        pass
        self.fh = open(OUT, "a", encoding="utf-8")
        self.st = {"new": 0, "reqs": 0, "windows": 0}
        state = {}
        if os.path.exists(STATE):
            state = json.load(open(STATE, encoding="utf-8"))
        self.until = state.get("until")
        if not self.until:
            self.until = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def save_state(self):
        json.dump({"until": self.until, "stats": self.st,
                   "saved": datetime.now(timezone.utc).isoformat()},
                  open(STATE, "w", encoding="utf-8"), ensure_ascii=False)

    def query(self, s, u, deep=False):
        """deep=True flips to Top and follows the bottom cursor (reaches back)."""
        raw = f"from:{SCREEN} since:{s} until:{u} filter:replies"
        v = {"rawQuery": raw, "count": 20, "querySource": "typed_query",
             "product": "Top" if deep else "Latest",
             "withGrokTranslatedBio": False}
        ids, tweets = set(), []
        cursor, pages = None, 0
        while True:
            if cursor:
                v["cursor"] = cursor
            self.st["reqs"] += 1
            data = self.api._call(EP_SEARCH, {"variables": json.dumps(v)})
            inst = (data["data"]["search_by_raw_query"]["search_timeline"]
                    ["timeline"]["instructions"])
            ents = parse_entries(inst)
            for e in ents:
                ids.add(e["entryId"].rpartition("-")[2])
                ic = ((e.get("content") or e.get("item") or {}).get("itemContent") or {})
                res = (ic.get("tweet_results") or {}).get("result") or {}
                if "tweet" in res:
                    res = res["tweet"]
                if res.get("legacy"):
                    tweets.append(res)
            pages += 1
            if not deep or pages >= max(1, int(os.environ.get("DEPTH", "6"))):
                break
            nxt = None
            for e in inst:
                if (e.get("entryId") or "").startswith("cursor-bottom"):
                    nxt = ((e.get("content") or {}).get("value") or e.get("value"))
            if not nxt or nxt == cursor:
                break
            cursor = nxt
        return tweets, ids

    def store(self, tweets):
        for res in tweets:
            if (screen_of(res) or "").lower() != SCREEN.lower():
                continue
            leg = res.get("legacy") or {}
            if not leg.get("in_reply_to_status_id_str"):
                continue
            tid = res.get("rest_id") or leg.get("id_str")
            if not tid or tid in self.known:
                continue
            rec = tweet_record(res)
            if not rec:
                continue
            rec["author"] = SCREEN
            rec["reply_to_id"] = leg.get("in_reply_to_status_id_str")
            rec["reply_to_user"] = leg.get("in_reply_to_screen_name")
            self.known.add(tid)
            self.fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.st["new"] += 1
        self.fh.flush()

    def ts_of(self, tid):
        try:
            return self.ex._tweetid_to_datetime(int(tid))
        except Exception:  # noqa: BLE001
            return None

    def until_of(self, tid):
        d = self.ts_of(tid)
        return None if d is None else d.astimezone(timezone.utc).date().isoformat()

    def run(self):
        if os.environ.get("IMPORT_ONLY"):
            self.fh.close()
            return
        self.bisect("2020-01-01", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.save_state()
        self.fh.close()
        print(f"done: new={self.st['new']} reqs={self.st['reqs']} "
              f"windows={self.st['windows']}", flush=True)

    def bisect(self, s, u, depth=0):
        """Split until a window holds fewer than SAT tweets (i.e. is complete)."""
        tweets, ids = None, set()
        for attempt in range(1):
            try:
                tweets, ids = self.query(s, u)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  {s}..{u} retry {attempt} {exc.__class__.__name__}: {exc}",
                      flush=True)
                time.sleep(10 + attempt * 10)
        if tweets is None:
            print(f"  {s}..{u} GAVE UP", flush=True)
            return
        self.store(tweets)
        self.st["windows"] += 1
        span = (datetime.strptime(u, "%Y-%m-%d")
                - datetime.strptime(s, "%Y-%m-%d")).days
        print(f"  {s}..{u} span={span}d ids={len(ids)} +{self.st['new']}", flush=True)
        if span <= 1 or len(ids) < SAT:
            return                      # complete window
        mid = (datetime.strptime(s, "%Y-%m-%d") + timedelta(days=max(1, span // 2)))
        self.bisect(s, mid.strftime("%Y-%m-%d"), depth + 1)
        self.bisect(mid.strftime("%Y-%m-%d"), u, depth + 1)
        if depth <= 1:
            self.save_state()


if __name__ == "__main__":
    Harvest().run()