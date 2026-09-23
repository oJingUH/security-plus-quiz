# Security+ (SY0-701) Terminal Quiz

A self-contained, dependency-free terminal quiz game built for the
CompTIA Security+ (SY0-701) exam. Pure Python 3 standard library for the
CLI — no pip installs, no venv, no third-party packages, no TUI framework.
The GUI edition uses PySide6 / Qt6.

## Exam version

The bank targets SY0-701 (V7), which CompTIA retires on June 11, 2027 for the
English exam (August 13, 2027 for Japanese, Portuguese, Spanish and Thai).
Security+ V8 (SY0-801) is expected on or around November 17, 2026, with new
domain weights (16/24/19/27/14), Domain 2 renamed "Threats, Vulnerabilities,
and Attacks", and a new AI objective (2.6). This bank does not cover V8.
Sources: https://www.comptia.org/en-us/certifications/security/v7/ and
https://www.comptia.org/training/resources/exam-objectives/exam-objectives-under-development

## Files

    quiz.py          entry point (single file)
    quiz_gui.py      GUI edition (PySide6) — same bank, same stats
    acronyms.py      acronym-drill logic shared by quiz.py and quiz_gui.py
    acronyms.json    acronym table (all cited to vault notes)
    crypto.py        crypto/algorithm-values drill logic shared by both front-ends
    crypto.json      crypto/algorithm values table (all cited to vault notes)
    questions.json   question bank (all cited to vault notes)
    verify_bank.py   integrity checker for the bank and the drill tables
    verify_negative_controls.py  negative-control suite for the verifier gate
    preview/         rendered GUI screenshots (offscreen, see Self-test / CI)
    assets/          app icon (icon.svg is the source, icon.png is bundled)
    packaging/       build.py + pinned build requirements for the executables
    .github/workflows/release.yml  builds and publishes releases on a version tag
    README.md        this file

## Run it

Download the archive for your OS from the
[Releases](https://github.com/oJingUH/security-plus-quiz/releases) page and
unpack it. Each one holds the GUI (`SecurityPlusQuiz`) and the terminal quiz
(`secplus-quiz`); neither needs Python installed.

- Windows x64: run `SecurityPlusQuiz.exe`. The builds are unsigned, so
  SmartScreen may ask you to confirm ("More info" -> "Run anyway").
- macOS (Apple silicon or Intel): the builds are unsigned, so the first launch
  of `SecurityPlusQuiz.app` needs right-click -> Open. For the terminal quiz,
  clear the download quarantine first:
  `xattr -d com.apple.quarantine secplus-quiz`.
- Linux x64: `./SecurityPlusQuiz`. Built on Ubuntu 24.04, so it needs glibc
  2.39 or newer.

From source:

    python3 quiz.py

That is the entire command. It drops you into a menu.

## Modes

    1) Quick 10        10 random questions across all domains
    2) Daily 10        today's 10 questions, identical for everyone on the same
                       date and bank version, ending in a shareable result card
    3) Practice exam   90 questions in 90 minutes, split by the SY0-701 domain
                       weights, no feedback until the end, estimated scaled score
    4) Domain drill    pick domains (1-5, comma/space, or "all") + length (10/20/all)
    5) Acronym drill   grind acronyms until recall is automatic; both directions
                       (mixed / acronym->expansion / expansion->acronym),
                       length 10 / 20 / all
    6) Crypto & Controls drill  grind crypto values and security-control
                       categories/types until recall is automatic; both
                       directions (mixed / algorithm->value / value->algorithm),
                       length 10 / 20 / all
    7) Review missed   replay questions you previously answered incorrectly
    8) Review acronyms replay acronym items you previously answered incorrectly
    9) Review crypto & controls  replay crypto/control items you previously answered incorrectly
    0) Stats           lifetime & per-domain accuracy, drill accuracy, current/best
                       streak, hardest domain
    q) Quit

### Daily 10

Every player on the same local date gets the same 10 questions in the same
order, as long as they run the same bank version. When the round ends you get a
Wordle-style card to paste anywhere. The GUI copies it with `[C] COPY RESULT`;
the CLI prints it:

    Security+ Daily 10 · 2026-09-23 · 8/10
    🟩🟩🟥🟩🟩🟩🟥🟩🟩🟩
    https://github.com/oJingUH/security-plus-quiz

### Practice exam

It mirrors the real exam's format: at most 90 questions in 90 minutes, drawn
11/20/16/25/18 across the domains to match the SY0-701 weights of
12/22/18/28/20%. There is no feedback until you finish. Ending early (`q`, or
END EXAM in the GUI) or running out of time counts every unanswered question as
wrong. The results show your score, an estimated 100-900 scaled score against
the 750 pass mark, the per-domain breakdown, and each missed question with its
correct answer. The scaled score is a linear estimate. CompTIA doesn't publish
its scaling, and the real exam also has performance-based questions this bank
can't simulate.

## Controls

