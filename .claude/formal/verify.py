#!/usr/bin/env python3
"""Run OpenTicker's formal verification skills (.claude/skills/verify-*).

    python3 .claude/formal/verify.py                 every skill
    python3 .claude/formal/verify.py tick-answers    one skill (the folder name, with or without "verify-")
    python3 .claude/formal/verify.py --no-tests ...  only the models

For each skill it reads the `metadata` block of its SKILL.md:
  synced   the commit at which someone last confirmed the models describe the code
  covers   the files the models describe
  models   the TLC configs to check (each next to its .tla)
  known    rules that break on the current code and are reported findings, as Config.cfg:Rule
  tests    unittest names that run the real code through the same steps

Then it (1) lists covered files changed since `synced`, (2) checks every rule of every config with TLC, one rule per
run so each one is reported on its own, plus one run for deadlocks, and (3) runs the tests. It exits 1 when a rule
breaks that is not listed as known, when a known one no longer breaks (update the skill), or when a test fails.

TLC comes from tla2tools.jar v1.7.4 (checked by SHA-256), downloaded once to ~/.cache/openticker, or from $TLA2TOOLS.
It needs Java 11 or later (`brew install openjdk` on a Mac). Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".claude" / "skills"
JAR_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
JAR_SHA = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TIMEOUT = 180              # seconds per TLC run; every model here takes one or two


def say(msg=""):
    print(msg, flush=True)


def meta(skill: Path) -> dict:
    """The `metadata:` block of a SKILL.md: `key: value` lines, values split on spaces."""
    text = (skill / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit(f"{skill.name}/SKILL.md has no front matter")
    out, inside = {}, False
    for line in m.group(1).splitlines():
        if line.startswith("metadata:"):
            inside = True
            continue
        if inside:
            if not line.startswith("  "):
                break
            k, _, v = line.strip().partition(":")
            out[k.strip()] = v.split()
    return out


def jar() -> str:
    if os.environ.get("TLA2TOOLS"):
        return os.environ["TLA2TOOLS"]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "openticker"
    path = cache / "tla2tools-1.7.4.jar"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        say(f"Downloading TLC (tla2tools.jar v1.7.4) to {path} ...")
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(JAR_URL, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        if hashlib.sha256(tmp.read_bytes()).hexdigest() != JAR_SHA:
            tmp.unlink()
            raise SystemExit("tla2tools.jar didn't match its checksum; not using it.")
        tmp.rename(path)
    return str(path)


def java() -> str:
    j = shutil.which("java")
    ok = False
    if j:
        r = subprocess.run([j, "-version"], capture_output=True, text=True)
        ok = r.returncode == 0       # macOS has a /usr/bin/java stub that fails when no JDK is installed
    if not ok:
        raise SystemExit("TLC needs Java 11 or later. On a Mac: brew install openjdk, then follow its note to link it.")
    return j


def parse_cfg(text: str):
    """(lines that aren't rules, [rule names]) from a TLC config."""
    keep, rules, cur = [], [], None
    for line in text.splitlines():
        s = line.split("\\*")[0].strip()
        if not s:
            continue
        word = s.split()[0]
        if word in ("INVARIANT", "INVARIANTS", "PROPERTY", "PROPERTIES"):
            cur = word
            rules += [(cur, n) for n in s.split()[1:]]
        elif word.isupper():
            cur = None
            keep.append(line)
        elif cur:
            rules += [(cur, n) for n in s.split()]
        else:
            keep.append(line)
    return keep, rules


def tlc(spec: Path, cfg_text: str, deadlock: bool):
    """Run TLC in a scratch folder. Returns (verdict, output): verdict is "holds", "breaks", "deadlock" or "error"."""
    with tempfile.TemporaryDirectory(prefix="ot-tlc-") as d:
        for f in spec.parent.glob("*.tla"):
            shutil.copy(f, d)
        Path(d, "Check.cfg").write_text(cfg_text)
        cmd = [java(), "-XX:+UseParallelGC", "-cp", jar(), "tlc2.TLC", "-workers", "1", "-cleanup",
               "-metadir", str(Path(d) / "states"), "-config", "Check.cfg", spec.name]
        if not deadlock:
            cmd.insert(-3, "-deadlock")      # TLC's flag means "don't check for deadlock"
        try:
            r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return "error", (f"TLC ran past {TIMEOUT} s. The model has probably lost a bound (a counter that only grows): "
                             "add a CONSTRAINT, or make the constants smaller.")
    out = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if not l.startswith("Picked up JAVA_TOOL_OPTIONS"))
    if "is violated" in out:
        return "breaks", out
    if "Deadlock reached" in out:
        return "deadlock", out
    if "No error has been found" in out:
        return "holds", out
    return "error", out


