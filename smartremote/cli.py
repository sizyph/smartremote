"""smartremote CLI:  run | submit | status | answer | selftest | models | hermes."""
from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sys
from pathlib import Path

from . import hermes_setup, models
from . import state as st
from .config import ROLE_HELP, load_config, update_local
from .dispatcher import Dispatcher
from .hermes import HermesNotifier


def _root(args) -> Path:
    return Path(args.root).resolve()


def _cfg(args) -> dict:
    return load_config(_root(args) / "config.yaml")


# ---- core commands --------------------------------------------------------
def cmd_run(args) -> None:
    root = _root(args)
    Dispatcher(root, load_config(root / "config.yaml")).run_forever()


def cmd_submit(args) -> None:
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
                rows.append((data["id"], data["state"], data["type"], data.get("pending_question") or "-"))
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


# ---- models ---------------------------------------------------------------
def cmd_models_show(args) -> None:
    cfg = _cfg(args)
    gpu = models.gpu_info()
    print(f"GPU:    {gpu if gpu else 'no NVIDIA GPU visible (nvidia-smi not found)'}")
    if models.ollama_available():
        installed = models.ollama_list()
        print(f"Ollama: available — {len(installed)} model(s): {', '.join(installed) or '(none pulled)'}")
    else:
        print("Ollama: not installed — curl -fsSL https://ollama.com/install.sh | sh")
    rp = models.remote_provider_status(cfg)
    print("Remote: " + ", ".join(f"{k}={'ok' if v else 'missing'}" for k, v in rp.items()))
    print("\nRoles:")
    roles = cfg["models"]["roles"]
    w = max(len(r) for r in roles)
    for role, help_ in ROLE_HELP.items():
        r = roles.get(role, {})
        target = f"{r.get('provider', '?')}:{r.get('model', '?')}"
        print(f"  {role:<{w}}  {target:<22} {help_}")


def cmd_models_recommend(args) -> None:
    print("Recommended local models for a 24 GB GPU (sizes ~Q4; verify tags on ollama.com):\n")
    w = max(len(r.tag) for r in models.RECOMMENDED)
    for r in models.RECOMMENDED:
        print(f"  {r.tag:<{w}}  {r.params:<20} ~{r.vram_q4_gb:>4.0f} GB  [{r.role}]  {r.note}")
    print("\nPull one with:   smartremote models pull <tag>")
    print("Assign a role:   smartremote models set executor local <tag>")


def cmd_models_pull(args) -> None:
    raise SystemExit(models.ollama_pull(args.tag))


def cmd_models_set(args) -> None:
    if args.role not in ROLE_HELP:
        raise SystemExit(f"unknown role {args.role!r}; choose from {', '.join(ROLE_HELP)}")
    if args.provider not in ("local", "remote"):
        raise SystemExit("provider must be 'local' or 'remote'")
    cfg = _cfg(args)
    if args.provider == "remote":
        known = list((cfg["models"]["remote"]["providers"] or {}))
        if args.model not in known:
            print(f"note: '{args.model}' is not a configured remote provider ({', '.join(known)})")
    update_local(_root(args), {"models": {"roles": {args.role: {"provider": args.provider, "model": args.model}}}})
    print(f"set role {args.role} -> {args.provider}:{args.model}")


def cmd_models_setup(args) -> None:
    cfg = _cfg(args)
    print("=== Model setup ===")
    cmd_models_show(args)
    print()
    cmd_models_recommend(args)
    # Auto-assign remote roles to whatever frontier CLI is installed.
    rp = models.remote_provider_status(cfg)
    if rp.get("codex") and not rp.get("claude-code"):
        update_local(_root(args), {"models": {"roles": {"planner": {"provider": "remote", "model": "codex"}}}})
        print("\nplanner -> codex (claude CLI not found)")
    if args.pull:
        print(f"\nPulling {args.pull} ...")
        models.ollama_pull(args.pull)
        update_local(_root(args), {"models": {"roles": {"executor": {"provider": "local", "model": args.pull}}}})
        print(f"executor -> local:{args.pull}")
    else:
        print("\nTip: pull + assign the executor, e.g.:  smartremote models setup --pull qwen3-coder:32b")


