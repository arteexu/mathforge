"""Diversity audit: tag every crux in the bank with technique(s) from the taxonomy,
then report coverage (which of the 381 techniques are over/under-represented).

This is the plan's "bottom-up" step: it grounds the taxonomy in real problems, writes
data/technique_coverage.json, and updates each technique's `source_count` in
data/techniques.json so the combination generator can prefer under-used techniques.

Usage: PYTHONPATH=src python scripts/audit_technique_coverage.py [limit] [workers]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient, make_anthropic_backend
from mathforge.schema import Problem

MODEL = "claude-opus-4-8"
TECH_PATH = Path("data/techniques.json")
OUT = Path("data/technique_coverage.json")
BATCH = 18


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    techs = json.loads(TECH_PATH.read_text())
    ids = {t["id"] for t in techs}
    by_area_menu = defaultdict(list)
    for t in techs:
        by_area_menu[t["area"]].append(f"{t['id']} | {t['name']}")
    menu = "\n".join(f"[{a}]\n" + "\n".join(v) for a, v in by_area_menu.items())

    db.init_db()
    with db.session_scope() as ses:
        cruxes = [
            (p.id, p.topic, (p.provenance or {}).get("crux"))
            for p in ses.exec(db.training_problems_select()).all()
            if (p.provenance or {}).get("crux")
        ]
    if limit:
        cruxes = cruxes[:limit]
    print(f"auditing {len(cruxes)} cruxes against {len(techs)} techniques", flush=True)

    client = LLMClient(model=MODEL,
                       backend=make_anthropic_backend(MODEL, max_output_tokens=1200, timeout=120.0),
                       purpose="audit")

    PROMPT = ("Tag each competition-math CRUX with the technique id(s) it most relies on, "
              "chosen ONLY from this menu (id | name):\n{menu}\n\n"
              "For each numbered crux output one line `<n>: <id>` (optionally `<id1>, <id2>` if two "
              "are essential; `none` if nothing fits). Output only these lines.\n\nCRUXES:\n{items}")

    def tag_batch(batch):
        items = "\n".join(f"{i+1}. {c[:280]}" for i, (_, _, c) in enumerate(batch))
        try:
            t = client.complete(PROMPT.format(menu=menu, items=items), purpose="audit").text
        except Exception as e:
            return [(pid, []) for pid, _, _ in batch], str(e)
        got = {}
        for line in (t or "").splitlines():
            m = re.match(r"\s*(\d+)\s*[:.]\s*(.+)", line)
            if not m:
                continue
            idx = int(m.group(1)) - 1
            tag_ids = [x.strip() for x in re.split(r"[,/;]", m.group(2)) if x.strip() in ids]
            if 0 <= idx < len(batch):
                got[idx] = tag_ids
        return [(batch[i][0], got.get(i, [])) for i in range(len(batch))], None

    batches = [cruxes[i:i + BATCH] for i in range(0, len(cruxes), BATCH)]
    counts = Counter()
    prob_tags = {}
    tagged = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(tag_batch, b) for b in batches]):
            res, err = f.result()
            if err:
                print("  batch error:", err[:80], flush=True); continue
            for pid, tag_ids in res:
                prob_tags[pid] = tag_ids
                for tid in tag_ids:
                    counts[tid] += 1
                if tag_ids:
                    tagged += 1

    # update source_count in techniques.json + persist per-problem tags
    for t in techs:
        t["source_count"] = counts.get(t["id"], 0)
    TECH_PATH.write_text(json.dumps(techs, indent=1, ensure_ascii=False), encoding="utf-8")
    with db.session_scope() as ses:
        for pid, tag_ids in prob_tags.items():
            if not tag_ids:
                continue
            p = ses.get(Problem, pid)
            prov = dict(p.provenance or {})
            # Keep generator conditioning immutable.  A later classifier pass
            # records what it inferred without overwriting required techniques.
            prov["inferred_techniques"] = tag_ids
            p.provenance = prov
            ses.add(p)

    name = {t["id"]: t["name"] for t in techs}
    area = {t["id"]: t["area"] for t in techs}
    mech = {t["id"]: t.get("mechanism") for t in techs}
    covered = [tid for t in techs if (tid := t["id"]) and counts.get(tid, 0) > 0]
    gaps = [t["id"] for t in techs if counts.get(t["id"], 0) == 0]
    by_area = Counter(area[t] for t in counts.elements())
    by_mech = Counter(mech[t] for t in counts.elements())
    OUT.write_text(json.dumps({"scope": "train_only_nonfrozen",
                               "total_cruxes": len(cruxes), "tagged_cruxes": tagged,
                               "counts": dict(counts), "covered": covered, "gaps": gaps,
                               "by_area": dict(by_area), "by_mechanism": dict(by_mech)},
                              indent=1), encoding="utf-8")

    print(f"\n=== COVERAGE: {len(covered)}/{len(techs)} techniques represented; "
          f"{tagged}/{len(cruxes)} cruxes tagged ===")
    print("\nTop 12 techniques by crux count:")
    for tid, n in counts.most_common(12):
        print(f"  {n:4}  {name[tid]}  [{area[tid]}]")
    print("\nCrux distribution by area:", dict(by_area.most_common()))
    print("\nGaps (0 cruxes) per area:")
    gap_by_area = Counter(area[g] for g in gaps)
    for a, n in gap_by_area.most_common():
        sample = [name[g] for g in gaps if area[g] == a][:4]
        print(f"  {a}: {n} unused  e.g. {', '.join(sample)}")
    print(f"\nwrote {OUT} + updated source_count in {TECH_PATH}")


if __name__ == "__main__":
    main()
