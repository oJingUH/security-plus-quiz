#!/usr/bin/env python3
"""
crypto.py — Security+ (SY0-701) crypto/algorithm values drill logic.

Pure Python 3 standard library. Holds ALL crypto-drill logic so quiz.py (the
CLI) and quiz_gui.py (the GUI) share one code path and cannot drift.

Responsibilities:
    - load and validate crypto.json (clean one-line error + exit 1 on missing
      or invalid JSON — never a raw traceback, same discipline as the bank
      loader in quiz.py)
    - build drill items in BOTH directions: algorithm -> value and
      value -> algorithm (e.g. "AES-256 - key size?" -> "256-bit" and "Which
      algorithm has a 160-bit digest?" -> "SHA-1")
    - shuffle with the caller's random.Random (same --seed semantics)
    - a question never repeats within a round
    - grade a free-text answer (case-insensitive, whitespace tolerant); expose
      the correct answer, a one-line explanation, and the source citation
    - merge crypto-drill stats into the shared stats store under a separate
      "crypto" section (backward compatible with stats.json files lacking it)

Both directions derive from a single entry: each entry carries an `algorithm`,
a `property` (what is being asked, e.g. "key size" or "digest"), and a `value`
(e.g. "256-bit" or "160-bit"). The `property` disambiguates the reverse prompt
so two algorithms sharing a value (e.g. two different 256-bit properties) stay
unambiguous.

Shared drill-module interface (mirrored by acronyms.py so both drills are
driven by one code path in each front-end):
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
DEFAULT_TABLE = os.path.join(SCRIPT_DIR, "crypto.json")

# Stats bucket and display tokens used by the front-ends.
STATS_KEY = "crypto"
TITLE = "CRYPTO DRILL"
Q_PREFIX = "C"

# Direction keys (internal) and their friendly labels.
DIR_MIXED = "mixed"
DIR_A2V = "a2v"          # algorithm -> value
DIR_V2A = "v2a"          # value -> algorithm

DIRECTION_LABELS = {
    DIR_MIXED: "mixed",
    DIR_A2V: "algorithm -> value",
    DIR_V2A: "value -> algorithm",
}

# Friendly (label, key) pairs for the callers' direction selectors.
DIRECTION_CHOICES = [
    ("mixed", DIR_MIXED),
    ("algorithm -> value", DIR_A2V),
    ("value -> algorithm", DIR_V2A),
]

_REQUIRED_FIELDS = ("id", "display", "algorithm", "property", "value", "source")


# ---------------------------------------------------------------- data I/O

def load_table_or_error(path=DEFAULT_TABLE):
    """Return (entries, error). Never raises: a missing file, invalid JSON, or a
    structurally malformed table is reported as a one-line error string."""
    if not os.path.exists(path):
        return None, "crypto table file not found: %s" % path
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "crypto table is not valid JSON: %s" % path
    if not isinstance(entries, list) or not entries:
        return None, "crypto table is empty or malformed: %s" % path
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            return None, ("crypto table entry #%d is not an object: %s"
                          % (i, path))
        for key in _REQUIRED_FIELDS:
            if key not in e:
                return None, ("crypto table entry #%d is missing %r: %s"
                              % (i, key, path))
    return entries, None


def load_table(path=DEFAULT_TABLE):
    """Return the crypto table, or exit(1) with a clean one-line message on
    error (mirrors quiz.load_bank — never a raw traceback)."""
    entries, err = load_table_or_error(path)
    if err:
        sys.exit("crypto.py: %s" % err)
    return entries


# ---------------------------------------------------------------- items

def _norm_text(s):
    """Normalise a free-text answer: lowercase and collapse all whitespace so
    matching is case-insensitive and tolerant of extra spaces/tabs/newlines."""
    return " ".join(str(s).strip().lower().split())


def _make_item(entry, direction):
    algorithm = entry["algorithm"]
    prop = entry["property"]
    value = entry["value"]
    if direction == DIR_A2V:
        prompt = "%s - %s?" % (algorithm, prop)
        answer = value
    else:
        prompt = "Which algorithm has a %s %s?" % (value, prop)
        answer = algorithm
    explanation = "%s has a %s of %s." % (algorithm, prop, value)
    return {
        "id": entry["id"],
        "direction": direction,
        "prompt": prompt,
        "answer": answer,
        "display": entry["display"],
        "algorithm": algorithm,
        "property": prop,
        "value": value,
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
        if direction in (DIR_MIXED, DIR_A2V):
            items.append(_make_item(e, DIR_A2V))
        if direction in (DIR_MIXED, DIR_V2A):
            items.append(_make_item(e, DIR_V2A))
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
    if item["direction"] == DIR_A2V:
        correct = got == _norm_text(item["value"])
        correct_answer = item["value"]
    else:
        correct = got == _norm_text(item["algorithm"])
        correct_answer = item["algorithm"]
    return correct, correct_answer, item["explanation"], item["source"]


def direction_label(direction):
    return DIRECTION_LABELS.get(direction, direction)


# ---------------------------------------------------------------- stats

def empty_stats():
    return {"correct": 0, "total": 0, "missed_ids": []}


def record_answer(stats, entry_id, correct):
    """Merge one crypto-drill answer into `stats` under the separate 'crypto'
    section so crypto accuracy never distorts per-domain accuracy. Creates the
    section on first use — backward compatible with stats.json files that have
    no 'crypto' key."""
    c = stats.setdefault(STATS_KEY, empty_stats())
    c["total"] += 1
    if correct:
        c["correct"] += 1
        if entry_id in c["missed_ids"]:
            c["missed_ids"].remove(entry_id)
    else:
        if entry_id not in c["missed_ids"]:
            c["missed_ids"].append(entry_id)
