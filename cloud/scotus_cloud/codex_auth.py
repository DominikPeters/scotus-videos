"""Credential round-trip for a dedicated, private, data-only Codex worker.

No public checkout is passed to Codex and no API billing fallback is allowed.
Seed with a separate cloud sign-in, not the desktop's actively used auth stream.
"""

import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import subprocess
import tempfile
import threading

from .control import validate_secret


def _validated_inputs(inputs):
    """Only application-supplied data paths, separate from auth and CLI outputs."""
    files = {}
    for name, content in (inputs or {}).items():
        if not isinstance(name, str):
            raise ValueError('Codex input paths must be strings')
        path = PurePosixPath(name)
        if (str(path) != name or path.is_absolute() or
                any(part in ('.', '..') or part.startswith('.') for part in path.parts) or
                not (name == 'POLICY.md' or name.startswith('input/'))):
            raise ValueError('Use POLICY.md or a relative input/ data path')
        if isinstance(content, str):
            content = content.encode('utf-8')
        if not isinstance(content, bytes):
            raise ValueError('Codex inputs must contain text or bytes, not file paths')
        if len(content) > 2 * 1024 * 1024:
            raise ValueError('Codex input exceeds the small text-file limit')
        files[name] = content
    if len(files) > 16 or sum(map(len, files.values())) > 4 * 1024 * 1024:
        raise ValueError('Codex input bundle is too large')
    for name in files:
        if any(str(parent) in files for parent in PurePosixPath(name).parents):
            raise ValueError('Codex input file conflicts with a directory')
    return files


def run_codex(dashboard, cloud, secret_name, prompt, schema, model=None, *, inputs=None,
              timeout_seconds=900, images=None, tools=None, tool_handler=None, subagent_model=None):
    if os.environ.get('SCOTUS_PRIVATE_CODEX_WORKER') != '1':
        raise RuntimeError('Enable only in the dedicated private Codex worker')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 900:
        raise ValueError('Codex turns need a bounded timeout of at most 900 seconds')
    files = _validated_inputs(inputs)
    if bool(tools)!=bool(tool_handler) or (tools and images):
        raise ValueError('Supply paired private tool definitions/handler; image turns use the CLI')
    images=list(images or [])
    if len(images)>4 or any(name not in files or not name.endswith(('.jpg','.png','.webp')) for name in images):
        raise ValueError('Attach only image files in the validated private input bundle')
    token = dashboard.call('auth_claim', name='codex')
    if not token:
        raise RuntimeError('Codex credential is already in use')
    stop, errors = threading.Event(), []

    def renew():
        while not stop.wait(30):
            try: dashboard.call('auth_check', name='codex', token=token)
            except Exception as error: errors.append(error); break

    thread = threading.Thread(target=renew, daemon=True); thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='private-codex-') as folder:
            root = Path(folder); home, data = root / 'auth', root / 'data'
            home.mkdir(mode=0o700); data.mkdir(mode=0o700)
            original = cloud.secret(secret_name)
            validate_secret('codex', json.loads(original))
            auth = home / 'auth.json'; auth.write_bytes(original); auth.chmod(0o600)
            config='cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n'
            if subagent_model:
                if subagent_model!='gpt-6-luna':raise ValueError('Use the configured Luna research model')
                config+='[agents]\ndefault_subagent_model = "gpt-6-luna"\nmax_concurrent_threads_per_session = 2\n'
            (home / 'config.toml').write_text(config)
            (data / 'schema.json').write_text(json.dumps(schema))
            for name, content in files.items():
                target = data / name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target.write_bytes(content); target.chmod(0o600)
            env = dict(os.environ); env['CODEX_HOME'] = str(home)
            env.pop('OPENAI_API_KEY', None); env.pop('CODEX_API_KEY', None);env.pop('CODEX_ACCESS_TOKEN',None)
            command = ['codex', '--search', 'exec', '--skip-git-repo-check', '--sandbox', 'read-only',
                       '--ephemeral', '--output-schema', str(data / 'schema.json'),
                       '--output-last-message', str(data / 'result.json')]
            if model: command.extend(['--model', model])
            for name in images:command.extend(['--image',str(data/name)])
            command.extend(['--',prompt])
            try:
                if tools:
                    import asyncio
                    from .codex_tools import run_with_tools
                    result=asyncio.run(run_with_tools(data,env,prompt,schema,model,tools,tool_handler,timeout_seconds,agents=bool(subagent_model)))
                    (data/'result.json').write_text(json.dumps(result))
                else:
                    subprocess.run(command, cwd=data, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, check=True, timeout=timeout_seconds)
            finally:
                if errors: raise RuntimeError('Codex credential lease was lost')
                updated = auth.read_bytes()
                if updated != original:
                    dashboard.call('auth_check', name='codex', token=token)
                    cloud.add_secret_version(secret_name, updated)
            return json.loads((data / 'result.json').read_text())
    finally:
        stop.set(); thread.join(timeout=5)
        dashboard.call('auth_release', name='codex', token=token)
