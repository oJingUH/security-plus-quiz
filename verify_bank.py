#!/usr/bin/env python3
"""
verify_bank.py — integrity checker for the Security+ (SY0-701) quiz question
bank and the two drill tables (acronyms and crypto).

Checks that questions.json is well-formed, correctly cited, and that every
fact (marked with a "verify" list) actually appears in the cited section of
the vault notes. Also validates acronyms.json and crypto.json: required
fields, unique ids/displays, citations resolve (exact heading match, em-dash
sensitive), every "verify" string appears in the cited section, and both
drill directions are derivable from every entry.

Grounding is CELL/TOKEN BOUNDARY based, never raw substring. A substring
compare in an earlier revision accepted "LDAPS" as satisfying "LDAP" — a
wrong-answer pass that this verifier makes impossible: a value must appear as
a whole token (or a contiguous run of tokens), so "LDAP" can never match the
"LDAP" prefix inside "LDAPS".

Prints a PASS/FAIL summary and exits non-zero on any failure.

Usage:
    python3 verify_bank.py [--bank questions.json] [--acronyms acronyms.json]
                           [--crypto crypto.json] [--vault "/path/to/Security+"]
"""

import argparse
import json
import os
import re
import sys

# Exam-weight targets. SY0-701 domain weights are 12/22/18/28/20; scaled by
# 1.2 and rounded that yields 14/26/22/34/24, which is exactly how network-quiz
# derived its own targets (N10-009 weights 23/20/19/14/24 x 1.2 -> {1:28, 2:24,
# 3:23, 4:17, 5:28}, TOTAL_MIN 120).
DOMAIN_MIN = {1: 14, 2: 26, 3: 22, 4: 34, 5: 24}
TOTAL_MIN = 120
VALID_DIFFICULTY = {"easy", "medium", "hard"}
REQUIRED_FIELDS = ["id", "domain", "type", "question", "options", "answer",
                   "answer_text", "explanation", "difficulty", "source"]
REQUIRED_SOURCE_FIELDS = ["note", "section"]

# Drill-table schemas (each validated separately).
ACRONYM_REQUIRED = ["id", "display", "acronym", "expansion", "source", "verify"]
CRYPTO_REQUIRED = ["id", "display", "algorithm", "property", "value",
                   "source", "verify"]
# The fields whose non-emptiness makes BOTH directions derivable.
ACRONYM_CONTENT = ("acronym", "expansion")
CRYPTO_CONTENT = ("algorithm", "property", "value")
# The ANSWER-bearing fields: the values that appear as a drill item's answer,
# which must each be covered by the entry's verify list so the gate can tell a
# correct drill table from one whose content was swapped/changed (steward C/D/E).
ACRONYM_ANSWER_FIELDS = ("acronym", "expansion")
CRYPTO_ANSWER_FIELDS = ("algorithm", "value")


def parse_answer(answer, num_options, qtype):
    """Return the 0-based index the answer refers to, or None if invalid."""
    if isinstance(answer, int) and not isinstance(answer, bool):
        if 0 <= answer < num_options:
            return answer
        return None
    if isinstance(answer, str):
        a = answer.strip().lower()
        if qtype == "tf" and a in ("t", "true", "f", "false"):
            return 0 if a in ("t", "true") else 1
        if qtype == "mc":
            if a in ("a", "b", "c", "d"):
                return ord(a) - ord("a")
            if a in ("1", "2", "3", "4"):
                return int(a) - 1
        return None
    return None


def section_body(lines, section):
    """Return the body text of a named section (list of file lines -> str).

    The heading is the first line whose '#'-stripped, whitespace-stripped
    content equals `section`. The body runs until the next heading of any
    level. Returns None if the heading does not exist. Lines are joined with a
    newline so token boundaries at line breaks are preserved for grounding.
    """
    target = section.strip()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading == target:
                start = i
                break
    if start is None:
        return None
    body = []
    for line in lines[start + 1:]:
        if line.strip().startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


