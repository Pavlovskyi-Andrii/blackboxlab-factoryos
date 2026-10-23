import argparse
import json
import os
import pathlib
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

FACTORY_URL=os.environ.get("FACTORY_URL","").strip().rstrip("/")
TOKEN=os.environ.get("FACTORY_CLAUDE_RUNNER_TOKEN","").strip()
REPO=pathlib.Path(os.environ.get("FACTORY_REPO",os.getcwd())).resolve()
HEARTBEAT_SECONDS=max(10,min(60,int(os.environ.get("FACTORY_CLAUDE_HEARTBEAT_SECONDS","20"))))


def run_text(cmd,cwd=None,timeout=30):
    try:
        p=subprocess.run(cmd,cwd=cwd,text=True,capture_output=True,timeout=timeout,check=False)
        return p.returncode,(p.stdout or "").strip(),(p.stderr or "").strip()
    except Exception as exc:
        return 127,"",str(exc)


def claude_version():
    code,out,err=run_text(["claude","--version"],timeout=15)
    return out if code==0 else ""


def git_branch():
    if not (REPO/".git").exists():
        return ""
    code,out,_=run_text(["git","branch","--show-current"],cwd=REPO,timeout=10)
    return out if code==0 else ""


def auth_mode(verify=False):
    if os.environ.get("ANTHROPIC_API_KEY","").strip():
        return "api_key_override","ANTHROPIC_API_KEY is set; Claude Code will use separately billed API usage."
    if not claude_version():
        return "claude_missing","Claude Code CLI is not installed or not on PATH."
    if not verify:
        return "subscription_unverified","Run this runner once with --verify after Claude Code /login."
    with tempfile.TemporaryDirectory(prefix="factoryos-claude-auth-") as td:
        code,out,err=run_text([
            "claude","-p",
            "Reply with exactly FACTORYOS_AUTH_OK. Do not inspect or modify files.",
            "--max-turns","1","--output-format","text"
        ],cwd=td,timeout=90)
    if code==0 and "FACTORYOS_AUTH_OK" in out:
        return "subscription_verified",""
    return "auth_failed",(err or out or "Claude Code authentication verification failed.")[:500]


def post_json(path,payload):
    if not FACTORY_URL or not TOKEN:
        raise RuntimeError("FACTORY_URL and FACTORY_CLAUDE_RUNNER_TOKEN are required")
    req=urllib.request.Request(
        FACTORY_URL+path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req,timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def heartbeat(mode,last_error=""):
    payload={
        "hostname":socket.gethostname(),
        "os":platform.platform(),
        "python":sys.version.split()[0],
        "claude_version":claude_version(),
        "auth_mode":mode,
        "repo":str(REPO),
        "branch":git_branch(),
        "last_error":str(last_error or "")[:500],
    }
    return post_json("/api/claude-runner/heartbeat",payload)


def main():
    parser=argparse.ArgumentParser(description="FactoryOS Claude Code Pro runner")
    parser.add_argument("--verify",action="store_true",help="Verify Claude Code subscription login with one tiny Claude Code call.")
    parser.add_argument("--once",action="store_true",help="Send one heartbeat and exit.")
    args=parser.parse_args()

    mode,error=auth_mode(args.verify)
    if mode=="api_key_override":
        print("WARNING:",error,file=sys.stderr)
    elif mode in {"claude_missing","auth_failed"}:
        print("ERROR:",error,file=sys.stderr)

    while True:
        try:
            result=heartbeat(mode,error)
            state="online" if result.get("online") else "registered"
            print(f"FactoryOS Claude runner: {state} · auth={mode} · branch={git_branch() or '-'}",flush=True)
        except Exception as exc:
            print("FactoryOS heartbeat failed:",exc,file=sys.stderr,flush=True)
        if args.once:
            return 0
        time.sleep(HEARTBEAT_SECONDS)


if __name__=="__main__":
    raise SystemExit(main())
