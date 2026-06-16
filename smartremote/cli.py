"""smartremote CLI: run | submit | status | answer | selftest."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from . import state as st
from .config import load_config
from .dispatcher import Dispatcher


def _root(args) -> Path:
    return Path(args.root).resolve()


def cmd_run(args) -> None:
    root = _root(args)
    Dispatcher(root, load_config(root / "config.yaml")).run_forever()


def cmd_submit(args) -> None:
    """Local (same-box) submit. For remote, use scripts/submit.sh over SFTP."""
    inbox = _root(args) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    src = Path(args.file)
    staging = inbox / ("." + src.name + ".part")
    shutil.copy2(src, staging)
    staging.rename(inbox / src.name)  # atomic publish on same FS
    print(f"submitted {src.name} -> {inbox / src.name}")


def cmd_status(args) -> None:
    jobs = _root(args) / "jobs"
    if args.job:
        print(json.dumps(st.Status(jobs / args.job).read(), indent=2))
        return
    rows = []
    if jobs.exists():
        for d in sorted(jobs.iterdir()):
            s = st.Status(d)
            if s.exists():
                data = s.read()
                rows.append(
                    (data["id"], data["state"], data["type"], data.get("pending_question") or "-")
                )
    if not rows:
        print("(no jobs)")
        return
    w = max(len(r[0]) for r in rows)
    for jid, state, typ, q in rows:
        print(f"{jid:<{w}}  {state:<14} {typ:<9} q={q}")


def cmd_answer(args) -> None:
    ans = _root(args) / "jobs" / args.job / "answers"
    ans.mkdir(parents=True, exist_ok=True)
    (ans / f"{args.qid}.txt").write_text(args.text, encoding="utf-8")
    print(f"answer recorded for {args.job}/{args.qid}; the dispatcher will resume it")


def cmd_selftest(args) -> None:
    from .selftest import run_selftest

    run_selftest()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="smartremote")
    p.add_argument("--root", default=".", help="project root holding inbox/ and jobs/")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="start the dispatcher loop").set_defaults(fn=cmd_run)
    sp = sub.add_parser("submit", help="publish a job file into the local inbox")
    sp.add_argument("file")
    sp.set_defaults(fn=cmd_submit)
    sp = sub.add_parser("status", help="list jobs or dump one job's status.json")
    sp.add_argument("job", nargs="?")
    sp.set_defaults(fn=cmd_status)
    sp = sub.add_parser("answer", help="record a human answer to a parked job")
    sp.add_argument("job")
    sp.add_argument("qid")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_answer)
    sub.add_parser("selftest", help="hermetic park/resume test in a temp dir").set_defaults(
        fn=cmd_selftest
    )
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
