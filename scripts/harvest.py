"""Harvest @owner posts via gallery-dl API (auth cookies), text-only metadata, no media download."""

import json
import os
import sys
import time
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import SCREEN as TARGET, XDL_ROOT as ROOT, COOKIES, OUT_DIR, PROXY  # noqa: E402

os.environ["GALLERY_DL_CONFIG"] = os.path.join(ROOT, "gallery-dl.json")

from gallery_dl import config, extractor  # noqa: E402

STATE_PATH = os.path.join(OUT_DIR, "state.json")
JSONL_PATH = os.path.join(OUT_DIR, "tweets.jsonl")
MAX_PAGES = int(os.environ.get("MAX_PAGES", "100000"))

CFG = ("extractor", "twitter")
config.clear()
config.load()
for key, value in (
    ("cookies", COOKIES),
    ("retweets", False),
    ("quoted", True),  # keep quotes, we store their nested text
    ("replies", False),
    ("pinned", True),
    ("text-tweets", True),
    ("unique", True),
    ("proxy", PROXY),
    ("ratelimit", "1/2"),
    ("retries", 6),
    ("sleep-429", "60-120"),
):
    config.set(CFG, key, value)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(ROOT, "harvest.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("harvest")


def flatten_media(entity):
    media = []
    for item in (entity.get("media") or {}).get("out", []) if isinstance(entity.get("media"), dict) else []:
        media.append(item)
    return media


def nf(x):
    return x if isinstance(x, (int, float)) else 0


def tweet_record(tweet):
    """Flatten one graphql tweet result into a simple record."""
    if not isinstance(tweet, dict):
        return None
    legacy = tweet.get("legacy") or tweet
    tid = legacy.get("id_str") or tweet.get("rest_id")
    if not tid:
        return None

    text = legacy.get("full_text") or legacy.get("text") or ""
    # t.co links -> real URLs
    for u in (legacy.get("entities") or {}).get("urls") or []:
        if u.get("url") and u.get("expanded_url"):
            text = text.replace(u["url"], u["expanded_url"])
    for u in (legacy.get("entities") or {}).get("media") or []:
        if u.get("url"):
            text = text.replace(u["url"], "")

    media = []
    for m in ((legacy.get("extended_entities") or {}).get("media")
              or (legacy.get("entities") or {}).get("media") or []):
        kind = m.get("type")
        entry = {"type": kind, "url": m.get("media_url_https")}
        if kind == "video" or kind == "animated_gif":
            variants = (m.get("video_info") or {}).get("variants") or []
            mp4 = [v for v in variants if v.get("content_type") == "video/mp4"]
            if mp4:
                entry["url"] = max(mp4, key=lambda v: nf(v.get("bitrate")))["url"]
                entry["type"] = "video" if kind == "video" else "gif"
            entry["duration_ms"] = (m.get("video_info") or {}).get("duration_millis")
        if m.get("ext_alt_text"):
            entry["alt"] = m["ext_alt_text"]
        media.append(entry)

    quoted = None
    qt = tweet.get("quoted_status_result") or {}
    if qt.get("result"):
        quoted = tweet_record(qt["result"])

    retweeted = None
    rt = tweet.get("retweeted_status_result") or {}
    if rt.get("result"):
        retweeted = tweet_record(rt["result"])

    author = (tweet.get("core") or {}).get("user_results", {}).get("result", {})
    al = author.get("legacy") or {}
    if not al and author.get("core"):
        al = {"screen_name": author["core"].get("screen_name"),
              "name": author["core"].get("name")}
    screen = al.get("screen_name")
    if not screen:
        screen = (author.get("core") or {}).get("screen_name")

    views = tweet.get("views") or {}
    try:
        view_count = int(views.get("count") or 0)
    except (TypeError, ValueError):
        view_count = 0

    rec = {
        "id": str(tid),
        "url": f"https://x.com/{screen or TARGET}/status/{tid}",
        "author": screen,
        "name": al.get("name"),
        "created_at": legacy.get("created_at"),
        "ts": _ts(legacy.get("created_at")),
        "text": text,
        "lang": legacy.get("lang"),
        "reply_to": legacy.get("in_reply_to_status_id_str"),
        "is_retweet": bool(legacy.get("retweeted_status_id_str")),
        "retweeted": retweeted,
        "is_quote": bool(legacy.get("quoted_status_id_str")),
        "quoted": quoted,
        "media": media,
        "likes": nf(legacy.get("favorite_count")),
        "replies": nf(legacy.get("reply_count")),
        "retweets": nf(legacy.get("retweet_count")),
        "quotes": nf(legacy.get("quote_count")),
        "bookmarks": nf(legacy.get("bookmark_count")),
        "views": view_count,
    }
    return rec


def _ts(s):
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")  # e.g. Mon Nov 10 10:00:00 +0000 2026
    except (TypeError, ValueError):
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


class CountingAPI:
    def __init__(self, api, state):
        self._api = api
        self._state = state
        for name in ("user_tweets", "user_media", "user_tweets_and_replies",
                     "search_timeline", "user_by_screen_name", "_user_id_by_screen_name"):
            if hasattr(api, name):
                setattr(self, name, self._wrap(getattr(api, name)))

    def _wrap(self, fn):
        def inner(*a, **kw):
            it = fn(*a, **kw)
            if not hasattr(it, "__iter__"):
                return it
            return self._gen(it)
        return inner

    def _gen(self, it):
        for item in it:
            self._state["batches"] = self._state.get("batches", 0) + 1
            yield item


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    state = load_state()
    done_ids = set()
    if os.path.exists(JSONL_PATH):
        with open(JSONL_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line)["id"])
    log.info("resume: %d tweets already stored", len(done_ids))

    ex = extractor.find(f"https://x.com/{TARGET}/tweets")
    ex.initialize()
    ex.login()
    user = ex._user_obj or {}
    info = {
        "rest_id": user.get("rest_id"),
        "screen_name": (user.get("legacy") or {}).get("screen_name"),
        "name": (user.get("legacy") or {}).get("name"),
        "statuses_count": (user.get("legacy") or {}).get("statuses_count"),
    }
    log.info("target: %s", json.dumps(info, ensure_ascii=False))
    state["user"] = info
    state["started"] = state.get("started") or datetime.now(timezone.utc).isoformat()

    total = 0
    fetched = 0
    seen = set(done_ids)
    fh = open(JSONL_PATH, "a", encoding="utf-8")
    try:
        for tweet in ex.tweets():
            fetched += 1
            data = tweet.get("legacy") or tweet
            if "retweeted_status_id_str" in data:
                continue
            if "in_reply_to_user_id_str" in data:
                rec_user = ((tweet.get("core") or {}).get("user_results") or {}).get("result") or {}
                uid = rec_user.get("rest_id") or ((rec_user.get("legacy") or {}).get("id_str"))
                if str(uid) != str(user.get("rest_id")):
                    continue
            rec = tweet_record(tweet)
            if not rec or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            total += 1
            if total % 20 == 0:
                state["fetched"], state["stored"] = fetched, len(seen)
                state["cursor"] = getattr(ex, "_cursor", None)
                save_state(state)
                log.info("stored %d (raw fetched %d) latest=%s %s",
                         len(seen), fetched, rec["ts"], rec["text"][:40].replace("\n", " "))
    except KeyboardInterrupt:
        log.warning("interrupted by user")
    finally:
        fh.close()
        state["fetched"], state["stored"] = fetched, len(seen)
        state["cursor"] = getattr(ex, "_cursor", None)
        state["updated"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        log.info("done: stored=%d fetched=%d", len(seen), fetched)


if __name__ == "__main__":
    main()