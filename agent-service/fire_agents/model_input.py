"""Small model views; immutable events and evidence responses keep the full source."""
from .models import Event


def compact_event(event: Event) -> Event:
    platform = event.payload.get('platform')
    if not isinstance(platform, dict):
        return event.model_copy(deep=True)
    # Word timing and the original observation are available through evidence lookup.
    # Sending them again duplicates the transcript/provenance and crowds out sources.
    payload = {k: v for k, v in (platform.get('payload') or {}).items()
               if k not in ('words', 'state_observation')}
    observation = (platform.get('payload') or {}).get('state_observation') or {}
    if isinstance(observation, dict) and observation:
        payload['room_id'] = observation.get('room_id')
        payload['source_device_id'] = observation.get('device_id')
    provenance = platform.get('provenance') or {}
    view = {k: v for k, v in platform.items() if k in (
        'id', 'device_id', 'ts', 'end_ts', 'metric_type', 'value', 'unit',
        'quality', 'availability', 'transcript', 'external_event_id')}
    view['payload'] = payload
    view['provenance'] = {k: v for k, v in provenance.items() if k in (
        'origin', 'source_id', 'source_channel', 'recorded_time', 'state_machine',
        'transformation', 'composition_note', 'independence_group')}
    # model_copy(deep=True) prevents accidental mutation through nested dicts.
    return event.model_copy(update={'payload': {'platform': view}}, deep=True)
