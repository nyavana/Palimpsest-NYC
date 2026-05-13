"""Generates ~150 candidate questions from the corpus + neighborhood list.

Pipeline:
  1. Pull a sample of places from /internal/retrieve (broad queries) + direct DB.
  2. Template into per-category candidate questions.
  3. Write a curation TSV with one column for `accept` (Y/N), one for
     `edited_question`, and one for `notes`. You manually cull/edit to 100.

The synthesizer is intentionally rule-based, not LLM-based — you want the
process to be deterministic and inspectable.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Manhattan neighborhoods used by the per-neighborhood category and as the
# spatial buckets for the per-region aggregate breakdown.
NEIGHBORHOODS: list[str] = [
    "Inwood",
    "Washington Heights",
    "Harlem",
    "Morningside Heights",
    "Upper West Side",
    "Upper East Side",
    "Midtown",
    "Hell's Kitchen",
    "Chelsea",
    "Flatiron District",
    "Greenwich Village",
    "SoHo",
    "Lower East Side",
    "Tribeca",
    "Financial District",
]


@dataclass(frozen=True)
class Place:
    name: str
    neighborhood: str
    source_type: str  # "wikipedia" | "osm" | "wikidata"


def template_single_place(p: Place) -> list[str]:
    return [
        f"Tell me about the {p.name}.",
        f"What is the history of the {p.name}?",
        f"Describe the architecture of the {p.name}.",
        f"Why is the {p.name} significant in {p.neighborhood}?",
    ]


def template_multi_place(places: list[Place]) -> list[str]:
    if len(places) < 2:
        return []
    a, b = places[0], places[1]
    return [
        f"Plan a walking tour that hits both the {a.name} and the {b.name}.",
        f"Compare the {a.name} and the {b.name}.",
        f"What can I see if I walk from the {a.name} to the {b.name}?",
    ]


def template_geographic(neighborhood: str, radius_m: int = 400) -> list[str]:
    return [
        f"What interesting places are within {radius_m} meters of {neighborhood} in Manhattan?",
        f"Show me landmarks in {neighborhood}, Manhattan.",
        f"Plan a short walk through {neighborhood}.",
    ]


def template_per_neighborhood(picks: list[str]) -> list[str]:
    out: list[str] = []
    for n in picks:
        # FiDi alias for Financial District in the eval set
        if n == "FiDi":
            out.append("Plan a walking tour of historic buildings in FiDi (Financial District).")
        else:
            out.append(f"Plan a walking tour of {n} for a first-time visitor.")
    return out


def template_out_of_scope() -> list[str]:
    return [
        "Take me on a walking tour of brownstones in Brooklyn.",
        "What's the history of the Apollo Theater? (note: out of Manhattan scope)",
        "Plan a walk through Astoria, Queens.",
        "Tell me about the Eiffel Tower.",
        "Plan a tour of Roosevelt Island gardens.",
        "What's there to see in Hoboken across the river?",
        "Show me landmarks in the Bronx Zoo area.",
        "Take me to the fictional 'Vandelay Plaza' on 42nd Street.",
        "Plan a walking tour of Coney Island.",
        "Tell me about Williamsburg's industrial history.",
    ]


def write_candidate_tsv(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "question", "category", "region", "expected_source_types",
        "accept", "edited_question", "notes",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "accept": "", "edited_question": "", "notes": ""})


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Synthesize candidate eval questions.")
    parser.add_argument("--places", type=Path, required=True,
                        help="TSV of seed places (columns: name, neighborhood, source_type).")
    parser.add_argument("--out", type=Path, default=Path("docs/eval/questions/manhattan-100/candidates.tsv"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(list(argv) if argv is not None else None)

    rng = random.Random(args.seed)

    # Load seed places.
    places: list[Place] = []
    with args.places.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            places.append(Place(
                name=row["name"].strip(),
                neighborhood=row["neighborhood"].strip(),
                source_type=row.get("source_type", "wikipedia").strip(),
            ))

    rng.shuffle(places)

    candidates: list[dict] = []

    # 30 single-place
    for p in places[:30]:
        # Pick one template variant deterministically per place
        q = template_single_place(p)[0]
        candidates.append({
            "question": q, "category": "single_place",
            "region": p.neighborhood, "expected_source_types": p.source_type,
        })

    # 25 multi-place
    for i in range(25):
        pair = places[30 + 2 * i : 30 + 2 * i + 2]
        qs = template_multi_place(pair)
        if qs:
            candidates.append({
                "question": qs[0], "category": "multi_place",
                "region": f"{pair[0].neighborhood} / {pair[1].neighborhood}",
                "expected_source_types": ",".join(sorted({pair[0].source_type, pair[1].source_type})),
            })

    # 20 geographic
    rng.shuffle(NEIGHBORHOODS)
    for n in NEIGHBORHOODS[:20]:
        q = template_geographic(n)[0]
        candidates.append({
            "question": q, "category": "geographic",
            "region": n, "expected_source_types": "osm,wikipedia",
        })

    # 15 per-neighborhood
    picks = NEIGHBORHOODS[:15]
    for q in template_per_neighborhood(picks):
        candidates.append({
            "question": q, "category": "per_neighborhood",
            "region": "varied", "expected_source_types": "osm,wikipedia",
        })

    # 10 out-of-scope
    for q in template_out_of_scope():
        candidates.append({
            "question": q, "category": "out_of_scope",
            "region": "outside_manhattan", "expected_source_types": "",
        })

    write_candidate_tsv(args.out, candidates)
    print(f"wrote {len(candidates)} candidates → {args.out}")


if __name__ == "__main__":
    main()
