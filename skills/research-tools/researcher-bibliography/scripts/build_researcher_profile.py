#!/usr/bin/env python3
"""Build a Chinese researcher-profile module for an author-literature-map run.

This is a v1 narrative layer over the evidence ledger. It does not change the
identity gate, the classified CSVs, or AUTHOR_MAP.json. It reads the finished
run and writes one `researcher_profile.md` next to the HTML map so every author
map has a stable, separate researcher-portrait module.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

try:
    import build_author_map_verdict as bv
except Exception:  # pragma: no cover
    bv = None


BUCKETS = {
    "胃肠肿瘤 / 消化道肿瘤": r"gastric|colorectal|colon|rectal|gastrointestinal|peritoneal|intestinal|stomach|digestive",
    "耐药 / 药物转运 / 药理": r"drug resistance|multidrug|resistance|ABCB1|ABCG2|P-gp|P-glycoprotein|transporter|chemotherapy|cytotoxic|drug",
    "类器官 / PDO / 功能药敏": r"organoid|organoids|PDO|patient-derived organoid|organoid-based drug sensitivity|organoid-based drug screening",
    "免疫治疗 / TME": r"immunotherapy|immune|T cell|T-cell|bispecific|HER2-CD3|engager|macrophage|CAF|STING|checkpoint",
    "纳米 / 金属 / 递送平台": r"nano|nanoparticle|metal|ruthenium|iridium|sonodynamic|photodynamic|metalloptosis|delivery|vesicle",
    "信号通路 / 机制": r"signaling|pathway|axis|phosphorylation|ubiquitination|glycolysis|autophagy|m6A|mutation|mechanism",
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def row_text(row: dict) -> str:
    return " ".join(str(row.get(k, "")) for k in ("title", "keywords", "venue", "abstract", "abstractNote"))


def clean_doi(value: str) -> str:
    return (value or "").replace("https://doi.org/", "").strip()


def csv_rows_for_profile(run_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    main = []
    for p in sorted(run_dir.glob("*_high_confidence_missing.csv")):
        main.extend(read_csv(p))
    for p in sorted(run_dir.glob("*_supplement.csv")):
        for row in read_csv(p):
            if str(row.get("route", "")).lower() != "review":
                main.append(row)
    review = []
    for p in sorted(run_dir.glob("*_needs_human_review.csv")):
        review.extend(read_csv(p))
    excluded = []
    for p in sorted(run_dir.glob("*_excluded_or_homonym_suspect.csv")):
        excluded.extend(read_csv(p))
    return main, review, excluded


def dedup_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        doi = clean_doi(str(row.get("doi", ""))).lower()
        title = re.sub(r"\W+", "", str(row.get("title", "")).casefold())
        key = f"doi:{doi}" if doi else f"title:{title}"
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def bucket_counts(rows: list[dict]) -> Counter:
    counts: Counter = Counter()
    for row in rows:
        text = row_text(row)
        for label, pattern in BUCKETS.items():
            if re.search(pattern, text, flags=re.I):
                counts[label] += 1
    return counts


def top_rows(rows: list[dict], pattern: str, limit: int = 8) -> list[dict]:
    hits = [r for r in rows if re.search(pattern, row_text(r), flags=re.I)]
    return sorted(hits, key=lambda r: str(r.get("year", "")), reverse=True)[:limit]


def load_profile(run_dir: Path, profile_path: Path | None) -> dict | None:
    path = profile_path or (run_dir / "profile.yaml")
    if bv is None or not path.exists():
        return None
    return bv.load_profile(path)


def bullet_join(items: list[str], max_items: int = 6) -> str:
    items = [i for i in items if i]
    if not items:
        return "未记录"
    return "、".join(items[:max_items])


def format_work(row: dict) -> str:
    year = row.get("year") or ""
    title = row.get("title") or ""
    venue = row.get("venue") or ""
    doi = clean_doi(str(row.get("doi") or ""))
    suffix = f"，{venue}" if venue else ""
    doi_text = f"，DOI `{doi}`" if doi else ""
    return f"- {year}｜{title}{suffix}{doi_text}"


def infer_position(main_rows: list[dict], counts: Counter, focus: str) -> str:
    total = len(main_rows)
    organoid = counts.get("类器官 / PDO / 功能药敏", 0)
    immune = counts.get("免疫治疗 / TME", 0)
    nano = counts.get("纳米 / 金属 / 递送平台", 0)
    resistance = counts.get("耐药 / 药物转运 / 药理", 0)
    gi = counts.get("胃肠肿瘤 / 消化道肿瘤", 0)

    parts = []
    if gi >= max(5, total * 0.15):
        parts.append("胃肠肿瘤转化研究")
    if resistance >= max(8, total * 0.2):
        parts.append("耐药与药物反应")
    if organoid >= 5:
        parts.append("PDO / 类器官功能验证")
    if immune >= 5:
        parts.append("肿瘤免疫治疗接口")
    if nano >= max(8, total * 0.2):
        parts.append("纳米/金属抗肿瘤平台合作")
    if not parts:
        parts.append(focus or "肿瘤转化研究")
    return "、".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True, help="full/ run directory")
    ap.add_argument("--author", required=True)
    ap.add_argument("--profile", type=Path, default=None)
    ap.add_argument("--focus", default="", help="Optional user-facing focus sentence")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    verdict_path = args.run_dir / "AUTHOR_MAP.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8")) if verdict_path.exists() else {}
    main_rows, review_rows, excluded_rows = csv_rows_for_profile(args.run_dir)
    main_rows = dedup_rows(main_rows)
    profile = load_profile(args.run_dir, args.profile) or {}

    counts = bucket_counts(main_rows)
    venues = Counter((r.get("venue") or "").strip() for r in main_rows if (r.get("venue") or "").strip())
    years = [int(str(r.get("year"))[:4]) for r in main_rows if str(r.get("year", ""))[:4].isdigit()]
    year_range = f"{min(years)}-{max(years)}" if years else "未记录"
    position = infer_position(main_rows, counts, args.focus)

    profile_name = args.author or profile.get("name")
    scholar = profile.get("google_scholar") or "未记录"
    accepted = bullet_join(list(profile.get("accepted_openalex_author_ids") or []))
    coauthors = bullet_join(list(profile.get("strong_coauthors") or []), 9)
    strong_venues = bullet_join(list(profile.get("strong_venues") or []), 9)
    homonym = profile.get("homonym_risk") or verdict.get("homonym_risk") or "未记录"

    bucket_lines = "\n".join(
        f"- {label}: {n} 条"
        for label, n in counts.most_common()
    ) or "- 未形成稳定主题桶"
    venue_lines = "\n".join(f"- {venue}: {n} 条" for venue, n in venues.most_common(10))

    organoid_rows = top_rows(main_rows, BUCKETS["类器官 / PDO / 功能药敏"], 10)
    immune_rows = top_rows(main_rows, BUCKETS["免疫治疗 / TME"], 8)
    organoid_lines = "\n".join(format_work(r) for r in organoid_rows) or "- 未在主线中检出明确类器官条目"
    immune_lines = "\n".join(format_work(r) for r in immune_rows) or "- 未在主线中检出明确免疫治疗条目"

    text = f"""# {profile_name} 研究者画像