# ---- hermes ---------------------------------------------------------------
def _prompt_email() -> dict | None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("(non-interactive: skipping email; re-run in a terminal or pass --email/--smtp-host/...)")
        return None
    if input("Configure Email notifications? [y/N] ").strip().lower() not in ("y", "yes"):
        return None
    username = input("  email address (username): ").strip()
    smtp_host = input("  SMTP host [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
    smtp_port = input("  SMTP port [587]: ").strip() or "587"
    imap_host = input("  IMAP host [imap.gmail.com]: ").strip() or "imap.gmail.com"
    imap_port = input("  IMAP port [993]: ").strip() or "993"
    password = getpass.getpass("  app password (stored in ~/.hermes/.env, chmod 600): ")
    return {"username": username, "smtp_host": smtp_host, "smtp_port": smtp_port,
            "imap_host": imap_host, "imap_port": imap_port, "password": password}


def _email_from_args(args) -> dict | None:
    if not args.email:
        return None
    password = args.email_password or (
        getpass.getpass("email app password: ") if sys.stdin.isatty() else "")
    return {"username": args.email, "smtp_host": args.smtp_host, "smtp_port": args.smtp_port,
            "imap_host": args.imap_host, "imap_port": args.imap_port, "password": password}


def cmd_hermes_setup(args) -> None:
    root = _root(args)
    email = _email_from_args(args) or _prompt_email()
    if args.whatsapp is None and sys.stdin.isatty() and sys.stdout.isatty():
        whatsapp = input("Configure WhatsApp notifications? [Y/n] ").strip().lower() not in ("n", "no")
    else:
        whatsapp = bool(args.whatsapp)

    compose = hermes_setup.write_compose(root, image=args.image)
    hermes_setup.write_channels(email, whatsapp)
    base_url = f"http://127.0.0.1:{hermes_setup.GATEWAY_PORT}"
    update_local(root, {"hermes": {"enabled": True, "base_url": base_url, "send_path": "/send"}})

    print(f"\nwrote {compose}")
    print(f"wrote channel config -> {hermes_setup.HERMES_HOME}/config.yaml (+ .env for secrets)")
    print(f"wired SmartRemote notifier -> {base_url}")
    print("\nNext:")
    print("  smartremote hermes up        # start the gateway (Docker)")
    if whatsapp:
        print("  docker logs -f hermes-hermes-1   # scan the WhatsApp QR code once, to pair")
    print("  smartremote hermes status    # health check")
    print("  smartremote hermes test      # send yourself a test message")
    if not args.up:
        return
    print("\nStarting gateway ...")
    hermes_setup.up(root)


def cmd_hermes_up(args) -> None:
    raise SystemExit(hermes_setup.up(_root(args)))


def cmd_hermes_down(args) -> None:
    raise SystemExit(hermes_setup.down(_root(args)))


def cmd_hermes_status(args) -> None:
    cfg = _cfg(args)
    base = cfg["hermes"]["base_url"]
    code, body = hermes_setup.health(base)
    if code == 200:
        print(f"hermes: up at {base} (health 200)")
    else:
        print(f"hermes: not reachable at {base} — {body}")
        print("  start it with:  smartremote hermes up")


def cmd_hermes_test(args) -> None:
    cfg = _cfg(args)["hermes"]
    notifier = HermesNotifier(cfg["base_url"], cfg.get("token") or None, send_path=cfg.get("send_path", "/send"))
    try:
        notifier.send(channel=args.channel, subject="SmartRemote test",
                      body="If you can read this, Hermes notifications work.", job_id="hermes-test")
        print(f"sent a test message via {args.channel} to {cfg['base_url']}")
    except Exception as e:  # noqa: BLE001
        print(f"send failed: {e}\n  (is the gateway up and the {args.channel} channel paired?)")


# ---- argparse -------------------------------------------------------------
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
    sp.add_argument("job"); sp.add_argument("qid"); sp.add_argument("text")
    sp.set_defaults(fn=cmd_answer)
    sub.add_parser("selftest", help="hermetic park/resume test").set_defaults(fn=cmd_selftest)

    # models
    mp = sub.add_parser("models", help="show and set up local/remote AI models")
    mp.set_defaults(fn=cmd_models_show)
    msub = mp.add_subparsers(dest="action")
    msub.add_parser("show", help="current roles, GPU, Ollama + remote status").set_defaults(fn=cmd_models_show)
    msub.add_parser("recommend", help="recommended local models for 24 GB").set_defaults(fn=cmd_models_recommend)
    sp = msub.add_parser("pull", help="ollama pull <tag>"); sp.add_argument("tag"); sp.set_defaults(fn=cmd_models_pull)
    sp = msub.add_parser("set", help="assign a model to a role")
    sp.add_argument("role"); sp.add_argument("provider", choices=["local", "remote"]); sp.add_argument("model")
    sp.set_defaults(fn=cmd_models_set)
    sp = msub.add_parser("setup", help="recommend + (optionally) pull + assign roles")
    sp.add_argument("--pull", metavar="TAG", help="ollama pull this tag and set it as executor")
    sp.set_defaults(fn=cmd_models_setup)

    # hermes
    hp = sub.add_parser("hermes", help="install + manage the Hermes notification gateway")
    hp.set_defaults(fn=cmd_hermes_status)
    hsub = hp.add_subparsers(dest="action")
    sp = hsub.add_parser("setup", help="generate compose, configure email/whatsapp, wire SmartRemote")
    sp.add_argument("--email", help="email address / IMAP+SMTP username")
    sp.add_argument("--email-password")
    sp.add_argument("--smtp-host", default="smtp.gmail.com"); sp.add_argument("--smtp-port", default="587")
    sp.add_argument("--imap-host", default="imap.gmail.com"); sp.add_argument("--imap-port", default="993")
    sp.add_argument("--whatsapp", dest="whatsapp", action="store_true", default=None, help="enable WhatsApp channel")
    sp.add_argument("--no-whatsapp", dest="whatsapp", action="store_false")
    sp.add_argument("--image", default=hermes_setup.DEFAULT_IMAGE, help="Hermes Docker image")
    sp.add_argument("--up", action="store_true", help="start the gateway after setup")
    sp.set_defaults(fn=cmd_hermes_setup)
    hsub.add_parser("up", help="start the gateway (docker compose up -d)").set_defaults(fn=cmd_hermes_up)
    hsub.add_parser("down", help="stop the gateway").set_defaults(fn=cmd_hermes_down)
    hsub.add_parser("status", help="gateway health check").set_defaults(fn=cmd_hermes_status)
    sp = hsub.add_parser("test", help="send yourself a test notification")
    sp.add_argument("--channel", default="whatsapp", choices=["whatsapp", "email"])
    sp.set_defaults(fn=cmd_hermes_test)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
