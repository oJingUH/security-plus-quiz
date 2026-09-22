#!/usr/bin/env python3
"""
acronyms.py — Security+ (SY0-701) acronym drill logic.

Pure Python 3 standard library. Holds ALL acronym-drill logic so quiz.py (the
CLI) and quiz_gui.py (the GUI) share one code path and cannot drift.

Responsibilities:
    - load and validate acronyms.json (clean one-line error + exit 1 on missing
      or invalid JSON — never a raw traceback, same discipline as the bank
      loader in quiz.py)
    - build drill items in BOTH directions: acronym -> expansion and
      expansion -> acronym
    - shuffle with the caller's random.Random (same --seed semantics)
    - a question never repeats within a round
    - grade a free-text answer (case-insensitive, whitespace tolerant); expose
      the correct answer, a one-line explanation, and the source citation
    - merge acronym-drill stats into the shared stats store under a separate
      "acronyms" section (backward compatible with stats.json files lacking it)

Shared drill-module interface (mirrored by crypto.py so both drills are driven
by one code path in each front-end):
    DEFAULT_TABLE, STATS_KEY, TITLE, Q_PREFIX
    DIR_MIXED + direction constants, DIRECTION_LABELS, DIRECTION_CHOICES
    load_table_or_error(path), load_table(path)
    build_items(table, direction), select_items(items, rng, length)
    grade(item, raw), direction_label(direction)
    empty_stats(), record_answer(stats, entry_id, correct)

This module is imported; it is not an entry point.
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TABLE = os.path.join(SCRIPT_DIR, "acronyms.json")

# Stats bucket and display tokens used by the front-ends.
STATS_KEY = "acronyms"
TITLE = "ACRONYM DRILL"
Q_PREFIX = "A"

# Direction keys (internal) and their friendly labels.
DIR_MIXED = "mixed"
DIR_A2E = "a2e"          # acronym -> expansion
DIR_E2A = "e2a"          # expansion -> acronym

DIRECTION_LABELS = {
    DIR_MIXED: "mixed",
    DIR_A2E: "acronym -> expansion",
    DIR_E2A: "expansion -> acronym",
}

# Friendly (label, key) pairs for the callers' direction selectors.
DIRECTION_CHOICES = [
    ("mixed", DIR_MIXED),
    ("acronym -> expansion", DIR_A2E),
    ("expansion -> acronym", DIR_E2A),
]

_REQUIRED_FIELDS = ("id", "display", "acronym", "expansion", "source")


# ---------------------------------------------------------------- data I/O

def load_table_or_error(path=DEFAULT_TABLE):
    """Return (entries, error). Never raises: a missing file, invalid JSON, or a
    structurally malformed table is reported as a one-line error string."""
    if not os.path.exists(path):
        return None, "acronym table file not found: %s" % path
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "acronym table is not valid JSON: %s" % path
    if not isinstance(entries, list) or not entries:
        return None, "acronym table is empty or malformed: %s" % path
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            return None, ("acronym table entry #%d is not an object: %s"
                          % (i, path))
        for key in _REQUIRED_FIELDS:
            if key not in e:
                return None, ("acronym table entry #%d is missing %r: %s"
                              % (i, key, path))
    return entries, None


def load_table(path=DEFAULT_TABLE):
    """Return the acronym table, or exit(1) with a clean one-line message on
    error (mirrors quiz.load_bank — never a raw traceback)."""
    entries, err = load_table_or_error(path)
    if err:
        sys.exit("acronyms.py: %s" % err)
    return entries


# ---------------------------------------------------------------- items

def _norm_text(s):
    """Normalise a free-text answer: lowercase and collapse all whitespace so
    matching is case-insensitive and tolerant of extra spaces/tabs/newlines."""
    return " ".join(str(s).strip().lower().split())


def _make_item(entry, direction):
    acronym = entry["acronym"]
    expansion = entry["expansion"]
    if direction == DIR_A2E:
        prompt = "What does %s stand for?" % acronym
        answer = expansion
    else:
        prompt = "Which acronym means '%s'?" % expansion
        answer = acronym
    explanation = "%s stands for %s." % (acronym, expansion)
    return {
        "id": entry["id"],
        "direction": direction,
        "prompt": prompt,
        "answer": answer,
        "display": entry["display"],
        "acronym": acronym,
        "expansion": expansion,
        "explanation": explanation,
        "source": entry["source"],
    }


def build_items(entries, direction=DIR_MIXED):
    """Return drill items in the requested direction(s).

    'mixed' yields two items per entry (one each way). Every item is a distinct
    (id, direction) prompt, so shuffling a built list can never repeat a
    question within a round."""
    items = []
    for e in entries:
        if direction in (DIR_MIXED, DIR_A2E):
            items.append(_make_item(e, DIR_A2E))
        if direction in (DIR_MIXED, DIR_E2A):
            items.append(_make_item(e, DIR_E2A))
    return items


def select_items(items, rng, length=None):
    """Return the round pool: all items, or a random sample of `length`
    (never more than available). Callers shuffle the result before playing.
    Sampling is without replacement, so a question never repeats in a round."""
    if length is None:
        return list(items)
    return rng.sample(items, min(length, len(items)))


def grade(item, raw):
    """Return (correct, correct_answer, explanation, source).

    Free-text matching is case-insensitive and tolerant of whitespace."""
    got = _norm_text(raw)
    if item["direction"] == DIR_A2E:
        correct = got == _norm_text(item["expansion"])
        correct_answer = item["expansion"]
    else:
        correct = got == _norm_text(item["acronym"])
        correct_answer = item["acronym"]
    return correct, correct_answer, item["explanation"], item["source"]


def direction_label(direction):
    return DIRECTION_LABELS.get(direction, direction)


# ---------------------------------------------------------------- stats

def empty_stats():
    return {"correct": 0, "total": 0, "missed_ids": []}


def record_answer(stats, entry_id, correct):
    """Merge one acronym-drill answer into `stats` under the separate
    'acronyms' section so acronym accuracy never distorts per-domain accuracy.
    Creates the section on first use — backward compatible with stats.json
    files that have no 'acronyms' key."""
    a = stats.setdefault(STATS_KEY, empty_stats())
    a["total"] += 1
    if correct:
        a["correct"] += 1
        if entry_id in a["missed_ids"]:
            a["missed_ids"].remove(entry_id)
    else:
        if entry_id not in a["missed_ids"]:
            a["missed_ids"].append(entry_id)
