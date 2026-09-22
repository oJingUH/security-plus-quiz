# Security+ (SY0-701) Terminal Quiz

A self-contained, dependency-free terminal quiz game built for the
CompTIA Security+ (SY0-701) exam. Pure Python 3 standard library for the
CLI — no pip installs, no venv, no third-party packages, no TUI framework.
The GUI edition uses PySide6 / Qt6.

## Files

    quiz.py          entry point (single file)
    quiz_gui.py      GUI edition (PySide6) — same bank, same stats
    acronyms.py      acronym-drill logic shared by quiz.py and quiz_gui.py
    acronyms.json    acronym table (all cited to vault notes)
    crypto.py        crypto/algorithm-values drill logic shared by both front-ends
    crypto.json      crypto/algorithm values table (all cited to vault notes)
    questions.json   question bank (all cited to vault notes)
    verify_bank.py   integrity checker for the bank and the drill tables
    README.md        this file

## Run it

    python3 quiz.py

That is the entire command. It drops you into a menu.

## Modes

    1) Quick 10        10 random questions across all domains
    2) Domain drill    pick domains (1-5, comma/space, or "all") + length (10/20/all)
    3) Acronym drill   grind acronyms until recall is automatic; both directions
                       (mixed / acronym->expansion / expansion->acronym),
                       length 10 / 20 / all
    4) Crypto & Controls drill  grind crypto values and security-control
                       categories/types until recall is automatic; both
                       directions (mixed / algorithm->value / value->algorithm),
                       length 10 / 20 / all
    5) Review missed   replay questions you previously answered incorrectly
    6) Review acronyms replay acronym items you previously answered incorrectly
    7) Review crypto & controls  replay crypto/control items you previously answered incorrectly
    8) Stats           lifetime & per-domain accuracy, drill accuracy, current/best
                       streak, hardest domain
    9) Quit

## Controls

- Answer multiple choice with `a`-`d` or `1`-`4`; true/false with `t`/`f`
  (or `true`/`false`).
- The acronym and crypto/controls drills take a free-text answer: type the
  expansion (for an acronym prompt), the acronym (for an expansion prompt), the
  value (for an algorithm prompt), or the algorithm (for a value prompt) and
  press Enter. Matching is case-insensitive and tolerates extra whitespace.
- Type `q` at any prompt to abandon the round and return to the menu.
- Question order and multiple-choice option order are shuffled every round;
  a question never repeats within a round.
- After each answer you get immediate feedback: CORRECT/INCORRECT, the right
  answer, a one-line explanation, and the source citation
  (`note > section`).

## Progress

Progress is saved to `stats.json` next to `quiz.py` (lifetime totals,
per-domain correct/total, missed question ids, current and best streak, and
separate `acronyms` and `crypto` sections for drill accuracy). Drill accuracy
is tracked independently so grinding acronyms or crypto values never distorts
your per-domain scores. A missing or corrupt `stats.json` is treated as a
fresh start — it will never crash the game. Older stats files without an
`acronyms` or `crypto` key load cleanly and keep all their existing values.
Set `NO_COLOR=1` or pipe output to disable colour.

## Drills

Two dedicated drills replace the Network+ edition's port drill. Each is a
section for sitting and grinding the facts until recall is automatic.

### Acronym drill

Quizzes every acronym the vault defines, both directions:

- acronym -> expansion  ("What does AAA stand for?")
- expansion -> acronym  ("Which acronym means 'Authentication, Authorization,
  and Accounting'?")

### Crypto & Controls drill

Quizzes crypto/algorithm values AND the security-control categories/types,
both directions, each deriving from a single entry (an `algorithm`/control name,
a `property` such as "key size", "digest", "control category" or "control type",
and a `value` such as "256-bit" or "Mandate behavior through policy"). The
`property` disambiguates the reverse prompt so two algorithms that share a value
(e.g. two different 256-bit properties) stay unambiguous:

- algorithm -> value  ("AES-256 - key size?" -> "256-bit")
- value -> algorithm  ("Which algorithm has a 160-bit digest?" -> "SHA-1")

The ten control-category/type entries (technical, managerial, operational,
physical, preventive, deterrent, detective, corrective, compensating, directive)
are high-yield memorization facts and live in the same `crypto.json` table, so
this one drill covers both crypto values and the control taxonomy.

Both the CLI (`quiz.py`) and the GUI (`quiz_gui.py`) reach both drills; each
front-end drives them through the SAME code path (one generic drill runner
keyed off the shared `acronyms.py` / `crypto.py` interface), so the two tools
cannot drift.

## Self-test / CI

    python3 quiz.py --selftest                # scripted 10-question round, no stdin, exit 0
    python3 quiz.py --selftest --acronyms     # scripted acronym-drill round, no stdin
    python3 quiz.py --selftest --crypto       # scripted crypto-drill round, no stdin
    python3 quiz.py --selftest --review       # scripted review-missed-questions round
    python3 quiz.py --selftest --review-acronyms  # scripted review-missed-acronyms round
    python3 quiz.py --selftest --review-crypto    # scripted review-missed-crypto round
    python3 quiz.py --seed 42                 # deterministic shuffling
    python3 quiz.py --bank /path/q.json

The GUI has the same discipline headless:

    QT_QPA_PLATFORM=offscreen python3 quiz_gui.py --selftest
    QT_QPA_PLATFORM=offscreen python3 quiz_gui.py --screenshot preview/

## Verify the bank

    python3 verify_bank.py
    python3 verify_bank.py --vault /path/to/Security+

Prints a PASS/FAIL summary and exits non-zero on any failure. The vault each
citation points into is resolved in this order: an explicit `--vault
/path/to/Security+`, then the `SECURITY_PLUS_VAULT` environment variable, then
`Security+` in the current directory. It checks:

- JSON parses; every required field present; answer index/letter in range
- no duplicate ids; exactly one correct option; unique options
- ANSWER MIRROR: every question carries `answer_text` holding the correct
  option's text, and `options[answer] == answer_text` (catches an in-range
  answer-index flip and a text/answer contradiction)
