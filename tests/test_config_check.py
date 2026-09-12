"""interact config set → 'it works' verdict.

When a user persists a model key or a model pin, the CLI must not stop at
"saved" — it must run that exact credential / model against a real vision call
and print whether it works. A wrong key saved silently sits in config.env until
the first real screenshot fails deep inside a vendor error; the set site is the
one place the user is watching the answer.
"""

import pytest

from interact.cli import config_check
from interact.config.user import UserConfig


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(UserConfig, "PATH", tmp_path / "config.env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config_check.ConfigCheck.reset()
    yield
    config_check.ConfigCheck.reset()


class _Result:
    def __init__(self, text="a tiny image", model="openai/gpt-4o"):
        self.text = text
        self.model = model
        self.elapsed = 0.1


async def _ok(*args, **kwargs):
    return _Result()


async def _bad(*args, **kwargs):
    raise RuntimeError("invalid api key")


@pytest.fixture
def _probe_openai(monkeypatch):
    """Route the probe resolver at an openai model whatever the criterion says."""
    monkeypatch.setattr(config_check.ConfigCheck, "_criterion_for", classmethod(
        lambda cls, env: "openai/gpt-4o" if env == "OPENAI_API_KEY" else None))


@pytest.mark.anyio
async def test_set_key_reports_works(monkeypatch, _probe_openai):
    monkeypatch.setattr(config_check.ConfigCheck, "_analyze", classmethod(
        lambda cls, model, what: _ok()))
    verdict = await config_check.ConfigCheck.key("OPENAI_API_KEY")
    assert verdict.ok
    assert "gpt-4o" in verdict.model


@pytest.mark.anyio
async def test_set_key_reports_failure_with_reason(monkeypatch, _probe_openai):
    monkeypatch.setattr(config_check.ConfigCheck, "_analyze", classmethod(
        lambda cls, model, what: _bad()))
    verdict = await config_check.ConfigCheck.key("OPENAI_API_KEY")
    assert not verdict.ok
    assert "invalid api key" in verdict.detail


@pytest.mark.anyio
async def test_unknown_provider_key_no_probe():
    verdict = await config_check.ConfigCheck.key("COHERE_API_KEY")
    assert not verdict.ok
    assert "no probe model" in verdict.detail


def test_non_media_setting_skips_probe(capsys):
    """`config set desktop.target nested` must not fire a model call."""
    from interact.cli.app_commands import config_set

    config_set("desktop.target", "nested")
    out = capsys.readouterr().out
    assert "works" not in out.lower()


def test_set_value_breaking_shell_sourcing_warns(capsys):
    """A value that breaks when config.env is SOURCED must be caught at set time.

    Real failure: `INTERACT_MEDIA_CRITERIA=cap.vlm and aa.intelligence >= 40`
    was written unquoted; every `source ~/.interact/config.env` then ran `and`
    as a command, and nothing ever said so. The set site is where the user is
    watching — the warning belongs there.
    """
    from interact.cli.app_commands import config_set

    config_set("media.criteria", "cap.vlm and aa.intelligence >= 40")
    out = capsys.readouterr().out
    assert "sources" in out.lower() or "shell" in out.lower() or "quote" in out.lower()


def test_written_file_sources_cleanly(capsys):
    """Whatever config set writes, `bash -c 'source file'` must exit 0."""
    import subprocess
    from interact.cli.app_commands import config_set

    config_set("media.criteria", "cap.vlm and aa.intelligence >= 40")
    proc = subprocess.run(
        ["bash", "-c", f"source {UserConfig.PATH} && echo ok"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_quoted_value_reads_back_unquoted(tmp_path, monkeypatch):
    """Write side quotes shell-hostile values; read side must strip them again.

    Real failure: after the quoting fix, the criteria value round-tripped as
    `'cap.vlm and …'` WITH quotes, and the next criterion parse failed on the
    leading quote. The file is one store with two readers (python, bash) — the
    pair must compose.
    """
    from interact.cli.app_commands import config_set

    config_set("media.criteria", "cap.vlm and aa.intelligence >= 40")
    assert UserConfig.get("media.criteria") == "cap.vlm and aa.intelligence >= 40"
    # Raw file holds the quoted form for bash's sake.
    raw = UserConfig.PATH.read_text()
    assert "INTERACT_MEDIA_CRITERIA='cap.vlm and aa.intelligence >= 40'" in raw


def test_probe_resolves_through_criterion(monkeypatch):
    """The probe target comes from the user's own media.criteria resolver,
    restricted to the provider owning the key — never a literal table."""
    from interact.criteria import Criteria
    from interact.models import Model

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    Model.load_registry()
    # The user's configured criterion, restricted to openai, must name an
    # openai model — proving the probe reads the same resolver as every other
    # selection surface. WHICH openai model is thrift's business, not this
    # test's; the resolver's provider restriction is the contract here.
    resolved = config_check.ConfigCheck._criterion_for("OPENAI_API_KEY")
    assert resolved is not None
    bare = resolved.split("/", 1)[-1]
    assert Model.from_litellm_id(resolved).provider == "openai" or bare.startswith("gpt")