> module: researcher_profile v1
> source_run: `{args.run_dir}`
> evidence: `AUTHOR_MAP.json` + classified CSVs + supplements

## 一句话画像

{profile_name} 更适合被理解为 **{position}** 型研究者。

## 身份与证据边界

- confirmed OpenAlex ID: {accepted}
- Google Scholar: {scholar}
- 年份跨度: {year_range}
- 主线纳入: {verdict.get('counts', {}).get('main', len(main_rows))} 条；待复核: {verdict.get('counts', {}).get('review', len(review_rows))} 条；排除: {verdict.get('counts', {}).get('excluded', len(excluded_rows))} 条
- 同名/拆分风险: {homonym}

## 研究问题画像

这个作者的核心不是单一技术，而是围绕“肿瘤治疗如何被功能性模型验证”组织研究。主线文献显示，该作者的研究经常把疾病场景、药物反应、机制解释和转化模型连在一起，而不是只停留在模型搭建或纯机制描述。

## 主题结构

{bucket_lines}

## 期刊与合作网络

高频或强信号期刊：

{venue_lines}

profile 中记录的强合作作者：{coauthors}

profile 中记录的强 venue：{strong_venues}

## 类器官 / PDO 线索

{organoid_lines}

## 免疫治疗 / TME 接口

{immune_lines}

## 对当前综述工作的启发

1. 适合顺着作者既有优势，把类器官写成 **功能性精准治疗模型**，而不是纯方法学平台。
2. 如果主题进入 immune-organoid，需要外部文献补足 ALI、TIL/PBMC 共培养、T-cell engager、CAR-T/CAR-NK、toxicity window 等方法和证据成熟度。
3. 文章组织上应保留作者习惯的客观综述和表格化优点，但每个小节都要补一个判断维度：这个模型能回答什么治疗问题、证据成熟到哪一级、不能外推什么。
4. 不要把所有 3D、纳米、机制或药物递送论文都等同于类器官证据；它们应作为相邻能力，而不是核心类器官主线。

## 后续优化点

- v1 画像按题名/关键词/venue 规则分桶，足够做阅读前定位，但不能替代全文级方法审计。
- 下一版可以加入作者顺位、通讯作者、基金/机构、关键论文引用网络和年度主题迁移。
"""

    out = args.out or (args.run_dir / "researcher_profile.md")
    out.write_text(text, encoding="utf-8")
    print(f"researcher_profile -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
