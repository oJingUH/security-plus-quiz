#!/usr/bin/env python3
"""
quiz.py — Security+ (SY0-701) terminal quiz game.

Pure Python 3 standard library. No dependencies, no TUI framework.

Modes:
    1) Quick 10          10 random questions across all domains
    2) Domain drill      pick domains (1-5 or all) + length (10/20/all)
    3) Acronym drill     grind acronyms both ways (acronym <-> expansion)
    4) Crypto drill      grind crypto/algorithm values both ways
    5) Review missed     replay questions previously answered incorrectly
    6) Review acronyms   replay acronym items previously answered incorrectly
    7) Review crypto     replay crypto items previously answered incorrectly
    8) Stats             lifetime & per-domain accuracy, streaks, hardest domain
    9) Quit

Answer with a-d or 1-4 (multiple choice) or t/f (true/false); the acronym and
crypto drills take free-text answers. Enter `q` at any prompt to return to the
menu. Progress persists to stats.json.

Flags:
    --selftest              scripted 10-question round, fixed seed, no stdin
    --selftest --acronyms   scripted acronym-drill round, no stdin
    --selftest --crypto     scripted crypto-drill round, no stdin
    --selftest --review     scripted review-missed-questions round, no stdin
    --selftest --review-acronyms  scripted review-missed-acronyms round
    --selftest --review-crypto    scripted review-missed-crypto round
    --seed N                deterministic shuffling
    --bank PATH             explicit question-bank path

Colour is used when stdout is a tty and NO_COLOR is unset.
"""

import argparse
import json
import os
import random
import sys
import tempfile
import textwrap

import acronyms
import crypto

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BANK = os.path.join(SCRIPT_DIR, "questions.json")
DEFAULT_STATS = os.path.join(SCRIPT_DIR, "stats.json")

DOMAIN_NAMES = {
    1: "General Security Concepts",
    2: "Threats, Vulnerabilities, and Mitigations",
    3: "Security Architecture",
    4: "Security Operations",
    5: "Security Program Management and Oversight",
}

# Longest domain name, so the stats/per-domain columns stay aligned.
NAME_W = max(len(n) for n in DOMAIN_NAMES.values())

WIDTH = 78


class Palette:
    """ANSI colour wrapper that degrades to plain text when disabled."""

    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, s):
        return "\033[%sm%s\033[0m" % (code, s) if self.enabled else s

    def green(self, s): return self._wrap("32", s)
    def red(self, s): return self._wrap("31", s)
    def yellow(self, s): return self._wrap("33", s)
    def cyan(self, s): return self._wrap("36", s)
    def bold(self, s): return self._wrap("1", s)
    def dim(self, s): return self._wrap("2", s)


def color_enabled():
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


# ---------------------------------------------------------------- data I/O

def load_bank(path):
    if not os.path.exists(path):
        sys.exit("quiz.py: question bank file not found: %s" % path)
    try:
        with open(path, encoding="utf-8") as f:
            bank = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        sys.exit("quiz.py: question bank is not valid JSON: %s" % path)
    if not isinstance(bank, list) or not bank:
        sys.exit("quiz.py: question bank is empty or malformed: %s" % path)
    return bank


def empty_stats():
    return {
        "lifetime": {"correct": 0, "total": 0},
        "per_domain": {},        # "1".."5" -> {"correct": n, "total": n}
        "missed_ids": [],        # question ids answered wrong (deduped)
        "best_streak": 0,
        "current_streak": 0,
        "acronyms": {"correct": 0, "total": 0, "missed_ids": []},
        "crypto": {"correct": 0, "total": 0, "missed_ids": []},
    }