# A "token" is a maximal run of characters that legitimately appear INSIDE a
# value or identifier: letters, digits, and the joining symbols '/', '+', '&'
# and '-'. Everything else (whitespace, ',', '.', ':', '|', quotes, …) is a
# token boundary. This keeps "AES-256", "256-bit", "SHA-1", "TACACS+" and
# "20/21" as single tokens, while "LDAP" and "LDAPS" are distinct tokens.
_TOKEN_RE = re.compile(r"[A-Za-z0-9/+&\-]+")


def _tokenize(text):
    return _TOKEN_RE.findall(text)


def grounded(body_text, value):
    """True if `value` appears in `body_text` as a whole token, or a contiguous
    run of whole tokens (cell/token boundary) — never as a raw substring.

    A naive substring compare would accept "LDAPS" as satisfying "LDAP"; here
    "LDAP" must appear as a standalone token, so that wrong-answer pass is
    impossible. Multi-word values (e.g. "Mandatory Access Control") must appear
    as that exact contiguous token sequence.
    """
    needle = _tokenize(value)
    if not needle:
        return False
    hay = _tokenize(body_text)
    n = len(needle)
    for i in range(len(hay) - n + 1):
        if hay[i:i + n] == needle:
            return True
    return False


def contains_ci(text, phrase):
    """Case-insensitive, token-boundary 'phrase appears in text' check.

    Mirrors grounded() but lowercases both sides so the casing of an option
    ("Confidentiality") and the casing of the vault ("confidentiality") agree.
    Still token-boundary based, so "LDAP" never matches "LDAPS"."""
    needle = [t.lower() for t in _tokenize(phrase)]
    if not needle:
        return False
    hay = [t.lower() for t in _tokenize(text)]
    n = len(needle)
    for i in range(len(hay) - n + 1):
        if hay[i:i + n] == needle:
            return True
    return False


# ---------------------------------------------------------------- vault cache

def _make_note_loader(vault):
    cache = {}

    def get_note_lines(rel_note):
        if rel_note in cache:
            return cache[rel_note]
        path = os.path.join(vault, rel_note.replace("/", os.sep))
        if not os.path.exists(path):
            cache[rel_note] = None
            return None
        with open(path, encoding="utf-8") as f:
            cache[rel_note] = f.read().splitlines()
        return cache[rel_note]

    return get_note_lines


# ---------------------------------------------------------------- question bank

