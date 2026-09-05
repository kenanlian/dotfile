#!/usr/bin/env python3
"""One-shot triage for pi run anomalies: interruption vs dual-writer vs still-alive.

Usage:
  python3 pi-run-forensics.py EVENTS.jsonl [more.jsonl ...]
  python3 pi-run-forensics.py --harvest EVENTS.jsonl OUT.txt

Judges ONLY stdout event files (attempts/*/events.jsonl, --mode json). Session-store
files (~/.pi/agent/sessions/...) never contain agent_settled/agent_end — do not
triage those here. Stdlib only. See references/long-run-supervision.md for the
incident classes and recovery recipes.
"""
import json, sys, subprocess, datetime


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def scan(path):
    st = {"path": path, "lines": 0, "unparsed": 0, "sessions": [], "starts": 0,
          "ends": [], "settled": [], "gaps": [], "max_gap": 0.0,
          "after_first_settled": 0, "last_type": None,
          "last_text": None, "last_text_line": 0}
    first_settled = None
    prev = None  # (line, dt)
    with open(path, errors="replace") as f:
        for i, line in enumerate(f, 1):
            st["lines"] = i
            try:
                ev = json.loads(line)
            except Exception:
                st["unparsed"] += 1
                continue
            t = ev.get("type")
            st["last_type"] = t
            dt = parse_ts(ev.get("timestamp"))
            if dt:
                if prev:
                    gap = (dt - prev[1]).total_seconds()
                    st["max_gap"] = max(st["max_gap"], gap)
                    if gap > 90:
                        st["gaps"].append((prev[0], i, int(gap)))
                prev = (i, dt)
            if t == "session":
                st["sessions"].append((i, ev.get("timestamp"), ev.get("id")))
            elif t == "agent_start":
                st["starts"] += 1
            elif t == "agent_end":
                st["ends"].append((i, ev.get("willRetry")))
            elif t == "agent_settled":
                st["settled"].append(i)
                if first_settled is None:
                    first_settled = i
            elif t == "message_end":
                m = ev.get("message") or {}
                if m.get("role") == "assistant":
                    for c in (m.get("content") or []):
                        if isinstance(c, dict) and c.get("type") == "text" \
                                and len(str(c.get("text", "")).strip()) > 50:
                            st["last_text"], st["last_text_line"] = c["text"], i
            if first_settled is not None and i > first_settled and t != "agent_settled":
                st["after_first_settled"] += 1
    return st


def verdict(st):
    s, a = len(st["settled"]), st["starts"]
    if s >= 2 and a == 1:
        return "DUAL-WRITER: >=2 settled with 1 agent_start — two pi processes shared this session. See references/long-run-supervision.md post-mortem."
    if s == 0:
        return "NO settled: interrupted mid-run OR still running — check writers below before any relaunch."
    if s == 1 and st["after_first_settled"] == 0:
        return "Completed normally (one settled, nothing after)."
    return "Ambiguous: settled=%d agent_start=%d after_first_settled=%d — inspect manually." % (s, a, st["after_first_settled"])


def live_writers(path, session_id):
    out = []
    try:
        r = subprocess.run(["lsof", "-t", path], capture_output=True, text=True, timeout=15)
        out += ["lsof pid " + p for p in r.stdout.split()]
    except Exception as e:
        out.append("lsof failed: %s" % e)
    if session_id:
        try:
            r = subprocess.run(["pgrep", "-fl", session_id], capture_output=True, text=True, timeout=15)
            out += [l for l in r.stdout.splitlines() if l.strip()][:4]
        except Exception:
            pass
    return out or ["none — no live writers/pids found"]


def report(st):
    print("=" * 72)
    print(st["path"])
    print("  lines=%d unparsed=%d  sessions(runs)=%d  agent_start=%d  agent_end=%d  settled=%d  after_first_settled=%d"
          % (st["lines"], st["unparsed"], len(st["sessions"]), st["starts"],
             len(st["ends"]), len(st["settled"]), st["after_first_settled"]))
    if st["sessions"]:
        print("  run boundaries: " + "; ".join("L%d %s %s" % s for s in st["sessions"][:5]))
    if st["ends"]:
        print("  agent_end willRetry: " + ", ".join("L%d:%s" % (i, wr) for i, wr in st["ends"][:5]))
    print("  max timestamp gap: %.0fs; gaps>90s: %s" % (st["max_gap"], st["gaps"][:5] or "none"))
    print("  last event type: %s" % st["last_type"])
    print("  VERDICT: " + verdict(st))
    sid = st["sessions"][0][2] if st["sessions"] else None
    print("  live now: " + "; ".join(live_writers(st["path"], sid)))
    if st["last_text"]:
        print("  final-report preview (L%d): %s" % (st["last_text_line"],
              st["last_text"][:200].replace("\n", " ")))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--harvest":
        st = scan(args[1])
        if not st["last_text"]:
            print("no harvestable assistant text found", file=sys.stderr)
            sys.exit(1)
        open(args[2], "w").write(st["last_text"])
        print("harvested %d chars (from line %d) -> %s" % (len(st["last_text"]), st["last_text_line"], args[2]))
        return
    for p in args:
        try:
            report(scan(p))
        except FileNotFoundError:
            print("%s: file not found" % p, file=sys.stderr)


if __name__ == "__main__":
    main()
