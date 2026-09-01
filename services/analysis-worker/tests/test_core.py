import json

from clipper_worker.core import (
    Anchor,
    ProposedCandidate,
    build_prompt,
    build_windows,
    candidate_from_anchor,
    dedupe_candidates,
    parse_anchor_response,
    parse_vtt,
)


def sample_vtt() -> bytes:
    return b"""WEBVTT

00:00.000 --> 00:05.000
Intro

00:05.000 --> 00:10.000
First point

00:10.000 --> 00:15.000
Second point

00:15.000 --> 00:20.000
Conclusion
"""


def test_parse_vtt_and_context_expansion_uses_canonical_cues() -> None:
    cues = parse_vtt(sample_vtt())
    assert len(cues) == 4

    candidate = candidate_from_anchor(
        cues,
        Anchor(start=9.0, end=12.0, category="argument", reason="key point"),
        context_before=4.0,
        context_after=4.0,
    )

    assert candidate is not None
    assert candidate.anchor_start == 9.0
    assert candidate.anchor_end == 12.0
    assert candidate.suggested_start == 5.0
    assert candidate.suggested_end == 20.0
    assert candidate.canonical_transcript == "First point Second point Conclusion"


def test_five_minute_windows_keep_overlap() -> None:
    windows = build_windows(700.0, size=300.0, overlap=40.0)
    assert windows == [
        (0.0, 300.0),
        (260.0, 560.0),
        (520.0, 700.0),
    ]


def test_prompt_uses_copyable_cue_ids_and_forbids_timestamp_output() -> None:
    cues = parse_vtt(sample_vtt())
    prompt = build_prompt(cues, 0.0, 20.0)

    assert "[C001 | 00:00:00.000 --> 00:00:05.000] Intro" in prompt
    assert "[C004 | 00:00:15.000 --> 00:00:20.000] Conclusion" in prompt
    assert '"start_cue":"C002"' in prompt
    assert '"end_cue":"C004"' in prompt
    assert "Do NOT calculate, convert, rewrite, or return timestamps or numeric seconds." in prompt


def test_anchor_parser_maps_cue_ids_to_canonical_boundaries() -> None:
    cues = parse_vtt(sample_vtt())
    raw = json.dumps(
        {
            "anchors": [
                {
                    "start_cue": "C002",
                    "end_cue": "C003",
                    "category": "quote",
                    "reason": "key exchange",
                },
                {
                    "start_cue": "C999",
                    "end_cue": "C999",
                    "category": "quote",
                    "reason": "hallucinated cue",
                },
                {
                    "start_cue": "C004",
                    "end_cue": "C002",
                    "category": "quote",
                    "reason": "reverse range",
                },
                {
                    "start_cue": "C001",
                    "end_cue": "C001",
                    "category": "argument",
                    "reason": "single cue",
                },
            ]
        }
    )

    parsed = parse_anchor_response(raw, cues, max_anchors=8)

    assert parsed == [
        Anchor(start=5.0, end=15.0, category="quote", reason="key exchange"),
        Anchor(start=0.0, end=5.0, category="argument", reason="single cue"),
    ]


def test_anchor_parser_caps_results_before_mapping() -> None:
    cues = parse_vtt(sample_vtt())
    anchors = [
        {
            "start_cue": "C001",
            "end_cue": "C001",
            "category": "quote",
            "reason": f"anchor {index}",
        }
        for index in range(12)
    ]

    parsed = parse_anchor_response(
        json.dumps({"anchors": anchors}),
        cues,
        max_anchors=8,
    )

    assert len(parsed) == 8
    assert all(anchor.start == 0.0 for anchor in parsed)
    assert all(anchor.end == 5.0 for anchor in parsed)


def test_dedupe_removes_only_nearly_identical_anchor_boundaries() -> None:
    first = ProposedCandidate(
        anchor_start=100,
        anchor_end=110,
        suggested_start=90,
        suggested_end=120,
        canonical_transcript="same context",
        category="quote",
        reason="a",
    )
    duplicate = ProposedCandidate(
        anchor_start=101,
        anchor_end=111,
        suggested_start=90,
        suggested_end=120,
        canonical_transcript="same context",
        category="argument",
        reason="b",
    )
    nested_but_distinct = ProposedCandidate(
        anchor_start=103,
        anchor_end=108,
        suggested_start=90,
        suggested_end=120,
        canonical_transcript="same context",
        category="explanation",
        reason="c",
    )

    result = dedupe_candidates([first, duplicate, nested_but_distinct])

    assert first in result
    assert duplicate not in result
    assert nested_but_distinct in result