def trace(out: str) -> str:
    """TLC's counterexample as numbered steps: the action, then only the variables that changed."""
    lines, prev, n = [], {}, 0
    for block in re.split(r"\n(?=State \d+:)", out):
        m = re.match(r"State (\d+): <?(\w[\w ]*?)(?: line \d+.*?)?>?\n(.*)", block, re.S)
        if not m:
            continue
        n += 1
        cur = dict(re.findall(r"^/\\ (\w+) = (.*)$", m.group(3), re.M))
        changed = {k: v for k, v in cur.items() if prev.get(k) != v}
        what = "start" if m.group(2) == "Initial predicate" else m.group(2)
        lines.append(f"    {n}. {what}: " + ", ".join(f"{k} = {v}" for k, v in changed.items()))
        prev = cur
    return "\n".join(lines)


def drift(info: dict):
    base, covers = (info.get("synced") or [""])[0], info.get("covers") or []
    if not base or not covers:
        return []
    r = subprocess.run(["git", "diff", "--name-only", base, "--"] + covers, cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        return [f"(can't compare with {base}: {r.stderr.strip()})"]
    return [l for l in r.stdout.splitlines() if l]


def python_for_tests():
    for p in (ROOT / ".venv" / "bin" / "python", Path.home() / ".openticker" / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def check(skill: Path, run_tests=True) -> bool:
    info = meta(skill)
    say(f"== {skill.name}")
    ok = True
    changed = drift(info)
    if changed:
        say(f"  Changed since the models were last synced ({info['synced'][0]}): {', '.join(changed)}")
        say("  Read those changes against the map in SKILL.md before trusting a pass.")
    known = set(info.get("known") or [])
    seen = set()
    for cfg_name in info.get("models") or []:
        cfg = skill / cfg_name
        text = cfg.read_text()
        keep, rules = parse_cfg(text)
        spec_line = next((l for l in keep if l.strip().startswith("SPECIFICATION")), None)
        mod = re.search(r"^\\\* model: (\w+)", text, re.M)
        spec = skill / ((mod.group(1) if mod else cfg.stem) + ".tla")
        if not spec.exists():
            spec = next(skill.glob("*.tla"))
        base = "\n".join(keep) + "\n"
        verdict, out = tlc(spec, base, deadlock=True)
        states = re.search(r"(\d[\d,]*) distinct states found", out)
        if verdict == "holds":
            say(f"  {cfg_name}: {states.group(1) if states else '?'} states, no step leads nowhere")
        else:
            ok = False
            say(f"  {cfg_name}: {'DEADLOCK' if verdict == 'deadlock' else 'TLC ERROR'}")
            say(trace(out) or "\n".join(out.splitlines()[-25:]))
        for kind, rule in rules:
            key = f"{cfg_name}:{rule}"
            seen.add(key)
            verdict, out = tlc(spec, base + f"{kind} {rule}\n", deadlock=False)
            if verdict == "holds":
                if key in known:
                    ok = False
                    say(f"  {rule}: holds, but SKILL.md lists it as a known break. Update `known` and the findings.")
                else:
                    say(f"  {rule}: holds")
            elif verdict == "breaks":
                if key in known:
                    say(f"  {rule}: breaks (known finding, see SKILL.md)")
                else:
                    ok = False
                    say(f"  {rule}: BREAKS. Shortest path:")
                    say(trace(out))
            else:
                ok = False
                say(f"  {rule}: TLC ERROR\n" + "\n".join(out.splitlines()[-25:]))
    for k in sorted(known - seen):
        ok = False
        say(f"  {k}: listed as known, but no such rule is checked. Fix `known` in SKILL.md.")
    if run_tests and info.get("tests"):
        r = subprocess.run([python_for_tests(), "-m", "unittest", "-q"] + info["tests"], cwd=ROOT,
                           capture_output=True, text=True, timeout=900)
        tail = (r.stderr or r.stdout).strip().splitlines()
        if r.returncode == 0:
            say(f"  tests: {tail[-1] if tail else 'OK'} ({' '.join(info['tests'])})")
        else:
            ok = False
            say("  tests FAILED:\n" + "\n".join("    " + l for l in tail[-40:]))
    say(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def main(argv):
    run_tests = "--no-tests" not in argv
    names = [a for a in argv if not a.startswith("--")]
    skills = sorted(p for p in SKILLS.glob("verify-*") if (p / "SKILL.md").exists())
    if names:
        want = {n if n.startswith("verify-") else "verify-" + n for n in names}
        skills = [s for s in skills if s.name in want]
        if len(skills) != len(want):
            raise SystemExit(f"No such skill. Have: {', '.join(s.name for s in sorted(SKILLS.glob('verify-*')))}")
    results = [check(s, run_tests) for s in skills]
    say()
    say("All checks pass." if all(results) else "Some checks failed; see above.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
