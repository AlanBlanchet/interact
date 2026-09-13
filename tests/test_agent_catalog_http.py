"""Public consumer against an explicitly supplied account-server executable.

Run with INTERACT_TEST_ACCOUNT_CLI=/path/to/interact-account. Uses only fresh
SQLite/Git files, synthetic keys, and a loopback process owned by this test.
"""

import json
import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, UTC
import httpx
import pytest
from interact_core import AgentRevision, AgentRevisionRef, PromptExecutionRef, PromptRevision


@pytest.mark.skipif(not os.environ.get("INTERACT_TEST_ACCOUNT_CLI"), reason="set INTERACT_TEST_ACCOUNT_CLI to exercise the real HTTP boundary")
def test_real_server_two_revisions_cli_sync_and_cache_recreation(tmp_path):
    public = Path(__file__).resolve().parents[1]
    root = tmp_path
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = {'PATH': os.defpath, 'HOME': str(root), 'TMPDIR': str(root), 'PYTHONDONTWRITEBYTECODE': '1',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'PYTHONPATH': os.pathsep.join(filter(None, (os.environ.get('PYTHONPATH'), str(public / 'packages/interact-local/src')))),
           'INTERACT_CSRF_SECRET_HEX': 'ab' * 32, 'INTERACT_MAIL_KEY_HEX': 'cd' * 32,
           'OLLAMA_DISCOVERY': '0', 'BENCHMARK_SCORES': ''}
    with (root / 'server.log').open('w+') as log:
        process = subprocess.Popen([os.environ['INTERACT_TEST_ACCOUNT_CLI'],
            '--database', str(root / 'accounts.sqlite3'), '--prompt-database', str(root / 'prompts.sqlite3'),
            '--prompt-authoring-root', str(root / 'authoring'), '--workflow-storage', str(root / 'artifacts'),
            '--origin', origin, '--port', str(port), '--smtp-host', '127.0.0.1', '--smtp-port', '9',
            '--mail-sender', 'fixture@example.test', '--local-http', '--local-preview', '--no-outbox-worker', '--migrate'],
            env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=origin, trust_env=False, timeout=5) as client:
                for _ in range(100):
                    try:
                        if client.get('/health').status_code == 200:
                            break
                    except httpx.ConnectError:
                        time.sleep(.05)
                else:
                    raise RuntimeError('server did not become healthy')
                bootstrap = client.post('/v1/auth/local-preview', headers={'Origin': origin})
                bootstrap.raise_for_status()
                data = bootstrap.json()
                base = f'/v1/workspaces/{data["current_workspace_id"]}'
                headers = {'Origin': origin, 'X-CSRF-Token': data['csrf_token']}
                agent = None
                prompt = None
                original_agent = None
                cursors = []
                for version in (1, 2):
                    content = f'Fixture instructions revision {version}'
                    if prompt is None:
                        response = client.post(base + '/prompts', headers=headers, json={
                            'key': {'namespace': 'fixture', 'slug': 'instructions'},
                            'name': 'Fixture instructions', 'content': content})
                    else:
                        proposed = PromptRevision.model_validate({
                            **prompt, 'revision': str(uuid4()), 'content': content,
                            'parent_digest': prompt['digest'], 'digest': hashlib.sha256(content.encode()).hexdigest(),
                        })
                        response = client.put(base + '/prompts/fixture/instructions', headers=headers,
                                              json=proposed.model_dump(mode='json'))
                    response.raise_for_status()
                    prompt = response.json()
                    revised = AgentRevision(id=agent.id if agent else uuid4(), revision=uuid4(),
                        parent_revision=agent.revision if agent else None, role_key='fixture-worker', name='Fixture worker',
                        prompt=PromptExecutionRef(key=prompt['key'], channel='stable', digest=prompt['digest'], revision=prompt['revision']),
                        criteria=f'price.in >= {version}', reasoning='high' if version == 1 else 'low',
                        harness_tools=('Read',) if version == 1 else ('Write',), resources=(), created_at=datetime.now(UTC))
                    saved = client.post(base + '/agents', headers=headers, json=revised.model_dump(mode='json'))
                    saved.raise_for_status()
                    agent = revised
                    if original_agent is None:
                        original_agent = revised
                    command = [str(Path(sys.executable).with_name('interact')), 'agents', 'sync']
                    if version == 1:
                        command += ['--endpoint', origin, '--preview']
                    result = subprocess.run(command, env=env, cwd=public, capture_output=True, text=True, timeout=15)
                    if result.returncode:
                        raise RuntimeError(result.stderr)
                    summary = json.loads(result.stdout)
                    cursors.append(summary['cursor'])
                    cached = json.loads((root / '.interact/agent-catalog-cache.json').read_text())
                    assert cached['snapshot']['agents'][0]['reasoning'] == revised.reasoning
                    definitions = subprocess.run([str(Path(sys.executable).with_name('interact')), 'agents', 'definitions', 'codex'], env=env, cwd=public, capture_output=True, text=True, timeout=15)
                    assert definitions.returncode == 0, definitions.stderr
                    assert definitions.stdout.strip() == 'fixture-worker'
                assert cursors[0] != cursors[1]
                lead = AgentRevision(
                    id=uuid4(), revision=uuid4(), role_key='fixture-lead', name='Fixture lead',
                    prompt=agent.prompt, criteria='price.in >= 0', resources=(), created_at=datetime.now(UTC),
                    capabilities=({'kind': 'delegate', 'name': 'ask_worker', 'description': 'Ask the fixture worker',
                                   'agent': {'id': original_agent.id, 'revision': original_agent.revision},
                                   'input_schema': {'properties': {}, 'required': ()}},),
                )
                client.post(base + '/agents', headers=headers, json=lead.model_dump(mode='json')).raise_for_status()
                advanced_lead = lead.model_copy(update={
                    'revision': uuid4(), 'parent_revision': lead.revision,
                    'capabilities': (lead.capabilities[0].model_copy(update={
                        'agent': AgentRevisionRef(id=agent.id, revision=agent.revision),
                    }),),
                })
                client.post(base + '/agents', headers=headers, json=advanced_lead.model_dump(mode='json')).raise_for_status()
                (root / '.interact/agent-catalog-cache.json').unlink()
                rebuilt = subprocess.run(command, env=env, cwd=public, capture_output=True, text=True, timeout=15)
                assert rebuilt.returncode == 0, rebuilt.stderr
                current = client.get(base + '/agent-catalog').json()
                assert json.loads(rebuilt.stdout)['cursor'] == current['cursor']
                assert all(value['digest'] != original_agent.prompt.digest for value in current['paradigms'])
                consumer = subprocess.run([sys.executable, '-c', PINNED_CONSUMER,
                    str(lead.id), str(lead.revision), str(original_agent.id), str(original_agent.revision)],
                    env=env, cwd=public, capture_output=True, text=True, timeout=45)
                assert consumer.returncode == 0, consumer.stderr
                proof = json.loads(consumer.stdout)
                assert proof == {'pinned_launches': 3, 'latest_launches': 1, 'continuations': 1, 'head_cache_preserved': True}
                print(json.dumps({'real_backend': 'PASS', 'cli_sync_revisions': 2, 'cache_recreated': True,
                                  'vendor': 'disposable subprocess', **proof}))
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.seek(0)
            diagnostics = log.read()
            if diagnostics:
                print(diagnostics)