def _coerce_int(value):
    """Return `value` as an int, or 0 when it cannot be converted.

    Defensive coercion for hand-edited stats.json files: a malformed value
    (e.g. a non-numeric string) becomes 0 instead of raising an exception.
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _load_drill_section(stats, data, key):
    """Merge one optional drill bucket ('acronyms'/'crypto') from `data` into
    `stats`. Absent or malformed values keep the empty defaults, so a
    stats.json that predates the drill sections loads cleanly without losing
    any of its existing lifetime / per-domain / streak data."""
    section = data.get(key)
    if not isinstance(section, dict):
        return
    stats[key]["correct"] = _coerce_int(section.get("correct", 0))
    stats[key]["total"] = _coerce_int(section.get("total", 0))
    mids = section.get("missed_ids")
    if isinstance(mids, list):
        stats[key]["missed_ids"] = [m for m in mids if isinstance(m, str)]


def load_stats(path):
    stats = empty_stats()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return stats
    if not isinstance(data, dict):
        return stats
    lt = data.get("lifetime")
    if isinstance(lt, dict):
        stats["lifetime"]["correct"] = _coerce_int(lt.get("correct", 0))
        stats["lifetime"]["total"] = _coerce_int(lt.get("total", 0))
    pd = data.get("per_domain")
    if isinstance(pd, dict):
        for k in ("1", "2", "3", "4", "5"):
            v = pd.get(k)
            if isinstance(v, dict):
                stats["per_domain"][k] = {
                    "correct": _coerce_int(v.get("correct", 0)),
                    "total": _coerce_int(v.get("total", 0)),
                }
    mids = data.get("missed_ids")
    if isinstance(mids, list):
        stats["missed_ids"] = [m for m in mids if isinstance(m, str)]
    stats["best_streak"] = _coerce_int(data.get("best_streak", 0))
    stats["current_streak"] = _coerce_int(data.get("current_streak", 0))
    # Drill sections are optional: older stats.json files have no "acronyms"
    # or "crypto" key, so keep the defaults when absent (never a crash, never
    # a reset). A legacy "ports" key is simply ignored — the port drill is gone.
    _load_drill_section(stats, data, "acronyms")
    _load_drill_section(stats, data, "crypto")
    return stats


def save_stats(stats, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # never let a stats write crash the game


def record_answer(stats, q, correct):
    lt = stats["lifetime"]
    lt["total"] += 1
    if correct:
        lt["correct"] += 1
        stats["current_streak"] += 1
        stats["best_streak"] = max(stats["best_streak"], stats["current_streak"])
        if q["id"] in stats["missed_ids"]:
            stats["missed_ids"].remove(q["id"])
    else:
        stats["current_streak"] = 0
        if q["id"] not in stats["missed_ids"]:
            stats["missed_ids"].append(q["id"])
    d = str(q["domain"])
    pd = stats["per_domain"].setdefault(d, {"correct": 0, "total": 0})
    pd["total"] += 1
    if correct:
        pd["correct"] += 1


# ---------------------------------------------------------------- output

def hr(pal, ch="-"):
    print(pal.dim(ch * WIDTH))


def paragraph(text, indent=""):
    for line in textwrap.wrap(text, WIDTH - len(indent)) or [""]:
        print(indent + line)


def print_option(key, text):
    prefix = "%s) " % key
    avail = WIDTH - len(prefix)
    lines = textwrap.wrap(text, avail) or [""]
    print(prefix + lines[0])
    for extra in lines[1:]:
        print("   " + extra)


def show_banner(pal):
    print()
    print(pal.cyan("  Security+ (SY0-701) Terminal Quiz"))
    print(pal.dim("  " + "-" * 35))
    print("  Study the vault. Answer fast. Keep the streak.")
    print()


def show_menu(pal):
    print("  1) Quick 10        - 10 random questions, all domains")
    print("  2) Domain drill    - pick domains (1-5 or all) + length")
    print("  3) Acronym drill   - acronyms, both directions")
    print("  4) Crypto drill    - crypto/algorithm values, both directions")
    print("  5) Review missed   - replay questions you got wrong")
    print("  6) Review acronyms - replay acronym items you got wrong")
    print("  7) Review crypto   - replay crypto items you got wrong")
    print("  8) Stats           - accuracy, streaks, hardest domain")
    print("  9) Quit")
    print()


# ---------------------------------------------------------------- questions

def make_choices(q, rng):
    """Return (keys, shown, correct_key).

    keys       list of answer keys in display order
    shown      list of (key, option_text) in display order
    correct_key the key that maps to the correct option
    """
    if q["type"] == "tf":
        shown = [("t", "True"), ("f", "False")]
        correct_key = "t" if q["answer"] == 0 else "f"
        return ["t", "f"], shown, correct_key

    opts = list(q["options"])
    order = list(range(len(opts)))
    rng.shuffle(order)
    keys = "abcd"
    shown = []
    correct_key = None
    for k, oi in zip(keys, order):
        shown.append((k, opts[oi]))
        if oi == q["answer"]:
            correct_key = k
    return list(keys), shown, correct_key


def parse_key(raw, keys, qtype):
    a = raw.strip().lower()
    if a in ("q", "quit"):
        return "quit"
    if a in keys:
        return a
    if qtype == "mc":
        if a in ("1", "2", "3", "4"):
            idx = int(a) - 1
            if idx < len(keys):
                return keys[idx]
    else:
        if a in ("t", "true"):
            return "t"
        if a in ("f", "false"):
            return "f"
    return None


def present_question(i, total, q, shown, pal):
    print()
    hr(pal)
    tag = pal.dim("Q%d/%d  [Domain %d - %s]  %s"
                  % (i, total, q["domain"], DOMAIN_NAMES[q["domain"]],
                     q["difficulty"]))
    print(tag)
    print()
    paragraph(q["question"])
    print()
    for key, text in shown:
        print_option(key, text)
    print()


def print_source(src, pal):
    label = "  source: "
    note = src["note"]
    section = src["section"]
    indent = " " * len(label)
    full = "%s \u203a %s" % (note, section)
    if len(label) + len(full) <= WIDTH:
        print(pal.dim(label + full))
    else:
        print(pal.dim("%s%s \u203a" % (label, note)))
        for line in textwrap.wrap(section, WIDTH - len(indent)) or [""]:
            print(pal.dim(indent + line))


def present_feedback(q, shown, correct_key, chosen_correct, pal):
    correct_text = next(t for k, t in shown if k == correct_key)
    if chosen_correct:
        print(pal.green("  CORRECT"))
    else:
        prefix = "  INCORRECT  ->  "
        avail = WIDTH - len(prefix)
        lines = textwrap.wrap(correct_text, avail) or [""]
        print(pal.red(prefix + lines[0]))
        for extra in lines[1:]:
            print(pal.red(" " * len(prefix) + extra))
    paragraph(q["explanation"], indent="  ")
    print_source(q["source"], pal)


def run_round(questions, pal, rng, answer_fn, stats=None, stats_path=None):
    """Run one round. `answer_fn(i, prompt, correct_key, keys)` returns a raw
    answer string (it owns printing the prompt). Returns None (results are
    handled internally); records stats when `stats` is provided."""
    order = list(questions)
    rng.shuffle(order)

    score = 0
    results = []  # (question, correct_bool)
    for i, q in enumerate(order, 1):
        keys, shown, correct_key = make_choices(q, rng)
        present_question(i, len(order), q, shown, pal)

        while True:
            raw = answer_fn(i, "> ", correct_key, keys)
            key = parse_key(raw, keys, q["type"])
            if key == "quit":
                print(pal.yellow("  Quit to menu."))
                _summarize(results, pal)
                return
            if key is not None:
                break
            print(pal.yellow("  Enter %s (or q to quit)."
                             % _keys_help(q["type"])))

        chosen_correct = (key == correct_key)
        if chosen_correct:
            score += 1
        results.append((q, chosen_correct))

        if stats is not None:
            record_answer(stats, q, chosen_correct)
            save_stats(stats, stats_path)

        present_feedback(q, shown, correct_key, chosen_correct, pal)

    _summarize(results, pal)


def _keys_help(qtype):
    return "a-d or 1-4" if qtype == "mc" else "t/f"


def _summarize(results, pal):
    total = len(results)
    if total == 0:
        return
    score = sum(1 for _, ok in results if ok)
    pct = 100.0 * score / total
    print()
    hr(pal, "=")
    print(pal.bold("  Round summary"))
    print("  Score: %d/%d  (%.0f%%)" % (score, total, pct))

    agg = {}
    for q, ok in results:
        d = q["domain"]
        a = agg.setdefault(d, [0, 0])
        a[1] += 1
        if ok:
            a[0] += 1
    print("  Per-domain:")
    for d in sorted(agg):
        c, t = agg[d]
        print("    Domain %d (%s): %d/%d" % (d, DOMAIN_NAMES[d], c, t))

    missed = [q for q, ok in results if not ok]
    if missed:
        print("  Missed:")
        for q in missed:
            prefix = "    - "
            avail = WIDTH - len(prefix)
            lines = textwrap.wrap(q["question"], avail) or [""]
            print(prefix + lines[0])
            for extra in lines[1:]:
                print(" " * len(prefix) + extra)
    else:
        print(pal.green("  Clean round - nothing missed."))
    hr(pal, "=")
    print()


# ---------------------------------------------------------------- selection

def select_quick(bank, rng):
    return rng.sample(bank, min(10, len(bank)))


def select_drill(bank, rng, domains, length):
    pool = [q for q in bank if q["domain"] in domains]
    if length is None:  # all
        return pool
    return rng.sample(pool, min(length, len(pool)))


def select_review(bank, stats):
    want = set(stats["missed_ids"])
    return [q for q in bank if q["id"] in want]


def select_review_drill(mod, table, stats):
    """Return drill items (mixed, both directions) whose id is in the drill
    bucket's missed_ids. `mod` is the acronyms or crypto module."""
    want = set(stats[mod.STATS_KEY]["missed_ids"])
    pool = mod.build_items(table, mod.DIR_MIXED)
    return [it for it in pool if it["id"] in want]