- Answer multiple choice with `a`-`d` or `1`-`4`; true/false with `t`/`f`
  (or `true`/`false`).
- The acronym and crypto/controls drills take a free-text answer: type the
  expansion (for an acronym prompt), the acronym (for an expansion prompt), the
  value (for an algorithm prompt), or the algorithm (for a value prompt) and
  press Enter. Matching is case-insensitive and tolerates extra whitespace.
- Type `q` at any prompt to abandon the round and return to the menu (in the
  practice exam, `q` ends and scores the exam).
- Question order and multiple-choice option order are shuffled every round;
  a question never repeats within a round.
- After each answer (except in the practice exam) you get immediate feedback: CORRECT/INCORRECT, the right
  answer, a one-line explanation, and the source citation
  (`note > section`).

## Progress

Progress is saved to `stats.json` next to `quiz.py` when run from source, or
in the per-user data directory for the packaged builds (`%APPDATA%` on
Windows, `~/Library/Application Support` on macOS, `$XDG_DATA_HOME` or
`~/.local/share` on Linux, each under `security-plus-quiz/`). It holds
lifetime totals, per-domain correct/total, missed question ids, current and
best streak, and separate `acronyms` and `crypto` sections for drill accuracy.
Drill accuracy
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
and a `value` such as "256-bit" or "Mandate behavior through policy"):

- algorithm -> value  ("AES-256 - key size?" -> "256-bit")
- value -> algorithm  ("Which algorithm has a 160-bit digest?" -> "SHA-1")

Some facts legitimately collide — ECC has two key sizes (256-bit and 384-bit,
so "ECC - key size?" has two right answers), and ECC and ChaCha20 both use a
256-bit key. `build_items` resolves these with an accept-list: every item
carries the full set of valid answers for its (algorithm, property) or
(property, value) key, and grading accepts any of them. Control entries use
their own prompt template instead of the algorithm/value wording — the reverse
direction asks "Which control category/type means '<value>'?".

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
    python3 quiz.py --selftest --daily        # scripted Daily 10 round + share card
    python3 quiz.py --selftest --exam         # scripted practice exam; a fake clock runs out
    python3 quiz.py --seed 42                 # deterministic shuffling
    python3 quiz.py --bank /path/q.json

The GUI has the same discipline headless:

    QT_QPA_PLATFORM=offscreen python3 quiz_gui.py --selftest
    QT_QPA_PLATFORM=offscreen python3 quiz_gui.py --screenshot preview/

## Releases

Pushing a version tag builds the Windows, macOS (Apple silicon and Intel) and
Linux executables and publishes them as a GitHub Release. Ordinary pushes
build nothing.

    git tag v1.2.0
    git push origin v1.2.0

A tag with a hyphen (`v1.2.0-rc.1`) publishes as a pre-release. To try the
builds without releasing, run the `release` workflow from the Actions tab; the
archives appear as workflow artifacts. Each build runs the source self-tests,
then the packaged self-tests, before anything is uploaded.

To build locally for the current OS (PyInstaller cannot cross-compile):

    pip install -r packaging/requirements.txt
    python packaging/build.py --version dev    # -> dist/security-plus-quiz-dev-<os>-<arch>.*

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
        "section": "1.4 — Explain the importance of using appropriate cryptographic solutions"  // exact heading in that note
      },
      "verify": ["SHA-1", "160-bit"]  // optional: literal strings that MUST
    }                                 // appear in the cited section

Rules:

- Only derive questions from the vault notes — do not invent facts.
- The `section` string must exactly match a heading in `note` (e.g.
  `"1.4 — Explain the importance of using appropriate cryptographic
  solutions"`). The em-dash vs hyphen matters.
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

The value->algorithm direction resolves collisions with an accept-list (every
legitimate answer is accepted), so two entries may legitimately share a
`property` and `value`. Run `python3 verify_bank.py` after editing to confirm
citations resolve and the `verify` strings are grounded.

## Grounding

Every question and every drill entry carries a citation back to one of the
vault notes. `verify_bank.py` confirms each cited value actually appears in
the cited section, matched on cell/token boundaries rather than raw
substring: a value must appear as a whole token (or a contiguous run of
tokens), so "LDAP" can never be satisfied by "LDAPS". The vault is read-only
to this project — the quiz never modifies it.

## Current state

The bank holds 208 questions — 186 multiple-choice and 22 true/false (11 true,
11 false) — spread across the five SY0-701 domains, meeting the exam-weight
minimums of 14/26/22/34/24 (total 120). The drill tables hold 316 acronym
entries and 44 crypto/control entries. Every question and drill entry is cited
to a private Obsidian vault that is NOT distributed with this repo, so
`python3 verify_bank.py` passes only when pointed at that vault via `--vault
/path/to/Security+` or the `SECURITY_PLUS_VAULT` environment variable; without
it the checker reports the vault as missing and exits non-zero.

## License

MIT
