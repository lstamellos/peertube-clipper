from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Iterable


CATEGORY_VALUES = {
    "quote",
    "argument",
    "revelation",
    "context",
    "conflict",
    "explanation",
    "other",
}

TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Anchor:
    start: float
    end: float
    category: str
    reason: str


@dataclass(frozen=True)
class ProposedCandidate:
    anchor_start: float
    anchor_end: float
    suggested_start: float
    suggested_end: float
    canonical_transcript: str
    category: str
    reason: str


def parse_timestamp(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:
        raise ValueError(f"invalid VTT timestamp: {value}")

    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_text(value: str) -> str:
    value = TAG_RE.sub("", value)
    value = html.unescape(value)
    return " ".join(value.split()).strip()


def parse_vtt(data: bytes | str) -> list[Cue]:
    text = data.decode("utf-8-sig", errors="strict") if isinstance(data, bytes) else data.lstrip("\ufeff")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    if not lines or not lines[0].strip().startswith("WEBVTT"):
        raise ValueError("caption snapshot is not WEBVTT")

    cues: list[Cue] = []
    index = 1
    while index < len(lines):
        line = lines[index].strip()

        if not line:
            index += 1
            continue

        if line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue

        if "-->" not in line:
            index += 1
            if index >= len(lines):
                break
            line = lines[index].strip()

        if "-->" not in line:
            index += 1
            continue

        start_raw, end_raw = [part.strip() for part in line.split("-->", 1)]
        end_token = end_raw.split()[0]

        try:
            start = parse_timestamp(start_raw)
            end = parse_timestamp(end_token)
        except (TypeError, ValueError):
            index += 1
            continue

        index += 1
        payload: list[str] = []
        while index < len(lines) and lines[index].strip():
            cleaned = clean_text(lines[index])
            if cleaned:
                payload.append(cleaned)
            index += 1

        cue_text = " ".join(payload).strip()
        if cue_text and end > start:
            cues.append(Cue(start=start, end=end, text=cue_text))

    cues.sort(key=lambda cue: (cue.start, cue.end))
    return cues


def build_windows(duration: float, size: float = 300.0, overlap: float = 40.0) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("invalid chunk size/overlap")

    windows: list[tuple[float, float]] = []
    step = size - overlap
    start = 0.0
    while start < duration:
        end = min(duration, start + size)
        windows.append((start, end))
        if end >= duration:
            break
        start += step
    return windows


def cues_in_range(cues: Iterable[Cue], start: float, end: float) -> list[Cue]:
    return [cue for cue in cues if cue.end > start and cue.start < end]


def seconds_label(value: float) -> str:
    milliseconds = int(round(max(0.0, value) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def build_prompt(cues: list[Cue], window_start: float, window_end: float) -> str:
    transcript = "\n".join(
        f"[{seconds_label(cue.start)} --> {seconds_label(cue.end)}] {cue.text}"
        for cue in cues
    )

    categories = ", ".join(sorted(CATEGORY_VALUES))
    return f"""You are an editorial clip locator. Analyze only the canonical caption cues below.
Return JSON only, with this exact top-level shape:
{{"anchors":[{{"start":12.3,"end":18.7,"category":"quote","reason":"brief editorial rationale"}}]}}

Rules:
- Propose 4 to 8 DISTINCT editorial anchors when the material supports them; fewer is allowed when it does not.
- Timestamps MUST be absolute source seconds and must stay inside {window_start:.3f}..{window_end:.3f}.
- Anchor only what is actually supported by the captions; do not invent text or facts.
- Prefer substantive quotes, arguments, explanations, revelations, context, or conflict.
- Do not create multiple anchors for the same editorial moment merely with slightly different boundaries.
- Partial/nested overlaps are allowed when they represent genuinely different editorial uses.
- category must be one of: {categories}.
- reason must be concise and must not quote long passages.

Canonical captions:
{transcript}
"""


def parse_anchor_response(raw: str, window_start: float, window_end: float, max_anchors: int = 8) -> list[Anchor]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    payload = json.loads(text)
    items = payload.get("anchors") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("model response does not contain anchors[]")

    anchors: list[Anchor] = []
    for item in items[:max_anchors]:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue

        category = str(item.get("category") or "other").strip().lower()
        if category not in CATEGORY_VALUES:
            category = "other"
        reason = " ".join(str(item.get("reason") or "").split())[:500]

        if start < window_start or end > window_end or end <= start:
            continue
        anchors.append(Anchor(start=start, end=end, category=category, reason=reason))

    return anchors


def candidate_from_anchor(
    cues: list[Cue],
    anchor: Anchor,
    context_before: float = 12.0,
    context_after: float = 12.0,
) -> ProposedCandidate | None:
    anchor_cues = cues_in_range(cues, anchor.start, anchor.end)
    if not anchor_cues:
        return None

    selected = cues_in_range(
        cues,
        max(0.0, anchor.start - context_before),
        anchor.end + context_after,
    )
    if not selected:
        return None

    transcript = " ".join(cue.text for cue in selected).strip()
    if not transcript:
        return None

    return ProposedCandidate(
        anchor_start=anchor.start,
        anchor_end=anchor.end,
        suggested_start=selected[0].start,
        suggested_end=selected[-1].end,
        canonical_transcript=transcript,
        category=anchor.category,
        reason=anchor.reason,
    )


def near_duplicate(left: ProposedCandidate, right: ProposedCandidate, tolerance: float = 2.5) -> bool:
    return (
        abs(left.anchor_start - right.anchor_start) <= tolerance
        and abs(left.anchor_end - right.anchor_end) <= tolerance
    )


def dedupe_candidates(candidates: list[ProposedCandidate]) -> list[ProposedCandidate]:
    result: list[ProposedCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.anchor_start, item.anchor_end)):
        if any(near_duplicate(candidate, existing) for existing in result):
            continue
        result.append(candidate)
    return result
