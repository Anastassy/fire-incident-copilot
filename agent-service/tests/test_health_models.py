import json

import pytest
from fastapi.testclient import TestClient

from fire_agents.api import create_app
from fire_agents.engines import FixtureEngine, SDKEngine


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    monkeypatch.delenv('FIRE_PLATFORM_SCOPE', raising=False)
    monkeypatch.setenv('FIRE_ENGINE', 'sdk')
    monkeypatch.setenv('FIRE_PROVIDER', 'openai')
    monkeypatch.setenv('FIRE_MODEL', 'environment-model-not-selected')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'HEALTH-MUST-NOT-EXPOSE-THIS-SECRET')


def test_fixture_health_does_not_advertise_configured_sdk(tmp_path):
    app = create_app(tmp_path / 'fixture.db', FixtureEngine(), background=False)
    with TestClient(app) as client:
        response = client.get('/health')
    assert response.status_code == 200
    health = response.json()
    assert health['engine'] == 'FixtureEngine'
    assert health['status'] == 'ok'
    assert 'model_configuration' not in health
    assert 'HEALTH-MUST-NOT-EXPOSE-THIS-SECRET' not in response.text


@pytest.mark.parametrize('fallback', ['anthropic/claude-fable-5.1', None])
def test_sdk_health_uses_only_selected_engine_metadata(tmp_path, fallback):
    # Build only the metadata surface: this health check must never invoke a model.
    engine = object.__new__(SDKEngine)
    engine.provider = 'openrouter'
    engine.primary_model = 'openai/gpt-6-astra'
    engine.fallback_model = fallback
    engine.private_client = {'api_key': 'HEALTH-MUST-NOT-EXPOSE-THIS-SECRET'}
    app = create_app(tmp_path / 'sdk.db', engine, background=False)
    with TestClient(app) as client:
        response = client.get('/health')
    assert response.status_code == 200
    health = response.json()
    assert health['engine'] == 'SDKEngine'
    assert health['model_configuration'] == {
        'provider': 'openrouter',
        'primary_model': 'openai/gpt-6-astra',
        'fallback_model': fallback,
    }
    assert 'HEALTH-MUST-NOT-EXPOSE-THIS-SECRET' not in json.dumps(health)
    assert 'environment-model-not-selected' not in response.text
