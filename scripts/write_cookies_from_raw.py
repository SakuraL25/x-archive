# -*- coding: utf-8 -*-
"""把 raw_cookie.txt（cookie 头格式）转成 gallery-dl 用的 Netscape cookies.txt。

用法：set XDL_ROOT=... 后直接运行；从 xconf 读路径，不打印 cookie 值。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xconf import XDL_ROOT, COOKIES  # noqa: E402

IMPORTANT = ("auth_token", "ct0", "twid", "kdt")
WANT = IMPORTANT + ("guest_id", "guest_id_marketing", "guest_id_ads",
                    "personalization_id", "gt")


def parse(header):
    pairs = {}
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k and v:
            pairs[k] = v
    return pairs


def main():
    src = os.path.join(XDL_ROOT, "raw_cookie.txt")
    pairs = parse(open(src, encoding="utf-8").read().strip())
    exp = int(time.time()) + 60 * 60 * 24 * 180
    lines = ["# Netscape HTTP Cookie File", "# generated for gallery-dl (x.com)", ""]
    for name in WANT:
        if name in pairs:
            lines.append("\t".join([".x.com", "TRUE", "/", "TRUE", str(exp), name, pairs[name]]))
    os.makedirs(XDL_ROOT, exist_ok=True)
    with open(COOKIES, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    missing = [k for k in IMPORTANT if k not in pairs]
    print("written", COOKIES, os.path.getsize(COOKIES), "bytes; names:",
          ",".join(n for n in WANT if n in pairs), "; missing:", ",".join(missing) or "none")
    if missing:
        print("WARN: 缺关键 cookie（auth_token/ct0/twid/kdt），登录态可能不完整")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
