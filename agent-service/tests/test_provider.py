import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fire_agents.engines import ModelFallbackError, SDKEngine
from fire_agents.models import Answer, Claim, Event, Extraction
from agents import OpenAIChatCompletionsModel, Runner
from agents.exceptions import ModelBehaviorError
from openai import APIStatusError


@pytest.fixture(autouse=True)
def isolated_model_config(monkeypatch):
    monkeypatch.delenv('FIRE_FALLBACK_MODEL', raising=False)
    monkeypatch.delenv('FIRE_OUTPUT_LANGUAGE', raising=False)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only')
    monkeypatch.setenv('FIRE_FALLBACK_MODEL', 'anthropic/fallback-test-model')
    return SDKEngine('openai/primary-test-model')


@pytest.fixture
def event():
    return Event(session_id='demo', generation=0, event_id='reading-1', time_ms=1000,
                 source_id='radio-1', kind='radio', description='Demo Group requests a working channel.')


def api_failure(message='provider response must not reach the UI'):
    return APIStatusError(message, response=httpx.Response(503, request=httpx.Request('POST', 'https://example.test')),
                          body={'detail': message})


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
    assert engine.fallback_extractor is None
    assert engine.fallback_responder is None


def test_fallback_uses_same_contract_and_router_settings(engine):
    assert engine.provider == 'openrouter'
    assert engine.primary_model == 'openai/primary-test-model'
    assert engine.fallback_model == 'anthropic/fallback-test-model'
    assert engine.fallback_extractor.output_type is Extraction
    assert engine.fallback_responder.output_type is Answer
    assert engine.fallback_extractor.instructions == engine.extractor.instructions
    assert engine.fallback_responder.instructions == engine.responder.instructions
    assert engine.fallback_extractor.model is engine.fallback_responder.model
    assert engine.fallback_extractor.model.model == engine.fallback_model
    assert engine.extractor.model_settings.extra_body == {
        'reasoning': {'effort': 'low'}, 'provider': {'require_parameters': True},
    }
    assert engine.extractor.model_settings.temperature is None
    assert engine.attempt_timeout == 14
    assert 'Output English claim text.' in engine.extractor.instructions


