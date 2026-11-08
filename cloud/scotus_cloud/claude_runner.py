"""Bounded subscription Claude Code calls, using the same private host tools."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import jsonschema
from .card_mcp import card_server
from .research_errors import ResearchUnavailable

CLAUDE_VERSION = '2.1.317'


def oauth_value(raw):
    value = json.loads(raw)
    token = value.get('oauth_token')
    if not isinstance(token, str) or not token.strip() or len(token) > 16384 or any(c.isspace() for c in token):
        raise ValueError('Expected a Claude setup-token credential')
    return token


def claude_access(cloud, secret_name):
    executable = shutil.which('claude')
    if not executable: raise ResearchUnavailable('setup', 'Install the pinned Claude Code CLI before enabling hybrid cards', 3600)
    try:
        version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=10, check=True).stdout
    except Exception:
        raise ResearchUnavailable('setup', 'The pinned Claude Code CLI could not start', 3600) from None
    if not version.startswith(CLAUDE_VERSION + ' '):
        raise ResearchUnavailable('setup', 'Claude CLI version differs from the tested version', 3600)
    try: return executable, oauth_value(cloud.secret(secret_name))
    except Exception: raise ResearchUnavailable('auth', 'Configure the dedicated Claude subscription credential', 3600) from None


def run_claude(dashboard, cloud, secret_name, prompt, schema, model, *, inputs=None,
               tools=(), tool_handler=None, web=False, timeout_seconds=900,
               max_turns=48, on_start=lambda: None, on_usage=lambda _: None, references=None):
    if os.environ.get('SCOTUS_PRIVATE_CODEX_WORKER') != '1':
        raise RuntimeError('Claude research runs only in the private enrichment worker')
    if not 1 <= timeout_seconds <= 1200 or not 1 <= max_turns <= 200:
        raise ValueError('Invalid Claude research budget')
    if not tools or tool_handler is None: raise ValueError('Supply the private card tools')
    if model not in ('haiku', 'opus') and not model.startswith('claude-'):
        raise ValueError('Specify the requested Claude research model')
    from .codex_auth import _validated_inputs
    files = _validated_inputs(inputs)
    executable, oauth = claude_access(cloud, secret_name)
    lease = dashboard.call('auth_claim', name='claude')
    if not lease: raise ResearchUnavailable('busy', 'Another Claude research turn is active', 300)
    stop = threading.Event(); errors = []
    def renew():
        while not stop.wait(30):
            try: dashboard.call('auth_check', name='claude', token=lease)
            except Exception:
                errors.append(True)
                if process is not None:
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                return
    process = None
    thread = threading.Thread(target=renew, daemon=True); thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='private-claude-') as folder, card_server(tools, tool_handler) as config:
            root = Path(folder).resolve(); root.chmod(0o700)
            # A clean HOME/config prevents desktop login, hooks, plugins and paid-key fallback.
            home = root / 'home'; home.mkdir(mode=0o700)
            data_root = root / 'data'; data_root.mkdir(mode=0o700)
            for name, content in files.items():
                target = data_root / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content); target.chmod(0o400)
            policy = {'disableAllHooks': True, 'autoMemoryEnabled': False}
            if references is not None:
                from .card_library import mount_references
                library = mount_references(data_root, references)
                policy['permissions'] = {'blockReadsOutsideWorkingDirectories': True,
                    'blockWritesOutsideWorkingDirectories': True, 'additionalDirectories': [str(library)],
                    'deny': ['Read(/' + str(home) + '/**)', 'Read(/' + str(root / 'mcp.json') + ')',
                             'Read(/' + str(root / 'result.json') + ')', 'Read(/' + str(root / 'stderr.txt') + ')']}
            settings = root / 'settings.json'; settings.write_text(json.dumps(policy))
            mcp = root / 'mcp.json'; mcp.write_text(json.dumps(config)); mcp.chmod(0o600)
            system = root / 'policy.txt'; system.write_text(prompt)
            env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
            env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / '.claude'), CLAUDE_CODE_OAUTH_TOKEN=oauth,
                       DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                       CLAUDE_CODE_DISABLE_BACKGROUND_TASKS='1', CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS='0',
                       MCP_TOOL_TIMEOUT=str(timeout_seconds * 1000), CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=str(timeout_seconds * 1000),
                       CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION='60')
            native = ','.join((['Read', 'Grep', 'Glob'] if references is not None else []) + (['WebSearch', 'WebFetch'] if web else []))
            command = [executable, '-p', '--restricted', '--model', model, '--output-format', 'json',
                       '--json-schema', json.dumps(schema), '--system-prompt-file', str(system),
                       '--tools', native, '--allowedTools', 'mcp__cards__*' + (',' + native if native else ''),
                       '--permission-mode', 'dontAsk', '--permission-prompts', 'none', '--max-turns', str(max_turns),
                       '--strict-mcp-config', '--mcp-config', str(mcp), '--setting-sources', '',
                       '--settings', str(settings), '--no-session-persistence']
            data = json.dumps(inputs or {}, ensure_ascii=False).encode()
            if len(data) > 2097152: raise ValueError('Keep the Claude input packet under 2 MB')
            on_start()
            # Files, rather than pipes, bound logs and cannot deadlock on verbose CLI output.
            output = root / 'result.json'; stderr = root / 'stderr.txt'
            # Set file limits in a fresh single-threaded interpreter. preexec_fn
            # is unsafe when Haiku and Terra run from separate host threads.
            command = [sys.executable, '-c', 'import os,resource,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(4194304,4194304));os.execv(sys.argv[1],sys.argv[1:])', *command]
            with output.open('wb') as stdout, stderr.open('wb') as error:
                process = subprocess.Popen(command, cwd=data_root, env=env, stdin=subprocess.PIPE, stdout=stdout,
                                           stderr=error, start_new_session=True)
                try: process.communicate(b'Complete the task using this application-supplied JSON input:\n' + data, timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    raise ResearchUnavailable('timeout', 'Claude reached its phase time limit; saved research is retained') from None
            if errors: raise ResearchUnavailable('lease', 'Claude research lease was interrupted')
            try: result = json.loads(output.read_text())
            except (ValueError, OSError): raise ResearchUnavailable('provider', 'Claude did not return a complete structured result') from None
            usage = {key: result[key] for key in ('usage', 'modelUsage', 'num_turns', 'total_cost_usd') if key in result}
            on_usage(usage)
            if process.returncode or result.get('is_error'):
                # Never relay raw provider output: it may include credentials or private context.
                raise ResearchUnavailable('provider', 'Claude could not complete this phase; check subscription access and usage limits')
            if 'structured_output' not in result:
                raise ResearchUnavailable('provider', 'Claude returned no schema-validated result')
            jsonschema.validate(result['structured_output'], schema)
            return result['structured_output']
    finally:
        if process is not None:
            # Also stop child processes after a normal parent exit, before the tool endpoint closes.
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
        stop.set(); thread.join(timeout=2)
        dashboard.call('auth_release', name='claude', token=lease)