def verify_questions(args):
    """Validate questions.json and return 0 (pass) or 1 (fail)."""
    print("=" * 66)
    print("Security+ Quiz Bank Verification")
    print("=" * 66)
    print("bank  : %s" % args.bank)
    print("vault : %s" % args.vault)

    errors = []

    if not os.path.exists(args.bank):
        print("FAIL: bank file not found: %s" % args.bank)
        return 1
    try:
        with open(args.bank, encoding="utf-8") as f:
            bank = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print("FAIL: questions.json does not parse as JSON: %s" % e)
        return 1

    if not isinstance(bank, list) or not bank:
        print("FAIL: bank must be a non-empty JSON list")
        return 1

    n = len(bank)
    ids = []
    domain_counts = {}
    type_counts = {}
    verify_checks = 0

    get_note_lines = _make_note_loader(args.vault)

    for idx, q in enumerate(bank):
        loc = "question #%d (id=%r)" % (idx + 1, q.get("id", "?"))

        if not isinstance(q, dict):
            errors.append("%s: not a JSON object" % loc)
            continue
        for field in REQUIRED_FIELDS:
            if field not in q:
                errors.append("%s: missing required field %r" % (loc, field))
        src = q.get("source")
        if not isinstance(src, dict):
            errors.append("%s: 'source' must be an object" % loc)
        else:
            for field in REQUIRED_SOURCE_FIELDS:
                if field not in src:
                    errors.append("%s: source missing field %r" % (loc, field))

        qid = q.get("id")
        if not isinstance(qid, str) or not qid.strip():
            errors.append("%s: 'id' must be a non-empty string" % loc)
        else:
            if qid in ids:
                errors.append("%s: duplicate question id %r" % (loc, qid))
            ids.append(qid)

        domain = q.get("domain")
        if isinstance(domain, bool) or not isinstance(domain, int) or domain not in (1, 2, 3, 4, 5):
            errors.append("%s: 'domain' must be an integer 1..5" % loc)
        else:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

        qtype = q.get("type")
        if qtype not in ("mc", "tf"):
            errors.append("%s: 'type' must be 'mc' or 'tf'" % loc)
        else:
            type_counts[qtype] = type_counts.get(qtype, 0) + 1

        if q.get("difficulty") not in VALID_DIFFICULTY:
            errors.append("%s: 'difficulty' must be easy|medium|hard" % loc)

        options = q.get("options")
        if not isinstance(options, list) or len(options) == 0:
            errors.append("%s: 'options' must be a non-empty list" % loc)
        elif qtype == "mc" and len(options) != 4:
            errors.append("%s: multiple-choice must have exactly 4 options (got %d)"
                          % (loc, len(options)))
        elif qtype == "tf" and (len(options) != 2 or
                                [str(o).strip().lower() for o in options] != ["true", "false"]):
            errors.append("%s: true/false options must be ['True','False']" % loc)

        # answer index/letter in range; exactly one correct option (a single
        # in-range answer index plus unique options makes the correct option
        # unambiguous).
        answer = q.get("answer")
        num_options = len(options) if isinstance(options, list) else 0
        ans_idx = None
        if num_options:
            ans_idx = parse_answer(answer, num_options, qtype)
            if ans_idx is None:
                errors.append("%s: answer %r out of range for %s (options=%d)"
                              % (loc, answer, qtype, num_options))
            elif isinstance(options, list):
                norm = [str(o).strip() for o in options]
                if len(set(norm)) != len(norm):
                    errors.append("%s: options contain duplicates" % loc)

        # ANSWER MIRROR: the correct option's text must be stated explicitly
        # (`answer_text`), and the gate requires options[answer] == answer_text.
        # A bare in-range index flip (test A) or a question text rewritten to
        # contradict the answer (test B) now fails.
        answer_text = q.get("answer_text")
        if not isinstance(answer_text, str) or not answer_text.strip():
            errors.append("%s: 'answer_text' must be a non-empty string" % loc)
        elif ans_idx is not None and isinstance(options, list) \
                and 0 <= ans_idx < len(options):
            if str(options[ans_idx]).strip() != answer_text.strip():
                errors.append("%s: answer mirror mismatch — options[answer]=%r "
                              "but answer_text=%r"
                              % (loc, str(options[ans_idx]).strip(),
                                 answer_text.strip()))

        # citation: note exists + section heading exists (exact match)
        if isinstance(src, dict) and "note" in src and "section" in src:
            rel_note = src["note"]
            section = src["section"]
            if not isinstance(rel_note, str) or not isinstance(section, str):
                errors.append("%s: source note/section must be strings" % loc)
                continue
            lines = get_note_lines(rel_note)
            if lines is None:
                errors.append("%s: cited note file not found: %r" % (loc, rel_note))
            else:
                body = section_body(lines, section)
                if body is None:
                    errors.append("%s: section heading %r not found in %r"
                                  % (loc, section, rel_note))
                else:
                    verify = q.get("verify")
                    if verify is not None:
                        if not isinstance(verify, list):
                            errors.append("%s: 'verify' must be a list of strings" % loc)
                        else:
                            for token in verify:
                                verify_checks += 1
                                if not isinstance(token, str) or not grounded(body, token):
                                    errors.append(
                                        "%s: expected value %r not found in %r > %r"
                                        % (loc, token, rel_note, section))

                    # ANSWER-BEARING GROUNDING: a multiple-choice question must
                    # carry a verify token drawn from the CORRECT option's own
                    # text that (i) is present in the cited section and (ii) is
                    # not present in any other option — so the verified string
                    # is actually discriminating and the gate can tell a correct
                    # bank from a scrambled one.
                    if qtype == "mc":
                        correct_opt = None
                        other_opts = []
                        if isinstance(options, list) and ans_idx is not None \
                                and 0 <= ans_idx < len(options):
                            correct_opt = str(options[ans_idx]).strip()
                            other_opts = [str(o).strip() for j, o
                                          in enumerate(options) if j != ans_idx]
                        toks = verify if isinstance(verify, list) else []
                        has_discriminating = bool(correct_opt) and any(
                            isinstance(t, str) and grounded(body, t)
                            and contains_ci(correct_opt, t)
                            and not any(contains_ci(o, t) for o in other_opts)
                            for t in toks)
                        if not has_discriminating:
                            errors.append(
                                "%s: no discriminating verify token drawn from the "
                                "correct option (answer=%r)" % (loc, correct_opt))

    for d in (1, 2, 3, 4, 5):
        have = domain_counts.get(d, 0)
        need = DOMAIN_MIN[d]
        if have < need:
            errors.append("domain %d: only %d questions (need >= %d)" % (d, have, need))
    if n < TOTAL_MIN:
        errors.append("total: only %d questions (need >= %d)" % (n, TOTAL_MIN))

    print("total : %d questions (target >= %d)" % (n, TOTAL_MIN))
    for d in (1, 2, 3, 4, 5):
        have = domain_counts.get(d, 0)
        need = DOMAIN_MIN[d]
        mark = "OK " if have >= need else "LOW"
        print("  domain %d : %3d   (target >= %d)  %s" % (d, have, need, mark))
    print("  types   : " + ", ".join("%s=%d" % (k, v) for k, v in sorted(type_counts.items())))
    print("  facts verified against vault : %d" % verify_checks)

    if errors:
        print("-" * 66)
        print("FAIL — %d problem(s) found:" % len(errors))
        for e in errors:
            print("  * %s" % e)
        print("=" * 66)
        return 1
    print("-" * 66)
    print("PASS — all %d questions valid, all citations resolve, "
          "all facts grounded." % n)
    print("=" * 66)
    return 0