- ANSWER-BEARING GROUNDING: every multiple-choice question carries a `verify`
  token drawn from the CORRECT option's text that is present in the cited
  section and absent from every other option
- every citation's note file exists and its section heading exists in it
  (exact match, em-dash sensitive)
- for fact items (a `"verify"` list), the cited section actually contains each
  expected value, matched on CELL/TOKEN BOUNDARIES (never raw substring, so
  "LDAPS" can never satisfy "LDAP")
- per-domain counts meet the exam-weight targets (14/26/22/34/24, total 120)

It also validates `acronyms.json` and `crypto.json`:

- parses; every required field present; ids unique; `display` values unique
- every citation's note file exists and its section heading exists in it
  (exact match, em-dash sensitive)
- every string in `verify` actually appears in the cited section (cell/token
  boundary)
- ANSWER-BEARING GROUNDING: each entry's answer fields (acronym+expansion, or
  algorithm+value) are covered by its `verify` list, so a content field changed
  or swapped while its verify strings stay intact fails
- COLLISION INVARIANT: no two drill items share a prompt with different expected
  answers unless every expected answer is in each item's accept-list
- both drill directions are derivable from every entry

The negative-control suite (`verify_negative_controls.py`) mutates a copy of the
bank and both drill tables one defect at a time and asserts the tightened gate
exits non-zero for each.

The question bank and drill tables are cited to a private Obsidian vault that
is not distributed with this repo, so the citations cannot be re-verified
without it — `--vault` is how you point it at your own.

## Adding questions

Edit `questions.json`. Each question is one object:

    {
      "id": "d1-053",              // unique string
      "domain": 1,                 // 1..5
      "type": "mc",                // "mc" (4 options) or "tf" (True/False)
      "question": "Which algorithm produces a 160-bit digest?",
      "options": ["MD5", "SHA-1", "SHA-256", "SHA-512"],  // 4 for mc; ["True","False"] for tf
      "answer": 1,                 // 0-based index of the correct option
      "answer_text": "SHA-1",     // MUST equal options[answer] (answer mirror)
      "explanation": "SHA-1 produces a 160-bit digest.",
      "difficulty": "easy",        // "easy" | "medium" | "hard"
      "source": {
        "note": "Domains/1 - General Security Concepts.md",  // path relative to the vault
        "section": "1.4 - Cryptography"                     // a heading that exists in that note
      },
      "verify": ["SHA-1", "160-bit"]  // optional: literal strings that MUST
    }                                 // appear in the cited section

Rules:

- Only derive questions from the vault notes — do not invent facts.
- The `section` string must exactly match a heading in `note` (e.g.
  `"1.4 - Cryptography"`). The em-dash vs hyphen matters.
- Add a `"verify"` list for any numeric/acronym/crypto item so
  `verify_bank.py` can confirm the fact actually appears in the source.

Run `python3 verify_bank.py` after editing; it will catch bad citations and
ungrounded values.

## Adding drill entries

Append one object to `acronyms.json`:

    {
      "id": "aaa",                            // unique, stable
      "display": "AAA",                       // how the acronym is shown
      "acronym": "AAA",                       // the acronym itself
      "expansion": "Authentication, Authorization, and Accounting",
      "source": { "note": "...", "section": "..." },
      "verify": ["AAA", "Authentication, Authorization, and Accounting"]
    }

Or one object to `crypto.json`:

    {
      "id": "aes-256",                        // unique, stable
      "display": "AES-256",                   // how the algorithm is shown
      "algorithm": "AES-256",                 // the algorithm name
      "property": "key size",                 // what is being asked
      "value": "256-bit",                     // the answer to the algorithm->value direction
      "source": { "note": "...", "section": "..." },
      "verify": ["AES-256", "256-bit"]
    }

The `property` field is what makes the value->algorithm direction
unambiguous; keep `(property, value)` unique per algorithm. Run
`python3 verify_bank.py` after editing to confirm citations resolve and the
`verify` strings are grounded.

## Grounding

Every question and every drill entry carries a citation back to one of the
vault notes. `verify_bank.py` confirms each cited value actually appears in
the cited section, matched on cell/token boundaries rather than raw
substring: a value must appear as a whole token (or a contiguous run of
tokens), so "LDAP" can never be satisfied by "LDAPS". The vault is read-only
to this project — the quiz never modifies it.

## Current state

The question bank and both drill tables currently hold SEED / STUB data only
(ids prefixed `seed-`): 10 questions, 6 acronyms, 6 crypto entries. The real
bank (180-190 questions) and the full acronym/crypto tables land in a later
pass; the schemas above are final, so that pass is data-only. The citations
point at future vault notes that do not exist yet, and the seed counts are far
below the exam-weight targets — therefore `python3 verify_bank.py` is EXPECTED
TO FAIL right now (vault not found / per-domain counts LOW). Once the real
bank, tables, and vault notes land, it should pass.

## License

MIT
