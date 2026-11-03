#!/usr/bin/env python3
"""盘点所有动作：扫 outputs/ 下的 action.json，生成一张索引表。

为什么需要：动作攒到几十个之后，"哪个是生成的、哪个是库里的、哪条能循环"
靠翻目录是找不到的。索引表让下游（Unity 打包、状态机、资产盘点）只认一份。

用法
----
  python tools/action_index.py                      # 扫 outputs/
  python tools/action_index.py --root outputs --out outputs
  python tools/action_index.py --json-only          # 只要 JSON
"""

from __future__ import annotations

import argparse
import json
import os

import pipeline_config as cfg


def load(root):
    items, bad = [], []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "action.json" not in filenames:
            continue
        path = os.path.join(dirpath, "action.json")
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as exc:
            bad.append((path, str(exc)))
            continue
        d["_path"] = os.path.relpath(dirpath, root)
        # 文件是否真的在
        missing = [f for f in d.get("files", []) if not os.path.isfile(os.path.join(dirpath, f))]
        d["_missing"] = missing
        items.append(d)
    return items, bad


def qa_of(d):
    qa = d.get("qa") or {}
    if not qa:
        return "-"
    if qa.get("check") == "loop_report":
        best = qa.get("best_seam_ratio")
        return "接缝最好 %.2f / %d 条" % (best, qa.get("clips", 0)) if best is not None else "循环报告"
    ok = qa.get("ok")
    note = qa.get("note") or ""
    return ("通过: " if ok else "不通过: ") + note[:28] if note else ("通过" if ok else "不通过")


def main():
    ap = argparse.ArgumentParser(description="生成动作索引表")
    ap.add_argument("--root", default="outputs", help="扫描根目录，默认 outputs")
    ap.add_argument("--out", default=None, help="索引文件输出目录，默认 <root>")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        raise SystemExit("目录不存在：%s" % root)
    items, bad = load(root)
    if not items:
        raise SystemExit("没找到任何 action.json（先跑产线产出动作）")

    items.sort(key=lambda d: (d.get("source", ""), d.get("name", "")))
    by_source = {}
    for d in items:
        by_source[d.get("source", "?")] = by_source.get(d.get("source", "?"), 0) + 1

    print("扫描 %s：%d 个动作" % (args.root, len(items)))
    for s, n in sorted(by_source.items()):
        print("  %-8s %d" % (s, n))
    print()

    head = "| 名字 | 来源 | 角色 | 帧 | 循环 | 原地 | 质检 | 目录 |"
    sep = "|---|---|---|---|---|---|---|---|"
    lines = [head, sep]
    for d in items:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            d.get("name", "?"), d.get("source", "?"), d.get("rig") or "-",
            d.get("frames") if d.get("frames") is not None else "-",
            "是" if d.get("loopable") else "否",
            "是" if d.get("in_place") else "否",
            qa_of(d), d.get("_path", "")))
    table = "\n".join(lines)
    if not args.json_only:
        print(table)

    # 体检：重名 / 文件缺失 / 质检不通过
    seen, dups = {}, []
    for d in items:
        key = (d.get("source"), d.get("name"))
        if key in seen:
            dups.append((d.get("name"), seen[key], d.get("_path")))
        seen[key] = d.get("_path")
    missing = [(d.get("name"), m) for d in items for m in d.get("_missing", [])]
    failed = [d.get("name") for d in items
              if (d.get("qa") or {}).get("ok") is False]

    problems = []
    if dups:
        problems.append("重名 %d 组：%s" % (len(dups), dups[:3]))
    if missing:
        problems.append("文件缺失 %d 处：%s" % (len(missing), missing[:3]))
    if failed:
        problems.append("质检不通过 %d 个：%s" % (len(failed), failed[:5]))
    if bad:
        problems.append("action.json 读不了 %d 个：%s" % (len(bad), [b[0] for b in bad[:3]]))

    if problems and not args.json_only:
        print()
        for p in problems:
            print("  [注意] " + p)

    out_dir = os.path.abspath(args.out or root)
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "kind": "action-index",
        "version": cfg.version(),
        "root": args.root,
        "count": len(items),
        "by_source": by_source,
        "problems": problems,
        "items": [{k: v for k, v in d.items()} for d in items],
    }
    json_path = os.path.join(out_dir, "actions_index.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    md_path = os.path.join(out_dir, "actions_index.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("# 动作索引\n\n")
        fh.write("工程版本 %s，扫描 %s，共 %d 个动作。\n\n" % (
            cfg.version(), args.root, len(items)))
        fh.write("来源分布：" + "，".join("%s %d" % (k, v)
                                        for k, v in sorted(by_source.items())) + "\n\n")
        fh.write(table + "\n")
        if problems:
            fh.write("\n## 需要注意\n\n")
            for p in problems:
                fh.write("- " + p + "\n")
    if not args.json_only:
        print()
        print("已写出 %s" % json_path)
        print("已写出 %s" % md_path)


if __name__ == "__main__":
    main()
