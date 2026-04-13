"""Refine eval harness — scores the live refine service against golden ground truth.

Walks every directory under ``eval/fixtures/refine_golden/``, runs the
real ``RefineService`` against each ``input_score.json`` (with the
fixture's ``title_hint`` / ``artist_hint``), and scores the output
against ``ground_truth.json``. Writes per-song and aggregate metrics
to ``refine-baseline.json``.

Requires ``OHSHEET_ANTHROPIC_API_KEY`` to be set. Costs real money.
Excluded from the default test suite and CI — run manually via
``make eval-refine``.

Metrics
-------
* title_exact_match            — case/whitespace-insensitive string equality
* composer_exact_match         — same, for composer
* key_match                    — true if tonic + mode match (Db:major == C#:major)
* time_signature_exact         — tuple equality
* tempo_within_5bpm            — |predicted - ground| <= 5
* section_label_f1             — F1 on section *labels* by greedy overlap match
* repeat_f1                    — F1 on (start_beat, end_beat) pairs (rounded to 0.1 beat)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.contracts import PianoScore  # noqa: E402
from shared.storage.local import LocalBlobStore  # noqa: E402

from backend.services.refine import RefineService  # noqa: E402


# Enharmonic tonic equivalence: normalize before comparison.
_ENHARMONIC = {
    "C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb",
    "Db": "Db", "Eb": "Eb", "Gb": "Gb", "Ab": "Ab", "Bb": "Bb",
    "C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "A": "A", "B": "B",
}


def _norm_key(key: str) -> str:
    if ":" not in key:
        return key.strip().lower()
    tonic, mode = key.split(":", 1)
    tonic = tonic.strip()
    return f"{_ENHARMONIC.get(tonic, tonic)}:{mode.strip().lower()}"


def _norm_str(s: str | None) -> str:
    if s is None:
        return ""
    return " ".join(s.split()).lower()


@dataclass
class FixtureResult:
    slug: str
    title_match: bool
    composer_match: bool
    key_match: bool
    time_sig_match: bool
    tempo_within_5bpm: bool
    section_f1: float
    repeat_f1: float
    predicted_title: str | None
    predicted_composer: str | None


def _score_sections(pred: list[dict[str, Any]], gt: list[dict[str, Any]]) -> float:
    """Simple F1 on section *labels* with overlap matching."""
    if not pred and not gt:
        return 1.0
    if not pred or not gt:
        return 0.0
    tp = 0
    for g in gt:
        for p in pred:
            overlap = max(0.0, min(p["end_beat"], g["end_beat"]) - max(p["start_beat"], g["start_beat"]))
            if overlap > 0 and p["label"] == g["label"]:
                tp += 1
                break
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gt) if gt else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _score_repeats(pred: list[dict[str, Any]], gt: list[dict[str, Any]]) -> float:
    if not pred and not gt:
        return 1.0
    if not pred or not gt:
        return 0.0
    def _key(r: dict[str, Any]) -> tuple[float, float, str]:
        return (round(r["start_beat"], 1), round(r["end_beat"], 1), r.get("kind", "simple"))
    pred_set = {_key(r) for r in pred}
    gt_set = {_key(r) for r in gt}
    tp = len(pred_set & gt_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(gt_set) if gt_set else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


async def _eval_fixture(svc: RefineService, fixture_dir: Path) -> FixtureResult:
    input_path = fixture_dir / "input_score.json"
    gt_path = fixture_dir / "ground_truth.json"
    score = PianoScore.model_validate(json.loads(input_path.read_text()))
    gt = json.loads(gt_path.read_text())

    refined = await svc.run(
        score,
        title_hint=gt.get("title_hint"),
        artist_hint=gt.get("artist_hint"),
    )

    md = refined.metadata if hasattr(refined, "metadata") else refined.score.metadata
    pred_sections = [
        {"start_beat": s.start_beat, "end_beat": s.end_beat, "label": s.label.value}
        for s in md.sections
    ]
    gt_sections = gt.get("sections", [])
    pred_repeats = [
        {"start_beat": r.start_beat, "end_beat": r.end_beat, "kind": r.kind}
        for r in md.repeats
    ]
    gt_repeats = gt.get("repeats", [])

    ts_gt = tuple(gt["time_signature"])
    tempo_gt = float(gt["tempo_bpm"])
    tempo_pred = md.tempo_map[0].bpm if md.tempo_map else 0.0

    return FixtureResult(
        slug=fixture_dir.name,
        title_match=_norm_str(md.title) == _norm_str(gt.get("title")),
        composer_match=_norm_str(md.composer) == _norm_str(gt.get("composer")),
        key_match=_norm_key(md.key) == _norm_key(gt["key_signature"]),
        time_sig_match=md.time_signature == ts_gt,
        tempo_within_5bpm=abs(tempo_pred - tempo_gt) <= 5,
        section_f1=_score_sections(pred_sections, gt_sections),
        repeat_f1=_score_repeats(pred_repeats, gt_repeats),
        predicted_title=md.title,
        predicted_composer=md.composer,
    )


async def _main(out_path: Path, fixtures_root: Path) -> int:
    if not os.environ.get("OHSHEET_ANTHROPIC_API_KEY"):
        print("ERROR: OHSHEET_ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2
    if not fixtures_root.is_dir():
        print(f"ERROR: fixtures root not found: {fixtures_root}", file=sys.stderr)
        return 2

    blob_root = REPO_ROOT / "blob"
    blob = LocalBlobStore(blob_root)
    svc = RefineService(blob_store=blob)

    fixture_dirs = sorted(
        d for d in fixtures_root.iterdir()
        if d.is_dir() and (d / "input_score.json").is_file() and (d / "ground_truth.json").is_file()
    )
    if not fixture_dirs:
        print(f"ERROR: no fixtures found under {fixtures_root}", file=sys.stderr)
        return 2

    results = []
    for fd in fixture_dirs:
        print(f"scoring {fd.name} ...")
        res = await _eval_fixture(svc, fd)
        results.append(res)
        print(
            f"  title={res.title_match} composer={res.composer_match} "
            f"key={res.key_match} ts={res.time_sig_match} "
            f"tempo<=5bpm={res.tempo_within_5bpm} "
            f"sec_f1={res.section_f1:.2f} rep_f1={res.repeat_f1:.2f}"
        )

    n = len(results)
    aggregate = {
        "count": n,
        "title_exact_match_pct": sum(r.title_match for r in results) / n * 100,
        "composer_exact_match_pct": sum(r.composer_match for r in results) / n * 100,
        "key_match_pct": sum(r.key_match for r in results) / n * 100,
        "time_signature_exact_pct": sum(r.time_sig_match for r in results) / n * 100,
        "tempo_within_5bpm_pct": sum(r.tempo_within_5bpm for r in results) / n * 100,
        "section_label_f1_avg": sum(r.section_f1 for r in results) / n,
        "repeat_f1_avg": sum(r.repeat_f1 for r in results) / n,
    }
    report = {
        "aggregate": aggregate,
        "per_song": [
            {
                "slug": r.slug,
                "title_match": r.title_match,
                "composer_match": r.composer_match,
                "key_match": r.key_match,
                "time_signature_exact": r.time_sig_match,
                "tempo_within_5bpm": r.tempo_within_5bpm,
                "section_label_f1": r.section_f1,
                "repeat_f1": r.repeat_f1,
                "predicted_title": r.predicted_title,
                "predicted_composer": r.predicted_composer,
            }
            for r in results
        ],
    }
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {out_path}")
    print(json.dumps(aggregate, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "refine-baseline.json",
        help="Output JSON path (default: refine-baseline.json)",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=REPO_ROOT / "eval" / "fixtures" / "refine_golden",
        help="Fixtures root (default: eval/fixtures/refine_golden/)",
    )
    args = parser.parse_args()
    rc = asyncio.run(_main(args.out, args.fixtures))
    sys.exit(rc)


if __name__ == "__main__":
    main()
