import pytest
from fire_agents.engines import SDKEngine
from agents import OpenAIChatCompletionsModel


def test_openrouter_requires_its_own_key(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openrouter')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-be-used')
    with pytest.raises(ValueError, match='OPENROUTER_API_KEY'):
        SDKEngine('openai/gpt-5.6-sol')


def test_openrouter_configures_both_agents(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only')
    engine = SDKEngine('openai/gpt-5.6-sol')
    assert isinstance(engine.extractor.model, OpenAIChatCompletionsModel)
    assert engine.extractor.model is engine.responder.model
    assert engine.extractor.model.model == 'openai/gpt-5.6-sol'


def test_unknown_provider_fails(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'typo')
    with pytest.raises(ValueError, match='FIRE_PROVIDER'):
        SDKEngine('example')