# ---------------------------------------------------------------- stats view

def show_stats(stats, pal):
    lt = stats["lifetime"]
    tot, corr = lt["total"], lt["correct"]
    acc = (100.0 * corr / tot) if tot else 0.0
    print()
    hr(pal, "=")
    print(pal.bold("  Statistics"))
    print("  Lifetime accuracy : %d/%d  (%.1f%%)" % (corr, tot, acc))
    print("  Current streak    : %d" % stats["current_streak"])
    print("  Best streak       : %d" % stats["best_streak"])
    print("  Per-domain:")
    hardest, hard_acc = None, None
    for d in ("1", "2", "3", "4", "5"):
        pd = stats["per_domain"].get(d)
        if pd and pd["total"] > 0:
            a = 100.0 * pd["correct"] / pd["total"]
            print("    %s  %-*s %d/%d  (%.1f%%)"
                  % (d, NAME_W, DOMAIN_NAMES[int(d)], pd["correct"], pd["total"], a))
            if hard_acc is None or a < hard_acc:
                hard_acc, hardest = a, d
    if hardest is not None:
        print("  Hardest domain    : %s (%s)"
              % (hardest, DOMAIN_NAMES[int(hardest)]))
    else:
        print("  Hardest domain    : none (no attempts yet)")
    print("  Missed questions  : %d" % len(stats["missed_ids"]))
    a = stats["acronyms"]
    a_acc = (100.0 * a["correct"] / a["total"]) if a["total"] else 0.0
    print("  Acronym drill     : %d/%d  (%.1f%%)   [%d missed acronyms]"
          % (a["correct"], a["total"], a_acc, len(a["missed_ids"])))
    c = stats["crypto"]
    c_acc = (100.0 * c["correct"] / c["total"]) if c["total"] else 0.0
    print("  Crypto drill      : %d/%d  (%.1f%%)   [%d missed crypto]"
          % (c["correct"], c["total"], c_acc, len(c["missed_ids"])))
    hr(pal, "=")
    print()


