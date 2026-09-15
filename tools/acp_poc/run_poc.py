"""ACP PoC scenario driver (stdlib only, no app imports, no DB).

Usage:
  python3 run_poc.py --profile codex|opencode --scenario initialize
  python3 run_poc.py --profile opencode --scenario new-prompt
  python3 run_poc.py --profile codex --scenario cancel --cancel-kind session
  python3 run_poc.py --profile codex --scenario resume
  python3 run_poc.py --profile opencode --scenario permission

Scenarios after `initialize` may invoke the LLM (cost) and are opt-in via flags.
Artifacts are redacted (secret values never persisted).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from acp_harness import AcpConnection, Redactor, ScenarioRecorder, load_dotenv_values

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DEFAULT_POC_ENV = Path(os.path.expanduser("~/.config/obsidian-ai-hub/acp-poc.env"))

READONLY_PROMPT = (
    "Reply with exactly this single line and nothing else: POC-OK. "
    "Do not edit, create, delete, or move any files. "
    "Do not run any shell commands."
)

PERMISSION_PROBE_PROMPT = (
    "List the files in the current directory by running a shell command, "
    "then report the result. "
    "Reply format: first line exactly PROBE-DONE, then your report."
)


def load_profile(name: str) -> dict:
    path = HERE / "profiles" / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    argv = [
        (str(REPO_ROOT) if a == "<REPO>" else a)
        for a in [profile["executable"], *profile["argv"]]
    ]
    # Expand the <REPO> placeholder which may be glued to a longer path.
    argv = [a.replace("<REPO>", str(REPO_ROOT)) for a in argv]
    profile["_argv"] = argv
    return profile


def make_temp_repo() -> str:
    tmp = tempfile.mkdtemp(prefix="acp-poc-")
    subprocess.run(["git", "init", "-q", tmp], check=True, timeout=30)
    subprocess.run(
        ["git", "-C", tmp, "config", "user.email", "poc@example.invalid"],
        check=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "-C", tmp, "config", "user.name", "acp-poc"],
        check=True,
        timeout=30,
    )
    Path(tmp, "README.md").write_text("# acp poc temp repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", tmp, "add", "."], check=True, timeout=30)
    subprocess.run(
        ["git", "-C", tmp, "commit", "-qm", "poc fixture"],
        check=True,
        timeout=30,
    )
    return tmp


def git_status(repo: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, "status", "--porcelain=v1"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout.strip()


def build_child_env(poc_env: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(poc_env)  # verification credentials for the agent subprocess only
    return env


def do_initialize(conn: AcpConnection, rec: ScenarioRecorder, timeout: float) -> dict:
    params = {
        "protocolVersion": 1,
        "clientCapabilities": {},  # minimal: no fs / terminal / elicitation
        "clientInfo": {
            "name": "acp-poc-harness",
            "title": "ACP PoC Harness",
            "version": "0.1.0",
        },
    }
    rec.sent({"jsonrpc": "2.0", "id": "initialize", "method": "initialize", "params": params})
    resp = conn.request("initialize", params, timeout=timeout)
    rec.received(resp)
    return resp


def do_new_session(
    conn: AcpConnection, rec: ScenarioRecorder, cwd: str, timeout: float
) -> dict:
    params = {"cwd": cwd, "mcpServers": []}
    rec.sent({"jsonrpc": "2.0", "id": "session/new", "method": "session/new", "params": params})
    resp = conn.request("session/new", params, timeout=timeout)
    rec.received(resp)
    return resp


def deny_option(options: list[dict]) -> str | None:
    for opt in options:
        kind = str(opt.get("kind", ""))
        if kind.startswith("reject"):
            return str(opt.get("optionId"))
    return None


def pump_agent_requests(
    conn: AcpConnection,
    rec: ScenarioRecorder,
    permission_policy: str,
    cancelled_turn: bool = False,
) -> list[dict]:
    """Answer agent->client requests per PoC policy; return the observed ones."""
    seen = []
    for req in conn.drain_client_requests():
        rec.received(req)
        seen.append(req)
        rid = req.get("id")
        method = req.get("method", "")
        if rid is None:
            continue
        if method == "session/request_permission":
            if cancelled_turn:
                conn.respond(rid, {"outcome": {"outcome": "cancelled"}})
                rec.sent({"jsonrpc": "2.0", "id": rid, "result": {"outcome": {"outcome": "cancelled"}}})
                continue
            params = req.get("params", {}) if isinstance(req.get("params"), dict) else {}
            options = params.get("options", [])
            if permission_policy == "deny":
                opt_id = deny_option(options) if isinstance(options, list) else None
                if opt_id is not None:
                    conn.respond(rid, {"outcome": {"outcome": "selected", "optionId": opt_id}})
                    rec.sent({"jsonrpc": "2.0", "id": rid, "result": {"outcome": {"outcome": "selected", "optionId": opt_id}}})
                else:
                    conn.respond_error(rid, -32601, "PoC harness denies permission requests without reject options")
                    rec.sent({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "denied"}})
            else:
                conn.respond_error(rid, -32602, "allow policy not enabled in PoC")
                rec.sent({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "allow not enabled"}})
        else:
            # fs/*, terminal/*, elicitation/* and anything else: not advertised.
            conn.respond_error(rid, -32601, f"method not supported by PoC harness: {method}")
            rec.sent({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not supported"}})
    return seen


def wait_prompt(
    conn: AcpConnection,
    rec: ScenarioRecorder,
    prompt_rid: int,
    timeout: float,
    permission_policy: str,
    poll_s: float = 0.5,
) -> tuple[dict | None, list[dict], list[dict]]:
    """Wait for session/prompt response while pumping agent requests/updates."""
    deadline = time.monotonic() + timeout
    agent_requests: list[dict] = []
    updates: list[dict] = []
    while time.monotonic() < deadline:
        agent_requests.extend(
            pump_agent_requests(conn, rec, permission_policy, cancelled_turn=False)
        )
        for n in conn.drain_notifications():
            rec.received(n)
            updates.append(n)
        resp = conn.wait_for_response(prompt_rid, timeout=poll_s)
        if resp is not None:
            rec.received(resp)
            # Final pump so late permission requests are answered/cancelled.
            agent_requests.extend(
                pump_agent_requests(conn, rec, permission_policy, cancelled_turn=False)
            )
            for n in conn.drain_notifications():
                rec.received(n)
                updates.append(n)
            return resp, agent_requests, updates
    return None, agent_requests, updates


def run_scenario(args, profile: dict, poc_env: dict[str, str], redactor: Redactor) -> dict:
    tmp_repo = make_temp_repo()
    status_before = git_status(tmp_repo)
    rec = ScenarioRecorder()
    rec.note(f"profile={profile['profileId']} pinned={profile.get('pinnedVersion')}")
    rec.note(f"tmp_repo={tmp_repo} git_status_before={status_before!r}")

    conn = AcpConnection(
        argv=profile["_argv"],
        env=build_child_env(poc_env),
        cwd=tmp_repo,
        redactor=redactor,
    )
    result: dict = {
        "profile": profile["profileId"],
        "pinnedVersion": profile.get("pinnedVersion"),
        "scenario": args.scenario,
        "envVarNames": sorted(poc_env.keys()),
        "tmpRepo": tmp_repo,
        "gitStatusBefore": status_before,
    }
    t_start = time.monotonic()
    try:
        conn.start()
        rec.note(f"spawned pid={conn.pid} pgid={conn.pgid} argv={profile['_argv']}")
        time.sleep(1.0)  # let stderr boot logs flush

        init_resp = do_initialize(conn, rec, timeout=args.rpc_timeout)
        result["initialize"] = init_resp.get("result") or {"error": init_resp.get("error")}
        caps = (init_resp.get("result") or {}).get("agentCapabilities", {})

        if args.scenario == "initialize":
            pass
        else:
            new_resp = do_new_session(conn, rec, tmp_repo, timeout=args.rpc_timeout)
            result["sessionNew"] = new_resp.get("result") or {"error": new_resp.get("error")}
            session_id = (new_resp.get("result") or {}).get("sessionId")

            if args.scenario in ("new-prompt", "cancel", "permission"):
                prompt_text = PERMISSION_PROBE_PROMPT if args.scenario == "permission" else READONLY_PROMPT
                prompt_rid = conn.send_request_async(
                    "session/prompt",
                    {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt_text}]},
                )
                rec.sent({"jsonrpc": "2.0", "id": prompt_rid, "method": "session/prompt",
                          "params": {"sessionId": session_id, "prompt": "[text prompt]"}})
                if args.scenario == "cancel":
                    # Let the turn run briefly, then cancel.
                    time.sleep(args.cancel_after_s)
                    pump_agent_requests(conn, rec, args.permission_policy)
                    for n in conn.drain_notifications():
                        rec.received(n)
                    if args.cancel_kind == "session":
                        conn.notify("session/cancel", {"sessionId": session_id})
                        rec.sent({"jsonrpc": "2.0", "method": "session/cancel",
                                  "params": {"sessionId": session_id}})
                    else:
                        conn.notify("$/cancel_request", {"id": prompt_rid})
                        rec.sent({"jsonrpc": "2.0", "method": "$/cancel_request",
                                  "params": {"id": prompt_rid}})
                    resp, agent_reqs, updates = wait_prompt(
                        conn, rec, prompt_rid, timeout=args.prompt_timeout,
                        permission_policy=args.permission_policy)
                    # Pending permission requests after cancel get cancelled outcome.
                    pump_agent_requests(conn, rec, args.permission_policy, cancelled_turn=True)
                    result["cancelKind"] = args.cancel_kind
                    result["promptResponse"] = resp
                    result["updateCount"] = len(updates)
                    result["updateKinds"] = sorted({str((u.get("params") or {}).get("update", {}).get("sessionUpdate")) for u in updates if isinstance(u.get("params"), dict)})
                    result["agentRequestCount"] = len(agent_reqs)
                    result["agentRequestMethods"] = sorted({str(r.get("method")) for r in agent_reqs})
                else:
                    resp, agent_reqs, updates = wait_prompt(
                        conn, rec, prompt_rid, timeout=args.prompt_timeout,
                        permission_policy=args.permission_policy)
                    result["promptResponse"] = resp
                    result["promptTimedOut"] = resp is None
                    result["updateCount"] = len(updates)
                    result["updateKinds"] = sorted({str((u.get("params") or {}).get("update", {}).get("sessionUpdate")) for u in updates if isinstance(u.get("params"), dict)})
                    result["agentRequestCount"] = len(agent_reqs)
                    result["agentRequestMethods"] = sorted({str(r.get("method")) for r in agent_reqs})

            if args.scenario == "resume":
                # Close this connection (process exit), then reconnect and probe
                # resume/load. Calls are only attempted when advertised.
                term1 = conn.terminate()
                rec.note(f"first connection terminated: {term1}")
                result["firstTerminate"] = {**term1, "orphans": list(term1.get("orphans", []))}
                conn2 = AcpConnection(argv=profile["_argv"], env=build_child_env(poc_env),
                                      cwd=tmp_repo, redactor=redactor)
                conn2.start()
                rec.note(f"reconnected pid={conn2.pid}")
                try:
                    init2 = do_initialize(conn2, rec, timeout=args.rpc_timeout)
                    caps2 = (init2.get("result") or {}).get("agentCapabilities", {})
                    result["reinitialize"] = init2.get("result") or {"error": init2.get("error")}
                    resume_adv = isinstance(caps2.get("sessionCapabilities"), dict) and "resume" in caps2["sessionCapabilities"]
                    load_adv = caps2.get("loadSession") is True
                    result["resumeAdvertised"] = bool(resume_adv)
                    result["loadAdvertised"] = bool(load_adv)
                    if resume_adv:
                        r = conn2.request("session/resume",
                                          {"sessionId": session_id, "cwd": tmp_repo, "mcpServers": []},
                                          timeout=args.rpc_timeout)
                        rec.received(r)
                        result["resumeResponse"] = r
                    else:
                        rec.note("session/resume not advertised; skipped per spec")
                    if load_adv:
                        r = conn2.request("session/load",
                                          {"sessionId": session_id, "cwd": tmp_repo, "mcpServers": []},
                                          timeout=args.rpc_timeout)
                        rec.received(r)
                        result["loadResponse"] = r
                        # Collect replayed updates briefly.
                        time.sleep(3.0)
                        for n in conn2.drain_notifications():
                            rec.received(n)
                    else:
                        rec.note("session/load not advertised; skipped per spec")
                finally:
                    term2 = conn2.terminate()
                    rec.note(f"second connection terminated: {term2}")
                    result["secondTerminate"] = {**term2, "orphans": list(term2.get("orphans", []))}
                    conn.proc = None  # avoid double-terminate of conn1 below
    finally:
        if conn.proc is not None and not conn._closed:
            term = conn.terminate()
            rec.note(f"terminated: exit={term['exitCode']} signalled={term['signalled']}")
            result["terminate"] = {**term, "orphans": list(term.get("orphans", []))}
        result["elapsed_s"] = round(time.monotonic() - t_start, 2)
        result["gitStatusAfter"] = git_status(tmp_repo)
        result["repoClean"] = result["gitStatusAfter"] == status_before
        result["stderrRedacted"] = conn.redacted_stderr()
        result["nonJsonStdoutLines"] = [redactor(l) for l in conn.non_json_stdout]
        result["transcript"] = rec.export(redactor)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="ACP Phase 0 PoC driver")
    ap.add_argument("--profile", choices=["codex", "opencode"], required=True)
    ap.add_argument(
        "--scenario",
        choices=["initialize", "new-prompt", "cancel", "resume", "permission"],
        default="initialize",
    )
    ap.add_argument("--cancel-kind", choices=["session", "cancel_request"], default="session")
    ap.add_argument("--cancel-after-s", type=float, default=8.0)
    ap.add_argument("--rpc-timeout", type=float, default=60.0)
    ap.add_argument("--prompt-timeout", type=float, default=300.0)
    ap.add_argument("--permission-policy", choices=["deny"], default="deny")
    ap.add_argument("--poc-env", default=str(DEFAULT_POC_ENV))
    ap.add_argument("--artifact-dir", default=None)
    args = ap.parse_args()

    profile = load_profile(args.profile)
    poc_env = load_dotenv_values(args.poc_env)
    redactor = Redactor(poc_env)

    result = run_scenario(args, profile, poc_env, redactor)

    date = datetime.date.today().isoformat()
    outdir = Path(args.artifact_dir or (REPO_ROOT / "docs" / "acp" / "artifacts" /
                                        f"{args.profile}-{profile.get('pinnedVersion')}-{date}"))
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / f"{args.scenario}-{args.cancel_kind if args.scenario == 'cancel' else 'run'}.json"
    # Final safety: redact serialized artifact once more before writing.
    raw = json.dumps(result, ensure_ascii=False, indent=2)
    outpath.write_text(redactor(raw) + "\n", encoding="utf-8")
    print(f"artifact: {outpath}")
    print(f"repoClean={result.get('repoClean')} elapsed={result.get('elapsed_s')}s")
    for secret_val in poc_env.values():
        if secret_val and len(secret_val) >= 4 and secret_val in raw:
            print("FATAL: secret value leaked into artifact", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
