"""Explicit mapping boundary. No assumptions about the eventual description payload."""
from .models import Event

def from_platform(reading:dict, *, session_id:str, generation:int, scenario_time_ms:int,
                  description:str='', media_url:str|None=None) -> Event:
    metric=reading['metric_type']
    return Event(session_id=session_id,generation=generation,event_id=str(reading['id']),
        time_ms=scenario_time_ms, source_id=reading['device_id'],
        kind='radio' if metric=='radio_audio' or (reading.get('payload') or {}).get('kind')=='radio_transcript' else 'system' if metric=='system' else 'sensor',
        description=description, media_url=media_url, reading_id=reading['id'],
        payload={'platform':reading})