# ---------------------------------------------------------------- selftest

def run_selftest(bank, pal, rng):
    show_banner(pal)
    print(pal.cyan("  SELF-TEST  (scripted round, fixed seed, no stdin)"))
    questions = rng.sample(bank, 10)

    def scripted(i, prompt, correct_key, keys):
        # answer correctly on odd i, incorrectly on even i (exercise both paths)
        if i % 2 == 0:
            chosen = next(k for k in keys if k != correct_key)
        else:
            chosen = correct_key
        print(prompt + chosen, flush=True)
        return chosen

    run_round(questions, pal, rng, scripted, stats=None, stats_path=None)
    print(pal.green("SELF-TEST COMPLETE"))
    return 0


def run_review_selftest(bank, pal, rng, stats=None, stats_path=None):
    show_banner(pal)
    print(pal.cyan("  REVIEW SELF-TEST  "
                   "(scripted round, fixed seed, no stdin)"))
    if stats is None:
        stats = empty_stats()
    if not stats["missed_ids"]:
        stats["missed_ids"] = [q["id"] for q in bank[:3]]
        if stats_path is not None:
            save_stats(stats, stats_path)
    qs = select_review(bank, stats)
    if not qs:
        print(pal.red("  REVIEW SELF-TEST FAIL: no review items selected"))
        return 1
    print("  Reviewing missed question ids: %s"
          % ", ".join(sorted(stats["missed_ids"])))

    def scripted(i, prompt, correct_key, keys):
        chosen = correct_key
        print(prompt + chosen, flush=True)
        return chosen

    run_round(qs, pal, rng, scripted, stats, stats_path)

    remaining = set(stats["missed_ids"]) & {q["id"] for q in qs}
    if remaining:
        print(pal.red("  REVIEW SELF-TEST FAIL: still missed: %s"
                      % ", ".join(sorted(remaining))))
        return 1
    print(pal.green("REVIEW SELF-TEST COMPLETE"))
    return 0


