#!/usr/bin/env python3
"""Negative controls for the tightened gate.

Each new gate check must make verify_bank.py exit non-zero on a COPY carrying
one defect. This script mutates a copy of the bank/drill tables, runs the
verifier, and asserts the defect is caught (exit != 0). It exits non-zero if any
negative control unexpectedly PASSES (i.e. the gate fails to catch the defect).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = "/home/ojinguh/security-quiz"
VAULT = "/home/ojinguh/Documents/Obsidian Vault/Security+"
VB = os.path.join(HERE, "verify_bank.py")

PASS = 0
failures = []


def _tmp_copy(src):
    fd, dst = tempfile.mkstemp(suffix=".json", prefix="negctl-")
    os.close(fd)
    shutil.copy(src, dst)
    return dst


def run_verify(bank_path=None, acronyms_path=None, crypto_path=None):
    cmd = [sys.executable, VB, "--vault", VAULT]
    if bank_path:
        cmd += ["--bank", bank_path]
    if acronyms_path:
        cmd += ["--acronyms", acronyms_path]
    if crypto_path:
        cmd += ["--crypto", crypto_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode


def check(name, exit_code):
    """A negative control must FAIL (exit != 0)."""
    ok = exit_code != PASS
    print("  [%s] %s -> exit=%d (must be non-zero)" % ("OK" if ok else "FAIL", name, exit_code))
    if not ok:
        failures.append(name)


def main():
    print("Negative controls (each mutated copy must FAIL the verifier)")
    print("=" * 66)
    bank = json.load(open(os.path.join(HERE, "questions.json")))

    # pick a stable mc question to mutate
    q = next(x for x in bank if x["type"] == "mc" and len(x["options"]) == 4)

    # --- (a) ANSWER MIRROR: in-range answer index flip (test A) ---
    path = _tmp_copy(os.path.join(HERE, "questions.json"))
    b = json.load(open(path))
    t = next(x for x in b if x["id"] == q["id"])
    new_idx = (t["answer"] + 1) % len(t["options"])  # different, still in range
    t["answer"] = new_idx
    json.dump(b, open(path, "w"))
    check("answer index flip (in-range)", run_verify(path))

    # --- (a) ANSWER MIRROR: text/answer contradiction (test B) ---
    path = _tmp_copy(os.path.join(HERE, "questions.json"))
    b = json.load(open(path))
    t = next(x for x in b if x["id"] == q["id"])
    wrong = t["options"][(t["answer"] + 1) % len(t["options"])]
    t["answer_text"] = wrong  # contradicts options[answer]
    json.dump(b, open(path, "w"))
    check("answer_text contradiction", run_verify(path))

    # --- (c) ANSWER-BEARING GROUNDING: non-discriminating verify token ---
    path = _tmp_copy(os.path.join(HERE, "questions.json"))
    b = json.load(open(path))
    t = next(x for x in b if x["id"] == q["id"])
    # replace verify with a token that IS grounded but appears in a WRONG option
    # (so it is not drawn from the correct option -> no discriminating token).
    wrong_opt = t["options"][(t["answer"] + 1) % len(t["options"])]
    t["verify"] = [wrong_opt.strip()]
    json.dump(b, open(path, "w"))
    check("non-discriminating verify token", run_verify(bank_path=path))

    # --- (d) TF ANSWER-BEARING GROUNDING: token grounds the subject ---
    # d3-028's false statement is "A warm recovery site is fully operational and
    # ready immediately."; the TRUE fact is that a warm site requires setup.
    # "Warm" is grounded in the cited section but is the statement's subject, so
    # the tf grounding check must reject it (exit != 0).
    path = _tmp_copy(os.path.join(HERE, "questions.json"))
    b = json.load(open(path))
    t = next(x for x in b if x["id"] == "d3-028")
    t["verify"] = ["Warm"]
    json.dump(b, open(path, "w"))
    check("tf token grounds subject, not inverted fact", run_verify(bank_path=path))

    # --- steward C/D/E: drill-table content changed/swapped with verify intact ---
    # C) expansion changed while verify strings stayed intact
    path = _tmp_copy(os.path.join(HERE, "acronyms.json"))
    a = json.load(open(path))
    e = next(x for x in a if x["id"] == "a-mac")
    e["expansion"] = "Access Control List"  # keep verify ["MAC", "Mandatory Access Control"]
    json.dump(a, open(path, "w"))
    check("expansion changed, verify intact (C)", run_verify(acronyms_path=path))

    # D) acronym expansion swapped with another acronym's (both in section)
    path = _tmp_copy(os.path.join(HERE, "acronyms.json"))
    a = json.load(open(path))
    mac = next(x for x in a if x["id"] == "a-mac")
    rbac = next(x for x in a if x["id"] == "a-rbac")
    mac["expansion"], rbac["expansion"] = rbac["expansion"], mac["expansion"]
    json.dump(a, open(path, "w"))
    check("acronym expansion swapped (D)", run_verify(acronyms_path=path))

    # E) crypto value swapped with another value in the same section
    path = _tmp_copy(os.path.join(HERE, "crypto.json"))
    c = json.load(open(path))
    aes = next(x for x in c if x["id"] == "c-aes")
    des = next(x for x in c if x["id"] == "c-3des")
    aes["value"], des["value"] = des["value"], aes["value"]
    json.dump(c, open(path, "w"))
    check("crypto value swapped (E)", run_verify(crypto_path=path))

    # --- (b) COLLISION INVARIANT: colliding drill prompt ---
    sys.path.insert(0, HERE)
    from verify_bank import find_prompt_collisions
    colliding = [
        {"id": "x1", "prompt": "What does MAC stand for?",
         "answer": "Mandatory Access Control"},
        {"id": "x2", "prompt": "What does MAC stand for?",
         "answer": "Media Access Control"},
    ]
    errs = find_prompt_collisions(colliding, "Acronym")
    ok = bool(errs)
    print("  [%s] colliding drill prompt -> %d error(s) (must be > 0)"
          % ("OK" if ok else "FAIL", len(errs)))
    if not ok:
        failures.append("colliding drill prompt")

    print("=" * 66)
    if failures:
        print("NEGATIVE CONTROLS: %d FAILED (gate missed a defect): %s"
              % (len(failures), ", ".join(failures)))
        return 1
    print("NEGATIVE CONTROLS: all caught (exit non-zero) — gate is strict.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