# ---------------------------------------------------------------- drill tables

def find_prompt_collisions(items, label):
    """Return error strings for drill items that share an identical prompt with
    different expected answers that are not all mutually acceptable.

    Grouping is across ALL directions of one table. Two items may share a prompt
    only if every expected answer in the group appears in every item's
    accept-list — i.e. each item grades all of them as correct. This is the
    collision invariant from the multi-expansion fix: a prompt never has two
    different expected answers unless every one of them is acceptable."""
    groups = {}
    for it in items:
        # Prompts are compared CASE-SENSITIVELY: "What does SoC stand for?" and
        # "What does SOC stand for?" are distinct questions (SoC = System on
        # Chip, SOC = Security Operations Center). Only the answers/accept-lists
        # are compared case-insensitively, matching how grade() normalizes.
        key = " ".join(str(it.get("prompt", "")).split())
        groups.setdefault(key, []).append(it)
    errs = []
    for key, grp in groups.items():
        answers = set()
        for it in grp:
            ans = str(it.get("answer", "")).strip()
            if ans:
                answers.add(" ".join(ans.lower().split()))
        for it in grp:
            accept = it.get("accept") or ([it["answer"]] if it.get("answer") else [])
            accept_norm = {" ".join(str(a).lower().split()) for a in accept}
            missing = answers - accept_norm
            if missing:
                errs.append(
                    "%s: drill item id=%r (prompt %r) does not accept every "
                    "answer for this prompt — missing %s"
                    % (label, it.get("id"), it.get("prompt"),
                       ", ".join(sorted(missing))))
    return errs