# ---------------------------------------------------------------- drills

def present_drill_question(mod, item, i, total, pal):
    print()
    hr(pal)
    tag = pal.dim("%s%d/%d  [%s]  %s"
                  % (mod.Q_PREFIX, i, total, mod.TITLE,
                     mod.direction_label(item["direction"])))
    print(tag)
    print()
    paragraph(item["prompt"])
    print()


def present_drill_feedback(mod, item, correct_answer, chosen_correct, pal):
    if chosen_correct:
        print(pal.green("  CORRECT"))
    else:
        prefix = "  INCORRECT  ->  "
        avail = WIDTH - len(prefix)
        lines = textwrap.wrap(correct_answer, avail) or [""]
        print(pal.red(prefix + lines[0]))
        for extra in lines[1:]:
            print(pal.red(" " * len(prefix) + extra))
    paragraph(item["explanation"], indent="  ")
    print_source(item["source"], pal)


def _summarize_drill(mod, results, pal):
    total = len(results)
    if total == 0:
        return
    score = sum(1 for _, ok, _ in results if ok)
    pct = 100.0 * score / total
    print()
    hr(pal, "=")
    print(pal.bold("  Round summary"))
    print("  Score: %d/%d  (%.0f%%)" % (score, total, pct))
    missed = [(it, ca) for it, ok, ca in results if not ok]
    if missed:
        print("  Missed:")
        for it, ca in missed:
            print("    - %s  ->  %s" % (it["prompt"], ca))
    else:
        print(pal.green("  Clean round - nothing missed."))
    hr(pal, "=")
    print()


def run_drill_round(mod, items, pal, rng, answer_fn, stats=None, stats_path=None):
    """Run one free-text drill round for `mod` (acronyms or crypto).
    `answer_fn(i, prompt, item)` returns a raw answer string. Results are
    handled internally; records drill stats when `stats` is provided."""
    order = list(items)
    rng.shuffle(order)
    results = []  # (item, correct, correct_answer)
    for i, item in enumerate(order, 1):
        present_drill_question(mod, item, i, len(order), pal)
        while True:
            raw = answer_fn(i, "> ", item)
            raw = "" if raw is None else raw.strip()
            if raw.lower() in ("q", "quit"):
                print(pal.yellow("  Quit to menu."))
                _summarize_drill(mod, results, pal)
                return
            if raw:
                break
            print(pal.yellow("  Type your answer (or q to quit)."))

        correct, correct_answer, _, _ = mod.grade(item, raw)
        results.append((item, correct, correct_answer))

        if stats is not None:
            mod.record_answer(stats, item["id"], correct)
            save_stats(stats, stats_path)

        present_drill_feedback(mod, item, correct_answer, correct, pal)

    _summarize_drill(mod, results, pal)


def run_drill_selftest(mod, pal, rng, stats=None, stats_path=None):
    show_banner(pal)
    print(pal.cyan("  %s SELF-TEST  "
                   "(scripted round, fixed seed, no stdin)" % mod.TITLE))
    table = mod.load_table()
    pool = mod.build_items(table, mod.DIR_MIXED)
    items = mod.select_items(pool, rng, 10)

    def scripted(i, prompt, item):
        # correct on odd i, incorrect on even i (exercise both paths)
        chosen = item["answer"] if i % 2 == 1 else "zzz-not-a-real-answer"
        print(prompt + chosen, flush=True)
        return chosen

    run_drill_round(mod, items, pal, rng, scripted, stats, stats_path)
    print(pal.green("%s SELF-TEST COMPLETE" % mod.TITLE))
    return 0


