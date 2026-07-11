"""Build a structured, combination-ready TECHNIQUE TAXONOMY -> data/techniques.json.

Top-down: Opus enumerates named techniques per area with a rich schema. The `objects`
(what a technique acts on) and `mechanism` (how it works) fields are drawn from a
controlled vocabulary so the combination engine (generate_from_techniques.py) can score
compatibility: two techniques combine well when they share an object type but use
different mechanisms (a real twist, not redundancy).

Usage: PYTHONPATH=src python scripts/build_technique_taxonomy.py
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mathforge.llm import LLMClient, make_anthropic_backend

MODEL = "claude-opus-4-8"
OUT = Path("data/techniques.json")

AREAS = ["Number Theory", "Combinatorics", "Algebra", "Geometry",
         "Precalculus and Trigonometry", "Probability", "Inequalities"]

OBJECTS = ("integers primes prime-powers polynomials sequences sets graphs lattice-paths "
           "permutations points lines circles triangles angles vectors functions "
           "expressions generating-functions matrices complex-numbers probability-spaces")
MECHANISMS = ("valuation counting bijection invariant monovariant generating-function "
              "algebraic-identity bounding extremal symmetry recursion modular coloring "
              "double-counting probabilistic transform induction telescoping roots-of-unity")

PROMPT = """You are compiling a reference of NAMED problem-solving techniques for olympiad and competition mathematics, area: {area}.

List 40-60 distinct, well-known named techniques a strong olympiad student would recognize (e.g. Lifting the Exponent, Vieta Jumping, Chicken McNugget, Cycle Lemma, roots-of-unity filter, Chung-Feller, SOS, Burnside, the probabilistic method, telescoping, generating functions, ...). Prefer canonical, teachable methods over one-off tricks.

For EACH technique output an object with these exact keys:
- "id": short slug like "nt.lte"
- "name": canonical name
- "family": sub-area
- "one_liner": one sentence on what it computes/does
- "trigger": when you reach for it (one phrase)
- "objects": list of 1-3 tags chosen ONLY from: {objects}
- "mechanism": ONE tag chosen ONLY from: {mechanisms}
- "difficulty_band": [low, high] on the AoPS 1-10 scale
- "example_crux": one sentence describing a problem's key insight using it

Return ONLY a JSON array of these objects, nothing else."""


def _parse_json_array(text):
    """Parse object-by-object via balanced braces: robust to truncation, a single
    malformed entry, or trailing prose."""
    text = text or ""
    items, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = text[start:i + 1]
                try:
                    items.append(json.loads(chunk))
                except Exception:
                    try:
                        items.append(json.loads(re.sub(r",\s*([\]}])", r"\1", chunk)))
                    except Exception:
                        pass
                start = None
    return items


def build_area(client, area):
    prompt = PROMPT.format(area=area, objects=OBJECTS, mechanisms=MECHANISMS)
    try:
        txt = client.complete(prompt, purpose="taxonomy", effort="high").text
        items = _parse_json_array(txt)
    except Exception as e:
        print(f"  {area}: error {type(e).__name__}: {e}", flush=True)
        return area, []
    for it in items:
        it["area"] = area
        it.setdefault("source_count", 0)
        it.setdefault("combinability", {"pairs_well_with": [], "avoid_with": []})
    return area, items


def main():
    client = LLMClient(
        model=MODEL,
        backend=make_anthropic_backend(MODEL, effort="high", max_output_tokens=16000, timeout=600.0),
        purpose="taxonomy",
    )
    OUT.parent.mkdir(exist_ok=True)
    all_items, seen_ids = [], set()
    with ThreadPoolExecutor(max_workers=len(AREAS)) as ex:
        for f in as_completed([ex.submit(build_area, client, a) for a in AREAS]):
            area, items = f.result()
            kept = 0
            for it in items:
                tid = it.get("id") or (it.get("name", "").lower().replace(" ", "-"))
                if tid in seen_ids:
                    continue
                seen_ids.add(tid); it["id"] = tid
                all_items.append(it); kept += 1
            print(f"  {area}: {kept} techniques", flush=True)
    OUT.write_text(json.dumps(all_items, indent=1, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(f"\nwrote {len(all_items)} techniques -> {OUT}")
    print("by area:", dict(Counter(t["area"] for t in all_items)))
    print("by mechanism:", dict(Counter(t.get("mechanism") for t in all_items)))


if __name__ == "__main__":
    main()
