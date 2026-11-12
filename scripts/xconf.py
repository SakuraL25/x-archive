# -*- coding: utf-8 -*-
"""x-archive 共享配置：所有脚本统一从环境变量读参数。

环境变量（TARGET_SCREEN_NAME 必填，其余有默认）：
  TARGET_SCREEN_NAME  博主 screen name（不带 @），如 SomeTrader
  XDL_ROOT            本次抓取的工作区（out/*.jsonl、cookies.txt 落这里）
                      默认 <数据根>/xdl-<screen>，避免不同博主互相污染
  X_ARCHIVE_DIR       整理稿目录（timeline.jsonl 等）
                      默认 <数据根>/x/<screen>
                      （数据根 = env X_DATA_ROOT，未设则用户主目录）
  WIKI_ROOT           llm-wiki 库根（raw/ 与 wiki/ 的父目录）
                      默认无（转 raw 时经 WIKI_ROOT 提供）
  X_PERSON_DIR        wiki 里的人物目录名（含档位前缀），如 "1 某某（方向）"
                      转 raw 时必填；不确定就先做身份对接
  X_PROXY             代理，默认 http://127.0.0.1:10090（Clash）
"""
import os

SCREEN = os.environ.get("TARGET_SCREEN_NAME", "").strip().lstrip("@")
if not SCREEN:
    raise SystemExit("xconf: 请先 set TARGET_SCREEN_NAME=<博主screen name（不带@）>")

XDL_ROOT = os.environ.get("XDL_ROOT") or os.path.join(os.environ.get("X_DATA_ROOT", os.path.expanduser("~")), "xdl-" + SCREEN)
X_ARCHIVE_DIR = os.environ.get("X_ARCHIVE_DIR") or os.path.join(os.environ.get("X_DATA_ROOT", os.path.expanduser("~")), "x", SCREEN)
WIKI_ROOT = os.environ.get("WIKI_ROOT") or os.environ.get("X_WIKI_ROOT_DEFAULT", "")
PERSON_DIR = os.environ.get("X_PERSON_DIR", "").strip()
PROXY = os.environ.get("X_PROXY") or "http://127.0.0.1:10090"

COOKIES = os.path.join(XDL_ROOT, "cookies.txt")
OUT = os.path.join(XDL_ROOT, "out")
POSTS = os.path.join(OUT, "tweets.jsonl")
REPLIES = os.path.join(OUT, "replies.jsonl")
CTX = os.path.join(OUT, "context.jsonl")
CHAIN = os.path.join(OUT, "chain.jsonl")
RAW_DIR = os.path.join(WIKI_ROOT, "raw", "人物", PERSON_DIR, "推特") if PERSON_DIR else ""

os.makedirs(OUT, exist_ok=True)
