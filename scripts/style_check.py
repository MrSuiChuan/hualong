#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长文草稿体检: 段落节奏 / 句长 / 口语密度 / 黑名单。

用法:
  py -3 scripts/style_check.py draft.md --mode tech
  py -3 scripts/style_check.py draft.md --mode human --report check.md
"""
import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path

IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
CJK = re.compile(r"[\u4e00-\u9fff]")
# 622 篇语料里出现 0 次 → 硬禁
HARD_BLACKLIST = ["综上所述", "不难看出", "值得注意的是", "值得一提的是", "换言之",
                  "在当今时代", "让我们一起来", "希望本文", "本文将从"]
# 语料里偶尔出现, 但不能当结构连接词或包装词 → 提醒
SOFT_BLACKLIST = ["总而言之", "总的来说", "众所周知", "由此可见", "与此同时", "随着",
                  "赋能", "抓手", "闭环", "生态位", "多维度", "一站式", "助力", "打造",
                  "彰显", "首先", "其次", "再次"]
COLLOQUIAL = ["就是", "直接", "但是", "然后", "真的", "其实", "大家", "所以", "我觉得",
              "这玩意", "说实话", "毕竟", "离谱", "居然", "吧", "呢", "嘛"]
# 抽象名词(堆叠起来就是典型的 AI 腔)
ABSTRACT = ["效率", "体验", "能力", "生态", "价值", "体系", "流程", "机制", "模式", "路径",
            "维度", "层面", "场景", "赋能", "协同", "闭环", "链路", "抓手", "颗粒度",
            "认知", "底层逻辑", "方法论", "范式", "矩阵", "飞轮", "心智", "势能"]
# 程度副词(越少越好)
MODIFIER = ["非常", "极其", "十分", "极为", "相当", "格外", "无比", "尤其", "显著", "大幅", "极大"]

# 硬规则: 违反即不合格(来自 622 篇的 p10–p90 分位区间, 取保守外扩)
HARD = {"para_med": (20, 45), "sent_per_para": (1.0, 1.6), "colloquial": (7, 99),
        "first_para": (5, 45), "max_para": (0, 300)}
# 模式目标带: 只提示, 不判死刑(两种模式在真实语料里高度重叠)
TARGET = {
    "tech": {"long_ratio": (0.10, 0.30), "sentence_med": (25, 39), "last_para": (15, 70)},
    "human": {"long_ratio": (0.05, 0.18), "sentence_med": (21, 33), "last_para": (6, 30)},
}
STEP = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)\s*(?:\d+[.、]|[一二三四五六七八九十]+[.、])"
                  r"|第[一二三四五六七八九十]步")
URL = re.compile(r"https?://\S+")

# 人味分扣分线: 取自 622 篇语料的 p95(超出即视为跑偏)
SCORE_LIMITS = {"start_dup_rate": 0.06, "parallel_run": 5, "abstract_per_1k": 6.0,
                "modifier_per_1k": 3.7, "passive_per_1k": 2.7, "colloquial_min": 7.0}


def strip_md(s):
    s = IMG.sub("", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"[`*_>#\[\]()]", "", s).strip()


def parse(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    prose, in_code, steps = [], False, 0
    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.strip():
            continue
        if line.lstrip().startswith("#") or line.lstrip().startswith(">") or line.strip().startswith("|"):
            continue
        t = strip_md(line)
        if STEP.search(line):
            steps += 1
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s", line):
            continue
        # 链接占比过高的段落(下载地址、外链清单)不计入节奏统计
        url_chars = sum(len(u) for u in URL.findall(line))
        if url_chars > 0.3 * max(len(line), 1):
            continue
        if re.search(r"[\u4e00-\u9fff]", t) and len(t) >= 2:
            prose.append(t)
    return prose, steps


def measure(prose, steps):
    lens = [len(p) for p in prose]
    sentences = [x for p in prose for x in re.split(r"[。！？!?…]+", p) if len(x.strip()) >= 2]
    sent_lens = [len(x) for x in sentences]
    text = "".join(prose)
    chars = max(len(text), 1)
    starts = [s.strip()[:2] for s in sentences]
    dup = sum(1 for i in range(1, len(starts)) if starts[i] == starts[i - 1]) / max(len(starts) - 1, 1)
    parallel = cur = 1
    for i in range(1, len(sent_lens)):
        cur = cur + 1 if abs(sent_lens[i] - sent_lens[i - 1]) <= 3 else 1
        parallel = max(parallel, cur)
    return {
        "chars": len(text),
        "n_paras": len(lens),
        "para_med": round(st.median(lens), 1),
        "long_ratio": round(sum(1 for x in lens if x > 60) / len(lens), 3),
        "max_para": max(lens),
        "sent_per_para": round(len(sentences) / len(lens), 2),
        "sentence_med": round(st.median(sent_lens), 1) if sent_lens else 0,
        "colloquial_per_1k": round(sum(text.count(k) for k in COLLOQUIAL) / chars * 1000, 1),
        "first_para": lens[0],
        "last_para": lens[-1],
        "hard_hits": sorted({w for w in HARD_BLACKLIST if w in text}),
        "soft_hits": sorted({w for w in SOFT_BLACKLIST if w in text}),
        "start_dup_rate": round(dup, 3),
        "parallel_run": parallel,
        "abstract_per_1k": round(sum(text.count(k) for k in ABSTRACT) / chars * 1000, 2),
        "modifier_per_1k": round(sum(text.count(k) for k in MODIFIER) / chars * 1000, 2),
        "passive_per_1k": round(text.count("被") / chars * 1000, 2),
        "steps": steps,
    }


def check(m, mode):
    results = []

    def hard(name, value, lo, hi):
        ok = lo <= value <= hi
        results.append((name, "OK" if ok else "FAIL", f"{value}", f"{lo}–{hi}"))

    def target(name, value, lo, hi):
        ok = lo <= value <= hi
        results.append((name, "OK" if ok else "WARN", f"{value}", f"{lo}–{hi}"))

    hard("段落中位长度", m["para_med"], *HARD["para_med"])
    hard("单段句数", m["sent_per_para"], *HARD["sent_per_para"])
    hard("口语标记密度", m["colloquial_per_1k"], *HARD["colloquial"])
    hard("开场段长度", m["first_para"], *HARD["first_para"])
    longest_ok = m["max_para"] <= HARD["max_para"][1]
    results.append(("单段最长", "OK" if longest_ok else "WARN", str(m["max_para"]),
                    f"≤{HARD['max_para'][1]}(引用/清单可放宽)"))
    for k, label in [("long_ratio", "长段(>60字)占比"), ("sentence_med", "句长中位"),
                     ("last_para", "收尾段长度")]:
        target(label, m[k], *TARGET[mode][k])
    if m["hard_hits"]:
        results.append(("硬禁词", "FAIL", "、".join(m["hard_hits"]), "0 处"))
    else:
        results.append(("硬禁词", "OK", "0 处", "0 处"))
    if m["soft_hits"]:
        results.append(("包装词提醒", "WARN", "、".join(m["soft_hits"]), "尽量少用"))
    else:
        results.append(("包装词提醒", "OK", "无", "尽量少用"))
    if mode == "tech":
        ok = m["steps"] >= 2
        results.append(("编号步骤数", "OK" if ok else "WARN", str(m["steps"]), "教程类 ≥2"))
    else:
        ok = m["steps"] == 0
        results.append(("编号步骤数", "OK" if ok else "WARN", str(m["steps"]), "0"))
    return results


def human_score(m, mode):
    """人味分(0–100): 跑偏项越多分越低。"""
    score, reasons = 100, []
    lim = SCORE_LIMITS
    if m["colloquial_per_1k"] < lim["colloquial_min"]:
        score -= 15
        reasons.append("口语标记偏少")
    if m["start_dup_rate"] > lim["start_dup_rate"]:
        score -= 10
        reasons.append("句首重复偏多")
    if m["parallel_run"] > lim["parallel_run"]:
        score -= 10
        reasons.append("同构句连排")
    if m["abstract_per_1k"] > lim["abstract_per_1k"]:
        score -= 12
        reasons.append("抽象名词偏多")
    if m["modifier_per_1k"] > lim["modifier_per_1k"]:
        score -= 10
        reasons.append("程度副词偏多")
    if m["passive_per_1k"] > lim["passive_per_1k"]:
        score -= 6
        reasons.append("被动句偏多")
    if m["hard_hits"]:
        score -= 20
        reasons.append("命中硬禁词")
    band = TARGET[mode]["long_ratio"]
    if not (band[0] <= m["long_ratio"] <= band[1]):
        score -= 8
        reasons.append("长段占比偏离该模式")
    steps_ok = m["steps"] >= 2 if mode == "tech" else m["steps"] == 0
    if not steps_ok:
        score -= 5
        reasons.append("结构标记与该模式不符")
    return max(score, 0), reasons


def suggestions(m, mode, results):
    tips = []
    failed = {name for name, st_, _, _ in results if st_ == "FAIL"}
    warned = {name for name, st_, _, _ in results if st_ == "WARN"}
    if "段落中位长度" in failed:
        tips.append("把段落往 30 字左右调:长段拆句,短段别合并。")
    if "长段(>60字)占比" in warned:
        if m["long_ratio"] < TARGET[mode]["long_ratio"][0]:
            tips.append("长段偏少,该模式最长的那几段(步骤解释/背景交代)可以再写透一点。")
        else:
            tips.append("长段偏多,把超过 60 字的段落拆成 2–3 段。")
    if "单段最长" in failed or "单段最长" in warned:
        tips.append("有超长段落,多半是引用或清单:若是正文,按语义拆成 2–3 段。")
    if "口语标记密度" in failed or ("句长中位" in warned and m["sentence_med"] > TARGET[mode]["sentence_med"][1]):
        tips.append("句子太书面,补回口语连接词(就是/直接/其实/所以)和语气词(吧/呢/啊)。")
    elif "句长中位" in warned:
        tips.append("句子偏短碎,把同类短句合并成一句,或补一个解释性的长段。")
    if "开场段长度" in failed or "收尾段长度" in warned:
        tips.append("开场直接抛现象,收尾压成一句话,别总结。")
    if "编号步骤数" in warned and mode == "tech":
        tips.append("技术文若是教程/实操,主体应改成 2 个以上的加粗编号步骤;评测/观点类可忽略。")
    if "编号步骤数" in warned and mode == "human":
        tips.append("人文文通常不用编号步骤,检查这些编号是否必要。")
    if "硬禁词" in failed:
        tips.append("删掉硬禁词:" + "、".join(m["hard_hits"]))
    if "包装词提醒" in warned:
        tips.append("少用包装词:" + "、".join(m["soft_hits"]) + "(语料里偶尔出现,但不能当结构连接词)。")
    return tips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", help="草稿 markdown 路径")
    ap.add_argument("--mode", choices=["tech", "human"], required=True)
    ap.add_argument("--report", help="把体检报告写到指定文件")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出指标")
    args = ap.parse_args()

    prose, steps = parse(Path(args.draft))
    if not prose:
        print("[错误] 没解析到正文段落")
        sys.exit(2)
    m = measure(prose, steps)
    results = check(m, args.mode)
    ok = all(r[1] != "FAIL" for r in results)
    score, reasons = human_score(m, args.mode)

    if args.json:
        print(json.dumps({"mode": args.mode, "pass": ok, "human_score": score,
                          "score_notes": reasons, "metrics": m,
                          "checks": [{"name": n, "status": s, "value": v, "range": r} for n, s, v, r in results]},
                         ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)

    lines = [f"# 风格体检({'技术文' if args.mode == 'tech' else '人文文'})", "",
             f"- 正文字数: {m['chars']}", f"- 段落数: {m['n_paras']}",
             f"- 人味分: {score}/100" + (f"({'、'.join(reasons)})" if reasons else ""),
             f"- 结论: {'PASS' if ok else 'FAIL'}", "", "| 检查项 | 结果 | 实测 | 允许区间 |",
             "| --- | --- | --- | --- |"]
    for name, status, value, rng in results:
        lines.append(f"| {name} | {status} | {value} | {rng} |")
    tips = suggestions(m, args.mode, results)
    if score < 85 and not tips:
        tips.append("人味分偏低,重点看句首重复、同构句连排和抽象名词密度。")
    if tips:
        lines += ["", "## 修改建议", ""] + [f"- {t}" for t in tips]
    if m["chars"] < 800:
        lines += ["", "> 提示:草稿短于 800 字,统计噪声大,阈值只作参考。"]
    text = "\n".join(lines)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"\n报告已写入 {args.report}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