def verify_drill_table(args, mod, table_path, required_fields, content_fields,
                       answer_fields, label):
    """Validate one drill table (acronyms.json or crypto.json) and return
    0 (pass) or 1 (fail).

    Checks: JSON parses; every required field present; ids unique; `display`
    values unique; the direction-bearing fields are non-empty strings; each
    citation's note file and section heading exist (exact match, em-dash
    sensitive); every "verify" string appears in the cited section (cell/token
    boundary); and BOTH directions are derivable from every entry.
    """
    print("=" * 66)
    print("Security+ %s Table Verification" % label)
    print("=" * 66)
    print("%s : %s" % (label.lower(), table_path))
    print("vault : %s" % args.vault)

    errors = []

    if not os.path.exists(table_path):
        print("FAIL: %s file not found: %s" % (label.lower(), table_path))
        return 1
    try:
        with open(table_path, encoding="utf-8") as f:
            table = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print("FAIL: %s does not parse as JSON: %s" % (label.lower(), e))
        return 1

    if not isinstance(table, list) or not table:
        print("FAIL: %s must be a non-empty JSON list" % label.lower())
        return 1

    n = len(table)
    ids = []
    displays = []
    verify_checks = 0

    get_note_lines = _make_note_loader(args.vault)

    for idx, e in enumerate(table):
        loc = "%s #%d (id=%r)" % (label, idx + 1, e.get("id", "?"))

        if not isinstance(e, dict):
            errors.append("%s: not a JSON object" % loc)
            continue
        for field in required_fields:
            if field not in e:
                errors.append("%s: missing required field %r" % (loc, field))

        src = e.get("source")
        if not isinstance(src, dict):
            errors.append("%s: 'source' must be an object" % loc)
        else:
            for field in REQUIRED_SOURCE_FIELDS:
                if field not in src:
                    errors.append("%s: source missing field %r" % (loc, field))

        eid = e.get("id")
        if not isinstance(eid, str) or not eid.strip():
            errors.append("%s: 'id' must be a non-empty string" % loc)
        elif eid in ids:
            errors.append("%s: duplicate id %r" % (loc, eid))
        else:
            ids.append(eid)

        disp = e.get("display")
        if not isinstance(disp, str) or not disp.strip():
            errors.append("%s: 'display' must be a non-empty string" % loc)
        elif disp in displays:
            errors.append("%s: duplicate display value %r" % (loc, disp))
        else:
            displays.append(disp)

        # Direction-derivable fields must be non-empty strings, otherwise one
        # of the two directions collapses (empty prompt or empty answer).
        for field in content_fields:
            v = e.get(field)
            if not isinstance(v, str) or not v.strip():
                errors.append("%s: '%s' must be a non-empty string" % (loc, field))

        if isinstance(src, dict) and "note" in src and "section" in src:
            rel_note = src["note"]
            section = src["section"]
            if not isinstance(rel_note, str) or not isinstance(section, str):
                errors.append("%s: source note/section must be strings" % loc)
                continue
            lines = get_note_lines(rel_note)
            if lines is None:
                errors.append("%s: cited note file not found: %r" % (loc, rel_note))
            else:
                body = section_body(lines, section)
                if body is None:
                    errors.append("%s: section heading %r not found in %r"
                                  % (loc, section, rel_note))
                else:
                    verify = e.get("verify")
                    if not isinstance(verify, list):
                        errors.append("%s: 'verify' must be a list of strings" % loc)
                    else:
                        for token in verify:
                            verify_checks += 1
                            if not isinstance(token, str) or not grounded(body, token):
                                errors.append(
                                    "%s: expected value %r not found in %r > %r"
                                    % (loc, token, rel_note, section))
                        # ANSWER-BEARING GROUNDING (drill table): each answer
                        # field's value must be covered by the entry's own verify
                        # list. This catches a content field (expansion/value)
                        # changed or swapped while its verify strings stayed
                        # intact (steward C/D/E).
                        joined = " ".join(str(t) for t in verify)
                        for f in answer_fields:
                            v = e.get(f)
                            if isinstance(v, str) and v.strip() \
                                    and not grounded(joined, v):
                                errors.append(
                                    "%s: answer field %r (%r) not covered by "
                                    "verify %r" % (loc, f, v, verify))

    # Both directions must be derivable: a mixed build yields exactly two items
    # per entry (one each way), covering both direction keys, with a non-empty
    # prompt and answer on every item.
    mixed_count = 0
    directions = set()
    expected_dirs = {key for _label, key in mod.DIRECTION_CHOICES
                     if key != mod.DIR_MIXED}
    try:
        items = mod.build_items(table, mod.DIR_MIXED)
        mixed_count = len(items)
        directions = set(it["direction"] for it in items)
        for it in items:
            if not it.get("prompt") or not it.get("answer"):
                errors.append("%s: drill item with empty prompt/answer: id=%r"
                              % (label, it.get("id")))
        # COLLISION INVARIANT: a prompt may only repeat with different expected
        # answers when every expected answer is in each item's accept-list.
        for err in find_prompt_collisions(items, label):
            errors.append(err)
    except Exception as e:  # noqa: BLE001 — report, don't traceback
        errors.append("%s drill build failed: %s" % (label, e))

    print("total : %d %s entries" % (n, label.lower()))
    print("  drill items (mixed) : %d" % mixed_count)
    print("  directions covered  : %s" % ", ".join(sorted(directions)))
    print("  %s facts verified against vault : %d" % (label.lower(), verify_checks))

    if mixed_count != n * 2:
        errors.append("mixed drill yields %d items (expected %d)"
                      % (mixed_count, n * 2))
    if directions != expected_dirs:
        errors.append("drill must cover both directions (got %s)"
                      % sorted(directions))

    if errors:
        print("-" * 66)
        print("FAIL — %d problem(s) found:" % len(errors))
        for e in errors:
            print("  * %s" % e)
        print("=" * 66)
        return 1
    print("-" * 66)
    print("PASS — all %d %s entries valid, citations resolve, both directions "
          "covered." % (n, label.lower()))
    print("=" * 66)
    return 0


