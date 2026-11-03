#!/usr/bin/env python3
"""统计 UniML3D 的动作类别分布 —— 判断"这个动作模型学过没有"。

为什么要看这个：模型只会做训练分布内的动作。想知道某个动作能不能生成，
先查它在 13,769 条 caption 里的占比。占比高 = 稳；占比低 = 多采几次也许能出；
查不到 = 换个办法（程序补 / 外部动作库 / 手工）。

用法
----
  # 1. 下载元数据（很小，几 MB，不需要 88 GB 全量数据集）
  hf download Linzhan/UniML3D --repo-type dataset --local-dir tmp/meta \
      --include "export/*/motion_captions.json" --include "export/*/category_groups.json"

  # 2. 统计
  python tools/caption_stats.py --meta tmp/meta
  python tools/caption_stats.py --meta tmp/meta --grep roll      # 查某个动作有没有
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter

DATASETS = ("mixamo", "truebones", "objaverse")

# 语义家族：顺序即优先级。同一句话只归第一个命中的家族。
FAMILIES = [
    ("翻滚翻转", r"\b(roll|rolls|rolling|somersault|tumble|tumbles|cartwheel|flip|flips|handspring)\b"),
    ("位移-走", r"\b(walk|walks|walking|stride|stroll|pace|march)\b"),
    ("位移-跑跳", r"\b(run|runs|jog|sprint|gallop|trot|bound|hop|hops|leap|jump|jumps|skip)\b"),
    ("原地摆动", r"\b(sway|sways|swinging|swings|bend|bends|twist|twists|lean|leans|bounce|bounces|float|floats|shift|shifts|extend|extends|reach|reaches|raise|raises|lower|lowers|rotate|rotates|moves|maintains|keeps|wiggles|shakes)\b"),
    ("待机站姿", r"\b(stand|stands|idle|wait|waits|holds? a stance|ready stance|breathing|rests|resting)\b"),
    ("舞蹈", r"\b(danc|breakdanc|groove|salsa|hip hop)\b"),
    ("战斗攻击", r"\b(punch|punches|kick|kicks|attack|attacks|strike|strikes|slash|slashes|shoot|shoots|stab|bite|bites|claw|claws|charge|charges|martial art|combat)\b"),
    ("倒地受击", r"\b(fall|falls|collapse|collapses|die|dies|knocked|stumble|stumbles|trip|trips|lying|hits the ground)\b"),
    ("蹲坐跪", r"\b(crouch|crouches|sit|sits|kneel|kneels|squat|squats|perches)\b"),
    ("游泳飞行", r"\b(swim|swims|swimming|flying|flies|fly|flap|flaps|glide|glides|dive|dives|splash)\b"),
    ("抓放操作", r"\b(pick|picks|grab|grabs|carry|carries|lift|lifts|throw|throws|push|pushes|pull|pulls|open|opens|close|closes|press|presses|hold|holds|touch|touches|push ups?)\b"),
    ("手势示意", r"\b(wave|waves|gesture|point|points|nod|nods|shake|shrug|shrugs|salute|beckon|clap|claps)\b"),
    ("情绪表达", r"\b(laugh|laughs|cheer|cheers|cry|cries|scream|screams|yawn|yawns|sleep|sleeps|pray|prays|think|thinks)\b"),
    ("爬行攀爬", r"\b(crawl|crawls|climb|climbs|creep|slither|slithers|scramble)\b"),
    ("进食嗅闻", r"\b(eat|eats|drink|drinks|sniff|sniffs|chew|graze|lick|licks|feeding)\b"),
    ("局部肢体", r"\b(mouth|jaw|tail|wing|petal|eyelid|tongue|stem|leaves|leaf|ear|ears|antenna|pincer|fin)\b"),
]


def load_captions(meta_dir):
    rows = []
    for ds in DATASETS:
        path = os.path.join(meta_dir, "export", ds, "motion_captions.json")
        if not os.path.isfile(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        for clip, cap in data.items():
            rows.append((ds, clip, cap))
    return rows


def classify(cap):
    t = re.sub(r"^An object\s+", "", cap.strip()).rstrip(".").lower()
    for name, rx in FAMILIES:
        if re.search(rx, t):
            return name, t
    return "其它", t


def main():
    ap = argparse.ArgumentParser(description="统计动作类别分布")
    ap.add_argument("--meta", required=True, help="元数据目录（含 export/<ds>/motion_captions.json）")
    ap.add_argument("--grep", default=None, help="额外查一个正则，看有没有、有多少")
    ap.add_argument("--top", type=int, default=8, help="每个类别打印多少条样例")
    args = ap.parse_args()

    rows = load_captions(args.meta)
    if not rows:
        raise SystemExit("没读到 caption，检查 --meta 指向的目录结构")

    total = len(rows)
    fam_of = {r[1]: classify(r[2])[0] for r in rows}
    fam_cnt = Counter(fam_of.values())
    fam_ds = Counter((fam_of[r[1]], r[0]) for r in rows)

    print("总片段 %d 条（mixamo/truebones/objaverse 合计）" % total)
    print()
    print("%-10s %6s %7s  %-8s %-9s %-9s" % ("类别", "数量", "占比", "mixamo", "truebones", "objaverse"))
    print("-" * 62)
    for fam, n in fam_cnt.most_common():
        print("%-10s %6d %6.1f%%  %-8d %-9d %-9d" % (
            fam, n, 100.0 * n / total,
            fam_ds[(fam, "mixamo")], fam_ds[(fam, "truebones")], fam_ds[(fam, "objaverse")]))

    print()
    print("占比解读： >5% 稳 / 1~5% 要多采 / <1% 容易失败 / 查不到 = 没学过")

    if args.grep:
        rx = re.compile(args.grep, re.IGNORECASE)
        hit = [(ds, clip, cap) for ds, clip, cap in rows if rx.search(cap)]
        print()
        print("=== 匹配 /%s/ 的片段：%d 条（占 %.2f%%）===" % (
            args.grep, len(hit), 100.0 * len(hit) / total))
        by_ds = Counter(h[0] for h in hit)
        print("   分布:", dict(by_ds))
        seen = set()
        shown = 0
        for ds, clip, cap in hit:
            key = re.sub(r"\s+", " ", cap.lower())
            if key in seen:
                continue
            seen.add(key)
            print("   [%-9s] %s" % (ds, cap))
            shown += 1
            if shown >= args.top * 2:
                break


if __name__ == "__main__":
    main()