def test_extractor_language_is_configurable(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openai')
    monkeypatch.setenv('FIRE_OUTPUT_LANGUAGE', 'ru')
    assert 'Output Russian claim text.' in SDKEngine('test-model').extractor.instructions
    monkeypatch.setenv('FIRE_OUTPUT_LANGUAGE', 'unknown')
    with pytest.raises(ValueError, match='FIRE_OUTPUT_LANGUAGE'):
        SDKEngine('test-model')


def test_identical_fallback_does_not_repeat_model(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'openai')
    monkeypatch.setenv('FIRE_FALLBACK_MODEL', 'test-model')
    configured = SDKEngine('test-model')
    assert configured.fallback_model is None
    assert configured.attempt_timeout == 28


def test_unknown_provider_fails(monkeypatch):
    monkeypatch.setenv('FIRE_PROVIDER', 'typo')
    with pytest.raises(ValueError, match='FIRE_PROVIDER'):
        SDKEngine('example')


@pytest.mark.parametrize('method', ['extract', 'extract_with_context', 'answer'])
def test_primary_success_never_calls_fallback(engine, event, monkeypatch, method):
    expected = Answer(claims=[Claim(text='A channel was requested.', evidence_ids=[event.event_id])]) if method == 'answer' else Extraction(action='none')
    run = AsyncMock(return_value=SimpleNamespace(final_output=expected))
    monkeypatch.setattr(Runner, 'run', run)
    if method == 'answer':
        result = asyncio.run(engine.answer('What was requested?', [event], language='en'))
        assert json.loads(run.call_args.args[1])['language'] == 'en'
    elif method == 'extract_with_context':
        result = asyncio.run(engine.extract_with_context(event, [event]))
        payload = json.loads(run.call_args.args[1])
        assert payload['current_event']['event_id'] == event.event_id
        assert payload['recent_context'][0]['event_id'] == event.event_id
    else:
        result = asyncio.run(engine.extract(event))
    assert result is expected
    assert run.await_count == 1
    assert run.call_args.kwargs['max_turns'] == 3


@pytest.mark.parametrize('failure', [api_failure(), TimeoutError(), ModelBehaviorError('invalid JSON')])
def test_recoverable_failure_uses_fallback_with_identical_input(engine, event, monkeypatch, failure):
    expected = Extraction(action='channel_requested', claim=Claim(text=event.description, evidence_ids=[event.event_id]))
    run = AsyncMock(side_effect=[failure, SimpleNamespace(final_output=expected)])
    monkeypatch.setattr(Runner, 'run', run)
    assert asyncio.run(engine.extract_with_context(event, [event])) is expected
    calls = run.await_args_list
    assert calls[0].args[0] is engine.extractor
    assert calls[1].args[0] is engine.fallback_extractor
    assert calls[0].args[1] == calls[1].args[1]
    assert len(calls) == 2


def test_invalid_structured_output_uses_fallback_and_validates_answer(engine, event, monkeypatch):
    run = AsyncMock(side_effect=[SimpleNamespace(final_output='unstructured prose'),
                                SimpleNamespace(final_output={'claims': [{'text': 'Reported request.', 'evidence_ids': [event.event_id]}], 'limitations': []})])
    monkeypatch.setattr(Runner, 'run', run)
    result = asyncio.run(engine.answer('What is known?', [event], language='en'))
    assert isinstance(result, Answer)
    assert result.claims[0].evidence_ids == [event.event_id]
    assert run.await_args_list[1].args[0] is engine.fallback_responder


def test_both_failures_remain_diagnostic_without_provider_body(engine, event, monkeypatch):
    first, second = api_failure('secret-response-primary'), api_failure('secret-response-fallback')
    run = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(Runner, 'run', run)
    with pytest.raises(ModelFallbackError) as caught:
        asyncio.run(engine.extract(event))
    assert caught.value.primary_error is first
    assert caught.value.fallback_error is second
    assert caught.value.__cause__ is second
    assert 'openai/primary-test-model' in str(caught.value)
    assert 'anthropic/fallback-test-model' in str(caught.value)
    assert 'secret-response' not in str(caught.value)
    assert run.await_count == 2


def test_invalid_fallback_output_is_not_returned(engine, event, monkeypatch):
    monkeypatch.setattr(Runner, 'run', AsyncMock(side_effect=[api_failure(), SimpleNamespace(final_output={'action': 'invented'})]))
    with pytest.raises(ModelFallbackError, match='ValidationError'):
        asyncio.run(engine.extract(event))


def test_timeout_cancels_primary_before_fallback(engine, event, monkeypatch):
    engine.attempt_timeout = 0.01
    completed_cancellation = []

    async def run(candidate, data, **kwargs):
        if candidate is engine.extractor:
            try:
                await asyncio.Event().wait()
            finally:
                completed_cancellation.append(True)
        assert completed_cancellation == [True]
        return SimpleNamespace(final_output=Extraction(action='none'))

    mocked = AsyncMock(side_effect=run)
    monkeypatch.setattr(Runner, 'run', mocked)
    assert asyncio.run(engine.extract(event)).action == 'none'
    assert mocked.await_count == 2


def test_user_cancellation_never_starts_fallback(engine, event, monkeypatch):
    async def scenario():
        entered = asyncio.Event()
        async def run(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        mocked = AsyncMock(side_effect=run)
        monkeypatch.setattr(Runner, 'run', mocked)
        task = asyncio.create_task(engine.answer('What is known?', [event], language='en'))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert mocked.await_count == 1
    asyncio.run(scenario())


def test_programming_error_does_not_trigger_fallback(engine, event, monkeypatch):
    mocked = AsyncMock(side_effect=RuntimeError('unexpected local error'))
    monkeypatch.setattr(Runner, 'run', mocked)
    with pytest.raises(RuntimeError, match='unexpected local error'):
        asyncio.run(engine.extract(event))
    assert mocked.await_count == 1


def test_unconfigured_fallback_preserves_original_failure(monkeypatch, event):
    monkeypatch.setenv('FIRE_PROVIDER', 'openai')
    configured = SDKEngine('test-model')
    failure = api_failure()
    mocked = AsyncMock(side_effect=failure)
    monkeypatch.setattr(Runner, 'run', mocked)
    with pytest.raises(APIStatusError) as caught:
        asyncio.run(configured.extract(event))
    assert caught.value is failure
    assert mocked.await_count == 1