# ---------------------------------------------------------------- entrypoint

def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default=os.path.join(here, "questions.json"))
    ap.add_argument("--acronyms", default=os.path.join(here, "acronyms.json"))
    ap.add_argument("--crypto", default=os.path.join(here, "crypto.json"))
    ap.add_argument("--vault", default=None)
    args = ap.parse_args(argv)

    # Resolve the vault: an explicit --vault wins, then the SECURITY_PLUS_VAULT
    # environment variable, then "Security+" relative to the current directory.
    vault = args.vault or os.environ.get("SECURITY_PLUS_VAULT") or "Security+"
    if not os.path.isdir(vault):
        print("vault not found: %s" % vault)
        print("pass --vault /path/to/Security+  (or set SECURITY_PLUS_VAULT)")
        return 1
    args.vault = vault

    questions_ok = (verify_questions(args) == 0)
    print()

    import acronyms as acronyms_mod
    import crypto as crypto_mod

    acronyms_ok = (verify_drill_table(args, acronyms_mod, args.acronyms,
                                      ACRONYM_REQUIRED, ACRONYM_CONTENT,
                                      ACRONYM_ANSWER_FIELDS, "Acronym") == 0)
    print()
    crypto_ok = (verify_drill_table(args, crypto_mod, args.crypto,
                                    CRYPTO_REQUIRED, CRYPTO_CONTENT,
                                    CRYPTO_ANSWER_FIELDS, "Crypto") == 0)
    print()

    ok = questions_ok and acronyms_ok and crypto_ok
    print("OVERALL: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