PINNED_CONSUMER = '''
import asyncio, json, sys
from pathlib import Path
from unittest.mock import patch
from interact_core import AgentRevisionRef
from interact.agents.catalog import AgentCatalog
from interact.agents import registry as reg
from interact.agents.providers import CodexProvider
from interact.agents.run import run_agent, launch_continuation

lead = AgentRevisionRef(id=sys.argv[1], revision=sys.argv[2])
worker = AgentRevisionRef(id=sys.argv[3], revision=sys.argv[4])
parent = reg.register(run_id="fixture-parent", pid=None, provider="codex", name="Fixture parent",
                      agent="fixture-lead", agent_ref=lead, cwd=str(Path.cwd()))
before = AgentCatalog.model_validate_json(AgentCatalog.cache_path().read_bytes()).snapshot
commands = []
build = CodexProvider.command

def command(self, task, **kwargs):
    build(self, task, **kwargs)
    commands.append((task, kwargs))
    return [sys.executable, "-c", "print('{}')"]

def resume(self, session_id, task, **kwargs):
    return command(self, task, cwd=str(Path.cwd()), mcp_config=None, run_id="fixture-resume", **kwargs)

async def main():
    saved = None
    for options in (
        {"agent": "fixture-worker", "parent_run_id": parent.run_id},
        {"delegate": "ask_worker", "parent_run_id": parent.run_id},
        {"agent_ref": worker},
    ):
        handle = await run_agent(CodexProvider(), "Bounded fixture task", cwd=str(Path.cwd()), mesh=False, **options)
        await asyncio.wait_for(handle.wait(), 10)
        saved = reg.get_run(handle.run_id)
        assert saved.agent_ref == worker
        assert saved.model == "fixture-model-1" and saved.reasoning == "high"
        assert "Fixture instructions revision 1" in commands[-1][0]
        assert "Fixture instructions revision 2" not in commands[-1][0]
        assert commands[-1][1]["allowed_tools"] == ["Read"]
    continuation = launch_continuation(CodexProvider(), saved, "fixture-session", "Continue fixture task",
        model="wrong-head-model", criterion="price.in >= 2", reasoning="low", raw_index=0)
    assert continuation.wait() == 0
    assert "Fixture instructions revision 1" in commands[-1][0]
    assert commands[-1][1]["model"] == "fixture-model-1"
    handle = await run_agent(CodexProvider(), "Current fixture task", cwd=str(Path.cwd()), mesh=False, agent="fixture-worker")
    await asyncio.wait_for(handle.wait(), 10)
    assert reg.get_run(handle.run_id).agent_ref != worker
    assert "Fixture instructions revision 2" in commands[-1][0]
    assert commands[-1][1]["allowed_tools"] == ["Write"]
    assert AgentCatalog.model_validate_json(AgentCatalog.cache_path().read_bytes()).snapshot == before
    print(json.dumps({"pinned_launches": 3, "latest_launches": 1, "continuations": 1, "head_cache_preserved": True}))

with patch.object(CodexProvider, "available", return_value=True), patch.object(CodexProvider, "command", command), patch.object(CodexProvider, "resume_command", resume), patch("interact.agents.run.resolve_model", lambda rule, env, **kwargs: ({}, "fixture-model-" + rule.rsplit(" ", 1)[-1])):
    asyncio.run(main())
'''
