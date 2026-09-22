#!/usr/bin/env python3
"""
crypto.py — Security+ (SY0-701) crypto/algorithm-values and security-controls
drill logic.

Pure Python 3 standard library. Holds ALL crypto/controls-drill logic so
quiz.py (the CLI) and quiz_gui.py (the GUI) share one code path and cannot
drift.

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
TITLE = "CRYPTO & CONTROLS DRILL"
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


def _accept_display(answer, accept):
    """Human display of a correct answer that may have acceptable alternates.

    e.g. "256-bit (also: 384-bit)". Single-accept answers are returned verbatim."""
    others = [a for a in accept if _norm_text(a) != _norm_text(answer)]
    if not others:
        return answer
    return "%s (also: %s)" % (answer, ", ".join(others))


def _make_item(entry, direction, accept):
    algorithm = entry["algorithm"]
    prop = entry["property"]
    value = entry["value"]
    is_control = prop in ("control category", "control type")
    if direction == DIR_A2V:
        prompt = "%s - %s?" % (algorithm, prop)
        answer = value
    elif is_control:
        prompt = "Which %s means '%s'?" % (prop, value)
        answer = algorithm
    else:
        prompt = "Which algorithm has a %s %s?" % (value, prop)
        answer = algorithm
    if is_control:
        if direction == DIR_A2V:
            explanation = "%s is a %s meaning '%s'." % (algorithm, prop, value)
        else:
            explanation = "%s is the %s meaning '%s'." % (algorithm, prop, value)
    elif direction == DIR_A2V:
        explanation = "%s has a %s of %s." % (algorithm, prop, _accept_display(value, accept))
    elif len(accept) > 1:
        explanation = "%s each have a %s of %s." % (" and ".join(accept), prop, value)
    else:
        explanation = "%s has a %s of %s." % (algorithm, prop, value)
    return {
        "id": entry["id"],
        "direction": direction,
        "prompt": prompt,
        "answer": answer,
        "accept": list(accept),
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
    question within a round.

    Some facts legitimately collide: ECC has two key sizes (256-bit and
    384-bit), and both ECC and ChaCha20 use a 256-bit key. Each item therefore
    carries an `accept` list of every valid answer for its (algorithm, property)
    or (property, value) key — derived from the source table, not a
    hand-maintained exception list — so a prompt never has two different
    expected answers unless every one of them is acceptable."""
    a2v_accept = {}  # (algorithm, property) -> [values]
    v2a_accept = {}  # (property, value) -> [algorithms]
    for e in entries:
        k = (e["algorithm"], e["property"])
        a2v_accept.setdefault(k, [])
        if e["value"] not in a2v_accept[k]:
            a2v_accept[k].append(e["value"])
        k2 = (e["property"], e["value"])
        v2a_accept.setdefault(k2, [])
        if e["algorithm"] not in v2a_accept[k2]:
            v2a_accept[k2].append(e["algorithm"])
    items = []
    for e in entries:
        if direction in (DIR_MIXED, DIR_A2V):
            items.append(_make_item(e, DIR_A2V, a2v_accept[(e["algorithm"], e["property"])]))
        if direction in (DIR_MIXED, DIR_V2A):
            items.append(_make_item(e, DIR_V2A, v2a_accept[(e["property"], e["value"])]))
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

    Free-text matching is case-insensitive and tolerant of whitespace. The
    `accept` list (built by build_items from the source table) holds every
    acceptable answer, so an ambiguous fact (ECC's two key sizes, or ECC vs
    ChaCha20 both at 256-bit) accepts any of its valid values/algorithms."""
    got = _norm_text(raw)
    accept = item.get("accept") or [item["answer"]]
    correct = any(_norm_text(a) == got for a in accept)
    correct_answer = _accept_display(item["answer"], accept)
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
