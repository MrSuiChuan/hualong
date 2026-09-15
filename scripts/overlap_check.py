#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""草稿原创性检查: 与参考语料比对, 找出重合片段。

用法:
  py -3 scripts/overlap_check.py draft.md --corpus D:\\path\\to\\corpus
  py -3 scripts/overlap_check.py draft.md --corpus ... --json

语料目录可以是 .md 文件组成的目录(递归查找)。
阈值: 最长重合 >= 30 字判不合格; >= 18 字或重合占比 >= 1% 判提醒。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

NGRAM = 12
FAIL_LEN = 30
WARN_LEN = 18
WARN_RATIO = 0.01

PUNCT_MAP = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":",
    "（": "(", "）": ")", "「": "[", "」": "]", "《": "<", "》": ">",
    "“": '"', "”": '"', "‘": "'", "’": "'", "、": ",", "—": "-",
    "－": "-", "【": "[", "】": "]", "…": ".", "　": "",
})


def normalize(text):
    """去掉 markdown 与空白, 统一标点, 便于比对。"""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[#>*`_~]", "", t)
    t = re.sub(r"\s+", "", t)
    return t.translate(PUNCT_MAP)


def grams(text, n=NGRAM):
    return {text[i:i + n] for i in range(max(len(text) - n + 1, 0))}


def extend(draft, other, seed):
    """以 seed 为锚点向两侧扩展, 返回最长公共片段。"""
    best = seed
    for pos in [m.start() for m in re.finditer(re.escape(seed), draft)]:
        opos = other.find(seed)
        while opos != -1:
            left = 0
            while pos - left - 1 >= 0 and opos - left - 1 >= 0 and draft[pos - left - 1] == other[opos - left - 1]:
                left += 1
            right = 0
            while (pos + len(seed) + right < len(draft) and opos + len(seed) + right < len(other)
                   and draft[pos + len(seed) + right] == other[opos + len(seed) + right]):
                right += 1
            span = draft[pos - left: pos + len(seed) + right]
            if len(span) > len(best):
                best = span
            opos = other.find(seed, opos + 1)
    return best


def scan(draft_text, corpus_dir, min_report=8):
    """把草稿和语料目录逐篇比对, 返回 (最长重合长度, 命中列表, 比对篇数)。"""
    draft = normalize(draft_text)
    if len(draft) < NGRAM:
        return 0, [], 0
    draft_grams = grams(draft)
    root = Path(corpus_dir)
    if not root.exists():
        raise FileNotFoundError(f"语料目录不存在: {root}")
    files = [fp for fp in sorted(root.rglob("*.md"))
             if not fp.name.startswith("_") and not fp.name.lower().startswith("readme")]
    if not files:
        raise ValueError(f"语料目录里没有可比对的 .md 文件: {root}")
    hits = []
    for fp in files:
        other = normalize(fp.read_text(encoding="utf-8"))
        if len(other) < NGRAM:
            continue
        common = draft_grams & grams(other)
        if not common:
            continue
        longest = ""
        for g in common:
            span = extend(draft, other, g)
            if len(span) > len(longest):
                longest = span
        if len(longest) >= min_report:
            hits.append({"file": str(fp), "length": len(longest), "snippet": longest})
    hits.sort(key=lambda h: -h["length"])
    return (hits[0]["length"] if hits else 0), hits, len(files)


def verdict_for(max_len, draft_len):
    if max_len >= FAIL_LEN:
        return "FAIL"
    if max_len >= WARN_LEN or (draft_len and max_len / draft_len >= WARN_RATIO):
        return "WARN"
    return "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", help="草稿 markdown 路径")
    ap.add_argument("--corpus", default=os.environ.get("CORPUS_DIR", ""),
                    help="参考语料目录(递归查找 .md), 或用环境变量 CORPUS_DIR")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.corpus:
        print("[错误] 需要 --corpus 指定语料目录, 或设置环境变量 CORPUS_DIR")
        sys.exit(2)
    corpus_dir = Path(args.corpus)
    if not corpus_dir.exists():
        print(f"[错误] 语料目录不存在: {corpus_dir}")
        sys.exit(2)

    draft_raw = Path(args.draft).read_text(encoding="utf-8")
    draft = normalize(draft_raw)
    if len(draft) < NGRAM:
        print("[错误] 草稿太短, 无法比对")
        sys.exit(2)
    try:
        max_len, hits, n_files = scan(draft_raw, corpus_dir)
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] {e}")
        print("       没有语料就无法做重合检测;请在交付说明里写明'未做原创性比对'。")
        sys.exit(2)
    ratio = (max_len / len(draft)) if max_len else 0.0
    verdict = verdict_for(max_len, len(draft))

    if args.json:
        print(json.dumps({"verdict": verdict, "max_match": max_len, "ratio": round(ratio, 5),
                          "draft_chars": len(draft), "corpus_files": n_files,
                          "hits": hits[:10]}, ensure_ascii=False, indent=2))
        sys.exit(0 if verdict == "PASS" else 1)

    lines = ["# 原创性检查", "",
             f"- 草稿有效字数: {len(draft)}", f"- 比对语料: {n_files} 篇",
             f"- 最长重合片段: {max_len} 字", f"- 结论: {verdict}", ""]
    if hits:
        lines += ["| 重合长度 | 来源文件 | 片段(截断) |", "| --- | --- | --- |"]
        for h in hits[:10]:
            lines.append(f"| {h['length']} | {Path(h['file']).name} | {h['snippet'][:40]} |")
        lines += ["", "重合片段必须重写:换句式、换叙述顺序、换用词,不要只改标点或换同义词。"]
    else:
        lines.append("没有发现 {}+ 字的连续重合,原创性良好。".format(NGRAM))
    text = "\n".join(lines)
    print(text)
    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