def _default_drill_missed_ids(mod):
    """Seed missed_ids for a review selftest from the first few table entries
    (ids are stable regardless of the real table landing later)."""
    table = mod.load_table()
    return [e["id"] for e in table[:3]]


def run_drill_review_selftest(mod, pal, rng, stats=None, stats_path=None):
    show_banner(pal)
    print(pal.cyan("  %s REVIEW SELF-TEST  "
                   "(scripted round, fixed seed, no stdin)" % mod.TITLE))
    if stats is None:
        stats = empty_stats()
    bucket = stats[mod.STATS_KEY]
    if not bucket["missed_ids"]:
        bucket["missed_ids"] = _default_drill_missed_ids(mod)
        if stats_path is not None:
            save_stats(stats, stats_path)
    table = mod.load_table()
    items = select_review_drill(mod, table, stats)
    if not items:
        print(pal.red("  %s REVIEW SELF-TEST FAIL: no review items selected"
                      % mod.TITLE))
        return 1
    print("  Reviewing missed %s ids: %s"
          % (mod.STATS_KEY, ", ".join(sorted(bucket["missed_ids"]))))

    def scripted(i, prompt, item):
        chosen = item["answer"]
        print(prompt + chosen, flush=True)
        return chosen

    run_drill_round(mod, items, pal, rng, scripted, stats, stats_path)

    remaining = set(bucket["missed_ids"]) & {it["id"] for it in items}
    if remaining:
        print(pal.red("  %s REVIEW SELF-TEST FAIL: still missed: %s"
                      % (mod.TITLE, ", ".join(sorted(remaining)))))
        return 1
    print(pal.green("%s REVIEW SELF-TEST COMPLETE" % mod.TITLE))
    return 0


def _direction_help(mod):
    return ", ".join("%d (%s)" % (n, label)
                     for n, (label, _key) in enumerate(mod.DIRECTION_CHOICES, 1))


def pick_direction(mod, pal):
    print("  Direction:")
    for n, (label, _key) in enumerate(mod.DIRECTION_CHOICES, 1):
        print("    %d) %s" % (n, label))
    raw = input("  > ").strip().lower()
    if raw in ("q", "quit"):
        return "quit"
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= len(mod.DIRECTION_CHOICES):
            return mod.DIRECTION_CHOICES[n - 1][1]
    for label, key in mod.DIRECTION_CHOICES:
        first = label.split(" ")[0]
        if raw == key or raw == first:
            return key
    return None


def interactive_drill_answer(i, prompt, item):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "q"


# ---------------------------------------------------------------- interactive

def interactive_answer(i, prompt, correct_key, keys):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "q"


def pick_domains(pal):
    raw = input("  Domains (1-5, comma/space, or 'all'): ").strip().lower()
    if raw in ("q", "quit"):
        return "quit"
    if raw == "all":
        return [1, 2, 3, 4, 5]
    out, seen = [], set()
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= 5:
            n = int(tok)
            if n not in seen:
                seen.add(n)
                out.append(n)
    return out if out else None


def pick_length(pal, available):
    raw = input("  Length (10, 20, or all): ").strip().lower()
    if raw in ("q", "quit"):
        return "quit"
    if raw == "all":
        return None  # None means "all"
    if raw in ("10", "20"):
        return min(int(raw), available)
    return "invalid"


def _drill_menu_entry(mod, pal, rng, stats, args):
    table, err = mod.load_table_or_error()
    if err:
        print("  %s" % err)
        print()
        return
    direction = pick_direction(mod, pal)
    if direction == "quit":
        return
    if direction is None:
        print("  Choose %s." % _direction_help(mod))
        return
    pool = mod.build_items(table, direction)
    length = pick_length(pal, len(pool))
    if length == "quit":
        return
    if length == "invalid":
        print("  Enter 10, 20, or all.")
        return
    items = mod.select_items(pool, rng, length)
    run_drill_round(mod, items, pal, rng, interactive_drill_answer,
                    stats, args.stats)


def _drill_review_menu_entry(mod, pal, rng, stats, args, label):
    table, err = mod.load_table_or_error()
    if err:
        print("  %s" % err)
        print()
        return
    items = select_review_drill(mod, table, stats)
    if not items:
        print("  Nothing to review - you have no missed %s yet." % label)
        print()
        return
    run_drill_round(mod, items, pal, rng, interactive_drill_answer,
                    stats, args.stats)


