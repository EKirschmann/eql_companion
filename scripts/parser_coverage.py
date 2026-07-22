"""Parser regression/coverage runner.

Usage (repo root):  python scripts/parser_coverage.py [logfile ...]
With no args it runs the vendored fixture(s) in tests/fixtures/ AND the
newest real log in EQL_LOG_DIR (if present). A category dropping to zero
against a file that used to produce it means a format broke.
"""
import glob
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.log_system.parser import parse_line, extract_character_from_filename  # noqa: E402


def run(path: str) -> Counter:
    from pathlib import Path
    name, _ = extract_character_from_filename(Path(path))
    counts: Counter = Counter()
    unparsed = 0
    with open(path, "rb") as f:
        for bline in f:
            line = bline.decode("cp1252", errors="replace")
            e = parse_line(line, name)
            if e:
                counts[e.type] += 1
            elif line.strip():
                unparsed += 1
    total = sum(counts.values())
    print(f"\n{os.path.basename(path)}: {total} events, {unparsed} unparsed lines")
    for t, n in counts.most_common():
        print(f"  {t:14} {n}")
    return counts


def main() -> None:
    targets = sys.argv[1:]
    if not targets:
        targets = sorted(glob.glob(os.path.join("tests", "fixtures", "eqlog_*.txt")))
        try:
            from backend.config import settings
            logs = sorted(glob.glob(os.path.join(settings.eql_log_dir, "eqlog_*.txt")),
                          key=os.path.getmtime, reverse=True)
            if logs:
                targets.append(logs[0])
        except Exception:
            pass
    for t in targets:
        run(t)


if __name__ == "__main__":
    main()