def run_menu(bank, stats, pal, rng, args):
    while True:
        show_banner(pal)
        show_menu(pal)
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "quit"

        if choice in ("1", "quick"):
            qs = select_quick(bank, rng)
            run_round(qs, pal, rng, interactive_answer, stats, args.stats)

        elif choice in ("2", "drill"):
            domains = pick_domains(pal)
            if domains == "quit":
                continue
            if domains is None:
                print("  No valid domains entered.")
                continue
            length = pick_length(pal, len(bank))
            if length == "quit":
                continue
            if length == "invalid":
                print("  Enter 10, 20, or all.")
                continue
            qs = select_drill(bank, rng, domains, length)
            run_round(qs, pal, rng, interactive_answer, stats, args.stats)

        elif choice in ("3", "acronym", "acronyms"):
            _drill_menu_entry(acronyms, pal, rng, stats, args)

        elif choice in ("4", "crypto", "cryptodrill"):
            _drill_menu_entry(crypto, pal, rng, stats, args)

        elif choice in ("5", "review"):
            qs = select_review(bank, stats)
            if not qs:
                print("  Nothing to review - you have no missed questions yet.")
                print()
                continue
            run_round(qs, pal, rng, interactive_answer, stats, args.stats)

        elif choice in ("6", "reviewacronyms", "review-acronyms",
                        "review_acronyms"):
            _drill_review_menu_entry(acronyms, pal, rng, stats, args,
                                     "acronyms")

        elif choice in ("7", "reviewcrypto", "review-crypto", "review_crypto"):
            _drill_review_menu_entry(crypto, pal, rng, stats, args, "crypto")

        elif choice in ("8", "stats"):
            show_stats(stats, pal)

        elif choice in ("9", "q", "quit", "exit"):
            print("  Good luck on the exam.")
            break

        else:
            print("  Unknown choice. Enter 1-9.")


def _selftest_stats(args, needs_write=False):
    """Resolve (stats, stats_path) for a selftest. An explicit --stats PATH is
    honoured; otherwise `needs_write` selftests use a throwaway temp file so a
    selftest never mutates the real stats.json."""
    if args.stats is not None:
        return load_stats(args.stats), args.stats
    if needs_write:
        fd, path = tempfile.mkstemp(prefix="secplus-selftest-", suffix=".json")
        os.close(fd)
        return empty_stats(), path
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Security+ (SY0-701) terminal quiz")
    ap.add_argument("--bank", default=DEFAULT_BANK)
    ap.add_argument("--stats", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--acronyms", action="store_true",
                    help="with --selftest: run a scripted acronym-drill round")
    ap.add_argument("--crypto", action="store_true",
                    help="with --selftest: run a scripted crypto-drill round")
    ap.add_argument("--review", action="store_true",
                    help="with --selftest: run a scripted review-missed-questions round")
    ap.add_argument("--review-acronyms", action="store_true",
                    help="with --selftest: run a scripted review-missed-acronyms round")
    ap.add_argument("--review-crypto", action="store_true",
                    help="with --selftest: run a scripted review-missed-crypto round")
    args = ap.parse_args(argv)

    pal = Palette(color_enabled())
    bank = load_bank(args.bank)
    stats_path = args.stats or DEFAULT_STATS

    if args.selftest:
        rng = random.Random(args.seed if args.seed is not None else 42)
        if args.acronyms:
            stats, sp = _selftest_stats(args)
            return run_drill_selftest(acronyms, pal, rng, stats, sp)
        if args.crypto:
            stats, sp = _selftest_stats(args)
            return run_drill_selftest(crypto, pal, rng, stats, sp)
        if args.review_acronyms:
            stats, sp = _selftest_stats(args, needs_write=True)
            return run_drill_review_selftest(acronyms, pal, rng, stats, sp)
        if args.review_crypto:
            stats, sp = _selftest_stats(args, needs_write=True)
            return run_drill_review_selftest(crypto, pal, rng, stats, sp)
        if args.review:
            stats, sp = _selftest_stats(args, needs_write=True)
            return run_review_selftest(bank, pal, rng, stats, sp)
        return run_selftest(bank, pal, rng)

    rng = random.Random(args.seed)
    stats = load_stats(stats_path)
    run_menu(bank, stats, pal, rng, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
