"""Generate the proposed contract and synthetic fixtures; does not change the server."""
from pathlib import Path
import copy
import datetime
import json

OUT = Path(__file__).resolve().parents[1] / 'v0.2'
S = {}
def ref(name): return {'$ref': '#/components/schemas/' + name}
def string(**kw): return {'type': 'string', **kw}
def integer(**kw): return {'type': 'integer', 'minimum': 0, **kw}
def enum(*values): return {'type': 'string', 'enum': list(values)}
def array(item, **kw): return {'type': 'array', 'items': item, **kw}
def nullable(schema): return {'anyOf': [schema, {'type': 'null'}]}
def obj(properties, required=None, **kw):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': True, **kw}
def add(name, props, **kw): S[name] = obj(props, **kw)
ID = string(minLength=1, maxLength=160)
MS = integer(description='Миллисекунды от начала сценария; не Unix time.')
UTC = string(format='date-time', description='RFC 3339, UTC с Z.')
BOOL = {'type': 'boolean'}
VERSION = {'type': 'string', 'const': '0.2'}
AVAILABLE = enum('fresh', 'stale', 'missing', 'invalid', 'disconnected')

add('RecordedTime', {'value': {'type': ['string', 'number', 'null']},
    'unit': enum('rfc3339', 'unix_s', 'relative_s', 'unknown'), 'reference': nullable(string())})
add('Provenance', {'source_id': ID, 'acquisition_id': ID,
    'origin': enum('recorded', 'derived', 'synthetic', 'human_report'),
    'source_file': nullable(string(description='Логический путь относительно источника; не абсолютный путь сервера.')),
    'source_url': nullable(string(format='uri')), 'source_sha256': nullable(string(pattern='^[a-f0-9]{64}$')),
    'source_row': nullable(integer(minimum=1)), 'source_channel': nullable(string()),
    'recorded_time': ref('RecordedTime'), 'transformation': string(), 'time_mapping': string(),
    'independence_group': ID, 'composition_note': nullable(string()),
    'attribution': nullable(string())})
add('Run', {'run_id': ID, 'scenario_id': ID, 'scenario_version': string(),
    'generation': integer(), 'status': enum('paused', 'playing', 'completed', 'error'),
    'sim_time_ms': MS, 'duration_ms': MS, 'speed': {'type': 'number', 'enum': [1, 10, 60]},
    'created_at': UTC, 'expires_at': UTC,
    'links': obj({'snapshot': string(format='uri-reference'), 'stream': string(format='uri-reference'),
                  'commands': string(format='uri-reference')})})
add('Scenario', {'scenario_id': ID, 'name': string(), 'description': string(),
    'scenario_version': string(), 'duration_ms': MS, 'building_id': ID,
    'supported_speeds': array({'type': 'number', 'enum': [1, 10, 60]}),
    'modalities': array(enum('smoke', 'temperature', 'camera', 'access', 'occupancy', 'radio')),
    'composition_note': string()})
add('Capabilities', {'schema_version': VERSION, 'api_version': string(const='v1'),
    'features': obj({'sse': BOOL, 'camera_clips': BOOL, 'radio_audio': BOOL,
                     'source_people_counts': BOOL, 'continuous_media': BOOL,
                     'prerecorded_radio_transcripts': BOOL},
                    required=['sse','camera_clips','radio_audio','source_people_counts','continuous_media']),
    'heartbeat_interval_ms': integer(), 'stream_timeout_ms': integer(),
    'max_page_size': integer(minimum=1), 'event_retention': string()})
add('CreateRun', {'scenario_id': ID, 'speed': {'type': 'number', 'enum': [1, 10, 60], 'default': 1}},
    required=['scenario_id'], additionalProperties=False)
command_base = {'command_id': string(format='uuid'), 'expected_generation': integer()}
commands=[]
for action in ['play', 'pause', 'reset', 'set_speed', 'seek']:
    p={**copy.deepcopy(command_base), 'action': string(const=action)}
    if action=='set_speed': p['speed']={'type':'number','enum':[1,10,60]}
    if action=='seek': p['position_ms']=MS
    commands.append(obj(p, additionalProperties=False))
S['Command']={'oneOf':commands, 'description':'Разные команды — разные command_id. Повтор того же тела с тем же ID возвращает прежний результат.'}
add('CommandResult', {'command_id': string(format='uuid'), 'run_id': ID, 'generation': integer(),
    'applied_sequence': integer(minimum=1), 'status': enum('applied'), 'run': ref('Run')})
add('Reading', {'metric': string(description='Например temperature, obscuration, smoke_detected, co, eco2.'),
    'value': {'type': ['number', 'boolean', 'null']}, 'unit': string(),
    'availability': AVAILABLE, 'observation_id': nullable(ID),
    'observed_sim_time_ms': nullable(MS), 'age_ms': nullable(MS),
    'stale_after_ms': integer(minimum=1)})
add('DeviceState', {'device_id': ID, 'name': string(),
    'kind': enum('temperature_sensor', 'smoke_sensor', 'multisensor', 'camera', 'access_reader', 'people_counter', 'radio_channel'),
    'building_id': ID, 'room_id': nullable(ID), 'floor_id': nullable(ID),
    'position_m': nullable(array({'type':'number'}, minItems=3, maxItems=3)),
    'availability': AVAILABLE,
    'readings': array(ref('Reading')), 'last_observation_id': nullable(ID),
    'last_observed_sim_time_ms': nullable(MS)})
add('RoomState', {'room_id': ID, 'name': string(), 'building_id': ID,
    'floor_id': nullable(ID), 'device_ids': array(ID), 'unavailable_device_ids': array(ID)})
add('CameraState', {'camera_id': ID, 'device_id': ID, 'room_id': nullable(ID),
    'availability': AVAILABLE, 'latest_video_media_id': nullable(ID),
    'latest_frame_media_id': nullable(ID), 'playback_delay_ms': MS})
add('Occupancy', {'scope_id': ID, 'scope_type': enum('building', 'room'),
    'count': nullable(integer()), 'basis': enum('unknown', 'source_count'), 'availability': AVAILABLE,
    'as_of_sim_time_ms': MS, 'observation_id': nullable(ID), 'limitations': array(string())},
    allOf=[{'if':{'properties':{'basis':{'const':'unknown'}}},
        'then':{'properties':{'count':{'type':'null'},'observation_id':{'type':'null'}}}},
        {'if':{'properties':{'basis':{'const':'source_count'}}},
         'then':{'properties':{'observation_id':ID}}}])
add('AccessSummary', {'scope_id': ID, 'window_start_sim_time_ms': MS, 'window_end_sim_time_ms': MS,
    'confirmed_entries': nullable(integer()), 'confirmed_exits': nullable(integer()),
    'availability': AVAILABLE,
    'evidence_ids': array(ID), 'limitations': array(string())})
add('MeasurementData', {'metric': string(), 'value': {'type':['number','boolean','null']},
    'unit': string(), 'quality': enum('valid','missing','invalid')},
    allOf=[{'if':{'properties':{'quality':{'enum':['missing','invalid']}}},
            'then':{'properties':{'value':{'type':'null'}}}}])
add('CameraData', {'camera_id': ID, 'media_id': ID, 'media_kind': enum('image','video'),
    'capture_start_sim_time_ms': MS, 'capture_end_sim_time_ms': MS})
add('AccessData', {'reader_id': ID, 'door_id': nullable(ID),
    'action': enum('badge_presented','access_granted','access_denied','passage_detected','door_opened','door_closed'),
    'direction': enum('enter','exit','unknown'), 'subject_ref': nullable(ID),
    'passage_count': nullable(integer()), 'from_room_id': nullable(ID), 'to_room_id': nullable(ID)})
add('RadioAudioData', {'channel_id': ID, 'media_id': ID, 'chunk_index': integer(),
    'audio_start_sim_time_ms': MS, 'audio_end_sim_time_ms': MS})
add('TranscriptWord', {'text':string(), 'start_sim_time_ms':MS, 'end_sim_time_ms':MS,
    'probability':nullable({'type':'number','minimum':0,'maximum':1})})
add('RadioTranscriptData', {'channel_id':ID, 'stream_id':ID, 'segment_id':ID, 'source_segment_id':ID,
    'language':string(), 'text':string(), 'audio_start_sim_time_ms':MS, 'audio_end_sim_time_ms':MS,
    'full_recording_offset_ms':MS, 'delivery':string(const='prerecorded'),
    'machine_generated':BOOL, 'human_verified':BOOL, 'model':nullable(string()),
    'audio_source_file':string(), 'audio_source_sha256':string(pattern='^[a-f0-9]{64}$'),
    'words':array(ref('TranscriptWord')), 'timing_notes':array(string())},
    description='Готовый текст из пакета, выдаваемый по часам аудио. Сервер не выполняет ASR. Оценка probability — показатель исходной модели, не измеренная точность.')
add('PeopleCountData', {'scope_id': ID, 'scope_type': enum('building', 'room'),
    'count': nullable(integer()), 'unit': string(const='people'),
    'quality': enum('valid','missing','invalid')},
    allOf=[{'if':{'properties':{'quality':{'enum':['missing','invalid']}}},
            'then':{'properties':{'count':{'type':'null'}}}}])
add('ConnectivityData', {'connected': BOOL, 'reason': string()})
obs_base={'evidence_id':ID, 'run_id':ID, 'generation':integer(), 'device_id':ID,
    'room_id':nullable(ID), 'observed_sim_time_ms':MS, 'received_sim_time_ms':MS,
    'received_at':UTC, 'provenance':ref('Provenance')}
observations=[]
observation_mapping={}
for kind,typename in [('measurement','MeasurementData'),('camera','CameraData'),('access','AccessData'),
        ('radio_audio','RadioAudioData'),('radio_transcript','RadioTranscriptData'),('people_count','PeopleCountData'),('connectivity','ConnectivityData')]:
    name='Observation'+''.join(x.title() for x in kind.split('_'))
    add(name,{**copy.deepcopy(obs_base),'kind':string(const=kind),'data':ref(typename)})
    observations.append(ref(name))
    observation_mapping[kind]=ref(name)['$ref']
S['Observation']={'oneOf':observations,'discriminator':{'propertyName':'kind','mapping':observation_mapping}}
add('RadioChannel', {'channel_id':ID, 'device_id':ID, 'name':string(),
    'availability':AVAILABLE, 'latest_audio_media_id':nullable(ID),
    'transcript_delivery':string(const='prerecorded'), 'latest_transcript':nullable(ref('ObservationRadioTranscript'))},
    required=['channel_id','device_id','name','availability','latest_audio_media_id'])
add('SystemHealth', {'status':enum('healthy','degraded','error'),
    'clock':obj({'sim_time_ms':MS,'wall_time':UTC,'processing_lag_ms':MS}),
    'events':obj({'processed':integer(),'observed':integer(),'suppressed':integer(),
                  'transport_controls':integer(),'dropped':integer()}),
    'blender':obj({'status':enum('not_connected','synced','catching_up','disconnected'),
                   'last_ack_at':nullable(UTC),'sim_lag_ms':nullable({'type':'integer'})}),
    'errors':array(obj({'code':string(),'message':string(),'component':string(),'at':UTC}))})
add('Media', {'media_id':ID, 'run_id':ID, 'generation':integer(), 'device_id':ID,
    'kind':enum('image','video','audio'), 'status':enum('ready','failed'),
    'mime_type':string(), 'codec':nullable(string()), 'byte_length':nullable(integer()),
    'sha256':nullable(string(pattern='^[a-f0-9]{64}$')), 'duration_ms':nullable(MS),
    'width':nullable(integer(minimum=1)), 'height':nullable(integer(minimum=1)),
    'sample_rate_hz':nullable(integer(minimum=1)), 'channels':nullable(integer(minimum=1)),
    'capture_start_sim_time_ms':MS, 'capture_end_sim_time_ms':MS,
    'published_sim_time_ms':MS, 'chunk_index':nullable(integer()),
    'content_url':nullable(string(format='uri-reference')),
    'url_expires_at':nullable(UTC), 'supports_range':BOOL,
    'failure_code':nullable(string()), 'provenance':ref('Provenance')},
    allOf=[{'if':{'properties':{'status':{'const':'ready'}}},
            'then':{'properties':{'content_url':{'type':'string','minLength':1},'byte_length':{'type':'integer','minimum':1},'sha256':{'type':'string'}}}},
           {'if':{'properties':{'status':{'const':'failed'}}},
            'then':{'properties':{'content_url':{'type':'null'},'failure_code':{'type':'string','minLength':1}}}}])
add('MediaStream', {'stream_id':ID,'run_id':ID,'generation':integer(),'device_id':ID,
    'kind':enum('video','audio'),'mime_type':enum('video/mp4','audio/mp4'),'codec':string(),
    'framing':string(const='fragmented_mp4'),'capture_start_sim_time_ms':MS,'duration_ms':MS,
    'available_until_sim_time_ms':MS,'status':enum('waiting','streaming','paused','completed'),
    'content_url':string(format='uri-reference'),'url_expires_at':UTC,'provenance':ref('Provenance'),
    'media_timestamp_offset_ms':{'type':'number','minimum':0,'description':'Если задано: source_sim_ms = max(0, encoded_pts_ms - offset). duration/available_until используют часы источника.'}},
    required=['stream_id','run_id','generation','device_id','kind','mime_type','codec','framing','capture_start_sim_time_ms',
        'duration_ms','available_until_sim_time_ms','status','content_url','url_expires_at','provenance'])
add('MediaStreamList', {'items':array(ref('MediaStream'))})
add('Snapshot', {'schema_version':VERSION, 'run':ref('Run'),
    'as_of':obj({'sequence':integer(),'cursor':string()}),
    'devices':array(ref('DeviceState')), 'rooms':array(ref('RoomState')),
    'cameras':array(ref('CameraState')), 'access':array(ref('AccessSummary')),
    'occupancy':array(ref('Occupancy')),
    'radio':obj({'channels':array(ref('RadioChannel'))}), 'system':ref('SystemHealth')})
add('StreamReset', {'reason':enum('reset','seek'), 'snapshot_url':string(format='uri-reference')})
event_types={'run.updated':'Run','observation.created':'Observation','device.updated':'DeviceState',
    'room.updated':'RoomState','camera.updated':'CameraState','access.updated':'AccessSummary',
    'occupancy.updated':'Occupancy','radio.channel.updated':'RadioChannel',
    'system.updated':'SystemHealth',
    'stream.reset':'StreamReset'}
envelopes=[]
event_mapping={}
for kind,name in event_types.items():
    event_name='Event'+''.join(x.title() for x in kind.split('.'))
    add(event_name,{'schema_version':VERSION,'event_id':ID,'run_id':ID,'generation':integer(),
        'sequence':integer(minimum=1),'cursor':string(),'kind':string(const=kind),
        'sim_time_ms':MS,'emitted_at':UTC,'data':ref(name)})
    envelopes.append(ref(event_name));event_mapping[kind]=ref(event_name)['$ref']
S['Event']={'oneOf':envelopes,'discriminator':{'propertyName':'kind','mapping':event_mapping}}
add('Heartbeat', {'run_id':ID,'generation':integer(),'last_sequence':integer(),
    'sim_time_ms':MS,'server_time':UTC})
add('Error', {'error':obj({'code':string(),'message':string(),'request_id':ID,'retryable':BOOL,
    'details':obj({'snapshot_url':string(format='uri-reference'),
                   'current_generation':integer(),'retry_after_ms':integer()},required=[])})})
add('Health',{'status':enum('ok','unavailable'),'schema_version':VERSION})
for name,item in [('ScenarioList','Scenario'),('DeviceList','DeviceState'),('CameraList','CameraState'),
                  ('OccupancyList','Occupancy'),('AccessList','AccessSummary')]:add(name,{'items':array(ref(item))})
for name,item in [('ObservationPage','Observation')]:
    add(name,{'items':array(ref(item)),'next_cursor':nullable(string()),'generation':integer(),
              'as_of_sequence':integer()})

def response(schema,description='Успешный ответ'):
    return {'description':description,'content':{'application/json':{'schema':ref(schema)}}}
def param(name,where='path',schema=ID,required=True,description=''):
    return {'name':name,'in':where,'required':required,'schema':schema,'description':description}
errors={str(c):{'$ref':'#/components/responses/Error'} for c in [400,401,403,404,409,410,422,429,503]}
error_response=response('Error','Структурированная ошибка; для 429 присутствует Retry-After.')
error_response['headers']={
    'X-Request-ID':{'schema':string(),'description':'Идентификатор запроса из error.request_id.'},
    'Retry-After':{'schema':string(),'description':'Обязателен для 429: число секунд или HTTP-date.'}}
paths={}
def endpoint(path,method,operation,summary,schema,body=None,parameters=None,code='200',description=''):
    op={'operationId':operation,'summary':summary,'description':description,
        'responses':{code:response(schema),**copy.deepcopy(errors)}}
    if body:op['requestBody']={'required':True,'content':{'application/json':{'schema':ref(body)}}}
    op['parameters']=[param(p) for p in re.findall(r'\{([^}]+)\}',path)]+(parameters or [])
    if not op['parameters']:del op['parameters']
    paths.setdefault(path,{})[method]=op

import re
endpoint('/health','get','getHealth','Доступность сервиса','Health');paths['/health']['get']['security']=[]
endpoint('/capabilities','get','getCapabilities','Поддерживаемые функции сервера','Capabilities')
endpoint('/scenarios','get','listScenarios','Сценарии без будущих наблюдений','ScenarioList')
endpoint('/runs','post','createRun','Создать изолированный запуск на паузе','Run','CreateRun',
    parameters=[param('Idempotency-Key','header',string(format='uuid'))],code='201')
endpoint('/runs/{run_id}','get','getRun','Часы и управление выбранным запуском','Run')
endpoint('/runs/{run_id}/commands','post','applyCommand','Play, pause, reset, speed, seek','CommandResult','Command',
    description='Атомарная команда; дедупликация command_id раньше проверки expected_generation. После reset/seek generation увеличивается.')
endpoint('/runs/{run_id}/snapshot','get','getSnapshot','Полный текущий наблюдаемый снимок','Snapshot')
for path,schema,operation,summary in [
    ('devices','DeviceList','listDevices','Текущие приборы'),('cameras','CameraList','listCameras','Камеры и последние media ID'),
    ('occupancy','OccupancyList','getOccupancy','Число людей только по прямому значению источника'),
    ('access','AccessList','getAccess','Счётчики зарегистрированных проходов'),
    ('system','SystemHealth','getSystem','Техническое состояние конвейера')]:
    endpoint('/runs/{run_id}/'+path,'get',operation,summary,schema)
gen=param('generation','query',integer(),True,'Поколение из текущего снимка; старое поколение даёт 409.')
endpoint('/runs/{run_id}/devices/{device_id}','get','getDevice','Карточка устройства','DeviceState',parameters=[gen])
pagination=[gen,param('cursor','query',string(),False),param('limit','query',integer(minimum=1,maximum=500,default=100),False)]
endpoint('/runs/{run_id}/observations','get','listObservations','История наблюдений для графиков и журнала','ObservationPage',
    parameters=pagination+[param('device_id','query',ID,False),param('from_ms','query',MS,False),param('to_ms','query',MS,False)])
endpoint('/runs/{run_id}/evidence/{evidence_id}','get','getEvidence','Неизменяемое исходное наблюдение','Observation',parameters=[gen])
endpoint('/runs/{run_id}/media/{media_id}','get','getMedia','Описание медиа и обновляемая ссылка загрузки','Media',parameters=[gen])
endpoint('/runs/{run_id}/media-streams','get','listMediaStreams','Непрерывные HTTP-потоки камер и радио','MediaStreamList')
endpoint('/runs/{run_id}/media-streams/{stream_id}/content','get','streamMediaContent','Один HTTP-ответ: init + fMP4-фрагменты по часам run','MediaStream',parameters=[gen])
paths['/runs/{run_id}/media-streams/{stream_id}/content']['get']['security']=[{'bearerAuth':[]},{'mediaTicket':[]}]
paths['/runs/{run_id}/media-streams/{stream_id}/content']['get']['responses']['200']={
    'description':'Потоковый fragmented MP4 без Content-Length/Range. Новые фрагменты пишет сервер после Play; Pause останавливает выдачу. EOF при конце записи/reset/seek/потере канала.',
    'headers':{'Accept-Ranges':{'schema':string(const='none')},'X-Media-Framing':{'schema':string(const='fragmented-mp4')}},
    'content':{mime:{'schema':{'type':'string','format':'binary'}} for mime in ['video/mp4','audio/mp4']}}
endpoint('/runs/{run_id}/stream','get','streamEvents','SSE: снимок, события и heartbeat','Event',parameters=[
    param('Last-Event-ID','header',string(),False,'Курсор последнего полностью применённого события.'),
    param('after','query',string(),False,'Курсор для fetch-клиента; нельзя вместе с Last-Event-ID.')])
paths['/runs/{run_id}/stream']['get']['responses']['200']={'description':'Долгое SSE-соединение. Без курсора первый кадр snapshot; с курсором — журнал после него.',
    'headers':{'Cache-Control':{'schema':string(),'description':'no-cache, no-transform'},'X-Accel-Buffering':{'schema':string(),'description':'no'}},
    'content':{'text/event-stream':{'schema':string()}},
    'x-sse-events':{'snapshot':ref('Snapshot'),'event':ref('Event'),'heartbeat':ref('Heartbeat'),'stream_error':ref('Error')}}
content_path='/runs/{run_id}/media/{media_id}/content'
content_response={'description':'Бинарное содержимое только уже опубликованного фрагмента.',
    'headers':{k:{'schema':string()} for k in ['Content-Type','Content-Length','Accept-Ranges','Content-Range','ETag']},
    'content':{mime:{'schema':{'type':'string','format':'binary'}} for mime in ['video/mp4','audio/mpeg','audio/wav','audio/ogg','image/jpeg','image/png']}}
for method in ['get','head']:
    paths.setdefault(content_path,{})[method]={'operationId':'getMediaBytes' if method=='get' else 'headMediaBytes',
        'summary':'Загрузка видео/аудио/кадра' if method=='get' else 'Заголовки медиа без тела',
        'security':[{'bearerAuth':[]},{'mediaTicket':[]}],
        'parameters':[param('run_id'),param('media_id'),gen,
            param('Range','header',string(),False,'Один byte range; неверный/множественный — 416.'),
            param('If-Range','header',string(),False,'ETag; при несовпадении возвращается полный 200.')],
        'responses':{'200':copy.deepcopy(content_response),'206':copy.deepcopy(content_response),
                      '416':copy.deepcopy(error_response),**copy.deepcopy(errors)}}
    paths[content_path][method]['responses']['416']['headers']['Content-Range']={
        'schema':string(),'description':'bytes */<length>, полный размер ресурса в байтах.'}
    if method=='head':
        paths[content_path][method]['parameters']=[param('run_id'),param('media_id'),gen]
        paths[content_path][method]['responses'].pop('206')
        paths[content_path][method]['responses'].pop('416')
        for code,item in paths[content_path][method]['responses'].items():
            if '$ref' in item:item=copy.deepcopy(error_response)
            item.pop('content',None)
            paths[content_path][method]['responses'][code]=item

spec={'openapi':'3.1.1','info':{'title':'Fire Safety State Machine — передача сырых данных',
    'version':'0.2.2','description':'Исходные наблюдения и готовая расшифровка из пакета через SSE, непрерывные HTTP-медиа. Сервер не выполняет распознавание и анализ. Контракт от 12 сентября 2026. Файлы examples синтетические.'},
    'servers':[{'url':'/api/v1','description':'Сервер State Machine; доступ к данным по токену приложения.'}],
    'security':[{'bearerAuth':[]}],'paths':paths,
    'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','description':'Токен приложения, выдаваемый отдельно. Не Cloudflare/Hetzner/1Password token.'},
        'mediaTicket':{'type':'apiKey','in':'query','name':'ticket','description':'Краткоживущий ticket из content_url, ограниченный run/generation/media; только GET/HEAD.'}},
        'responses':{'Error':error_response},'schemas':S}}

def write(name,data):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
write('openapi.json',spec)

RUN='run-demo-001';TIME='2026-09-12T10:30:00Z';GEN=0
def wall(t):return (datetime.datetime.fromisoformat(TIME.replace('Z','+00:00'))+datetime.timedelta(milliseconds=t)).isoformat().replace('+00:00','Z')
base='/api/v1/runs/'+RUN
run={'run_id':RUN,'scenario_id':'contract-demo','scenario_version':'fixture-v1','generation':GEN,
    'status':'paused','sim_time_ms':0,'duration_ms':600000,'speed':1,
    'created_at':TIME,'expires_at':'2026-09-13T10:30:00Z',
    'links':{'snapshot':base+'/snapshot','stream':base+'/stream','commands':base+'/commands'}}
def provenance(source,origin='synthetic'):
    return {'source_id':source,'acquisition_id':'fixture-session-001','origin':origin,
        'source_file':None,'source_url':None,'source_sha256':None,'source_row':None,'source_channel':None,
        'recorded_time':{'value':None,'unit':'unknown','reference':None},
        'transformation':'Синтетический пример контракта; не запись реального инцидента.',
        'time_mapping':'Фикстура: время задано непосредственно в миллисекундах сценария.',
        'independence_group':source,'composition_note':'Полностью вымышленные данные для разработки UI.',
        'attribution':None}
def observation(id,kind,device,t,data,source='fixture-sensors',room='server'):
    return {'evidence_id':id,'run_id':RUN,'generation':GEN,'device_id':device,'room_id':room,
        'observed_sim_time_ms':t,'received_sim_time_ms':t,'received_at':wall(t),
        'provenance':provenance(source),'kind':kind,'data':data}
def device(id,kind,metric=None,unit=''):
    readings=[] if metric is None else [{'metric':metric,'value':None,'unit':unit,'availability':'missing',
        'observation_id':None,'observed_sim_time_ms':None,'age_ms':None,'stale_after_ms':5000}]
    return {'device_id':id,'name':id,'kind':kind,'building_id':'office-demo','room_id':'server','floor_id':'floor-1',
        'position_m':None,'availability':'missing','readings':readings,
        'last_observation_id':None,'last_observed_sim_time_ms':None}
devices=[device('TMP-SRV','temperature_sensor','temperature','degC'),device('SMK-SRV','smoke_sensor','obscuration','%/ft'),
         device('CAM-SRV','camera'),device('ACCESS','access_reader'),device('RADIO-A','radio_channel')]
camera={'camera_id':'CAM-SRV','device_id':'CAM-SRV','room_id':'server','availability':'missing',
    'latest_video_media_id':None,'latest_frame_media_id':None,'playback_delay_ms':2000}
occupancy={'scope_id':'office-demo','scope_type':'building','count':None,'basis':'unknown','availability':'missing','as_of_sim_time_ms':0,'observation_id':None,
    'limitations':['Нет подтверждённых данных о присутствии людей.']}
access={'scope_id':'office-demo','window_start_sim_time_ms':0,'window_end_sim_time_ms':0,
    'confirmed_entries':None,'confirmed_exits':None,'availability':'missing',
    'evidence_ids':[],'limitations':['Нет данных о зарегистрированных проходах.']}
channel={'channel_id':'RADIO-A','device_id':'RADIO-A','name':'Учебный канал A','availability':'missing',
    'latest_audio_media_id':None}
room={'room_id':'server','name':'Серверная / учебная зона','building_id':'office-demo','floor_id':'floor-1',
    'device_ids':[d['device_id'] for d in devices],
    'unavailable_device_ids':[d['device_id'] for d in devices]}
health={'status':'healthy','clock':{'sim_time_ms':0,'wall_time':TIME,'processing_lag_ms':0},
    'events':{'processed':0,'observed':0,'suppressed':0,'transport_controls':0,'dropped':0},
    'blender':{'status':'not_connected','last_ack_at':None,'sim_lag_ms':None},'errors':[]}
initial={'schema_version':'0.2','run':run,'as_of':{'sequence':0,'cursor':RUN+':0'},'devices':devices,'rooms':[room],
    'cameras':[camera],'access':[access],'occupancy':[occupancy],
    'radio':{'channels':[channel]},'system':health}
write('examples/snapshot.initial.json',initial)
events=[]
def event(kind,data,t):
    seq=len(events)+1
    e={'schema_version':'0.2','event_id':'evt-demo-'+str(seq),'run_id':RUN,'generation':GEN,'sequence':seq,
        'cursor':RUN+':'+str(seq),'kind':kind,'sim_time_ms':t,'emitted_at':wall(t),'data':copy.deepcopy(data)}
    events.append(e);return seq
playing=copy.deepcopy(run);playing['status']='playing';event('run.updated',playing,0)
temp=observation('ev-temp-1','measurement','TMP-SRV',1000,{'metric':'temperature','value':42.2,'unit':'degC','quality':'valid'})
smoke=observation('ev-smoke-1','measurement','SMK-SRV',1000,{'metric':'obscuration','value':11.017,'unit':'%/ft','quality':'valid'})
for obs,idx in [(temp,0),(smoke,1)]:
    event('observation.created',obs,1000)
    d=copy.deepcopy(devices[idx]);d.update(availability='fresh',last_observation_id=obs['evidence_id'],last_observed_sim_time_ms=1000)
    d['readings'][0].update(value=obs['data']['value'],availability='fresh',observation_id=obs['evidence_id'],observed_sim_time_ms=1000,age_ms=0)
    event('device.updated',d,1000)
cam_obs=observation('ev-camera-1','camera','CAM-SRV',2000,{'camera_id':'CAM-SRV','media_id':'media-camera-001',
    'media_kind':'video','capture_start_sim_time_ms':0,'capture_end_sim_time_ms':2000},'fixture-camera')
event('observation.created',cam_obs,2000)
cam_device=copy.deepcopy(devices[2]);cam_device.update(availability='fresh',last_observation_id=cam_obs['evidence_id'],last_observed_sim_time_ms=2000);event('device.updated',cam_device,2000)
camera_new=copy.deepcopy(camera);camera_new.update(availability='fresh',latest_video_media_id='media-camera-001');event('camera.updated',camera_new,2000)
audio=observation('ev-radio-audio-1','radio_audio','RADIO-A',2000,{'channel_id':'RADIO-A','media_id':'media-radio-001','chunk_index':0,
    'audio_start_sim_time_ms':0,'audio_end_sim_time_ms':2000},'fixture-radio')
event('observation.created',audio,2000)
radio_device=copy.deepcopy(devices[4]);radio_device.update(availability='fresh',last_observation_id=audio['evidence_id'],last_observed_sim_time_ms=2000);event('device.updated',radio_device,2000)
channel_new=copy.deepcopy(channel);channel_new.update(availability='fresh',latest_audio_media_id='media-radio-001')
event('radio.channel.updated',channel_new,2000)
badge=observation('ev-access-1','access','ACCESS',2500,{'reader_id':'ACCESS','door_id':'door-server','action':'access_granted',
    'direction':'enter','subject_ref':'badge-demo-01','passage_count':None,'from_room_id':None,'to_room_id':'server'},'fixture-access')
event('observation.created',badge,2500)
access_device=copy.deepcopy(devices[3]);access_device.update(availability='fresh',last_observation_id=badge['evidence_id'],last_observed_sim_time_ms=2500);event('device.updated',access_device,2500)
access_new=copy.deepcopy(access);access_new.update(window_end_sim_time_ms=2500,availability='fresh',evidence_ids=['ev-access-1']);event('access.updated',access_new,2500)
occ_new=copy.deepcopy(occupancy);occ_new.update(as_of_sim_time_ms=2500,limitations=['Разрешение прохода не доказывает проход или присутствие.']);event('occupancy.updated',occ_new,2500)
room_new=copy.deepcopy(room);room_new['unavailable_device_ids']=[];event('room.updated',room_new,2500)
loss=observation('ev-offline-1','connectivity','SMK-SRV',4000,{'connected':False,'reason':'synthetic_power_loss'},'fixture-power')
event('observation.created',loss,4000)
disconnected=copy.deepcopy(events[4]['data']);disconnected.update(availability='disconnected',last_observation_id=loss['evidence_id'],last_observed_sim_time_ms=4000);disconnected['readings'][0].update(availability='disconnected',age_ms=3000)
event('device.updated',disconnected,4000)
temp_device=copy.deepcopy(events[2]['data']);temp_device['readings'][0]['age_ms']=3000;event('device.updated',temp_device,4000)
room_new['unavailable_device_ids']=['SMK-SRV'];event('room.updated',room_new,4000)
health_new=copy.deepcopy(health);health_new['status']='degraded';health_new['clock'].update(sim_time_ms=4000,wall_time=wall(4000))
health_new['events'].update(processed=6,observed=6);event('system.updated',health_new,4000)
paused=copy.deepcopy(run);paused['sim_time_ms']=4000;event('run.updated',paused,4000)
write('examples/events.json',events)

final_snapshot=copy.deepcopy(initial)
def upsert(items,value,key):
    for i,old in enumerate(items):
        if old[key]==value[key]:items[i]=copy.deepcopy(value);return
    items.append(copy.deepcopy(value))
for e in events:
    k,d=e['kind'],e['data']
    if k=='run.updated':final_snapshot['run']=copy.deepcopy(d)
    elif k=='device.updated':upsert(final_snapshot['devices'],d,'device_id')
    elif k=='room.updated':upsert(final_snapshot['rooms'],d,'room_id')
    elif k=='camera.updated':upsert(final_snapshot['cameras'],d,'camera_id')
    elif k=='access.updated':upsert(final_snapshot['access'],d,'scope_id')
    elif k=='occupancy.updated':upsert(final_snapshot['occupancy'],d,'scope_id')
    elif k=='radio.channel.updated':upsert(final_snapshot['radio']['channels'],d,'channel_id')
    elif k=='system.updated':final_snapshot['system']=copy.deepcopy(d)
    final_snapshot['as_of']={'sequence':e['sequence'],'cursor':e['cursor']}
write('examples/snapshot.after-play.json',final_snapshot)
def media(id,kind,device_id,mime,codec,source):
    return {'media_id':id,'run_id':RUN,'generation':GEN,'device_id':device_id,'kind':kind,'status':'ready',
        'mime_type':mime,'codec':codec,'byte_length':4096,'sha256':'0'*64,'duration_ms':2000,
        'width':1280 if kind=='video' else None,'height':720 if kind=='video' else None,
        'sample_rate_hz':16000 if kind=='audio' else None,'channels':1 if kind=='audio' else None,
        'capture_start_sim_time_ms':0,'capture_end_sim_time_ms':2000,'published_sim_time_ms':2000,'chunk_index':0,
        'content_url':base+'/media/'+id+'/content?generation=0&ticket=MOCK_NOT_A_REAL_TICKET',
        'url_expires_at':'2026-09-12T10:32:00Z','supports_range':True,'failure_code':None,'provenance':provenance(source)}
write('examples/media.video.json',media('media-camera-001','video','CAM-SRV','video/mp4','avc1.42E01E','fixture-camera'))
write('examples/media.audio.json',media('media-radio-001','audio','RADIO-A','audio/mpeg','mp3','fixture-radio'))
write('examples/media-streams.json',{'items':[{'stream_id':sid,'run_id':RUN,'generation':0,'device_id':sid,
    'kind':kind,'mime_type':mime,'codec':codec,'framing':'fragmented_mp4','capture_start_sim_time_ms':0,
    'duration_ms':duration,'available_until_sim_time_ms':0,'status':'paused',
    'content_url':base+'/media-streams/'+sid+'/content?generation=0&ticket=MOCK_NOT_A_REAL_TICKET',
    'url_expires_at':'2026-09-12T10:32:00Z','provenance':provenance('fixture-stream')}
    for sid,kind,mime,codec,duration in [('CAM-SRV','video','video/mp4','h264',30000),('RADIO-A','audio','audio/mp4','aac',60047)]]})
people=observation('ev-people-example','people_count','COUNTER-DEMO',2500,
    {'scope_id':'office-demo','scope_type':'building','count':12,'unit':'people','quality':'valid'},
    'fixture-people-counter',room=None)
write('examples/observation.people-count.json',people)
text_sample=observation('ev-radio-text-1','radio_transcript','RADIO-A',1800,
    {'channel_id':'RADIO-A','stream_id':'RADIO-A','segment_id':'fixture-0001','source_segment_id':'1',
     'language':'en','text':'Test radio message.','audio_start_sim_time_ms':500,'audio_end_sim_time_ms':1800,
     'full_recording_offset_ms':0,'delivery':'prerecorded','machine_generated':True,'human_verified':False,
     'model':'fixture-model','audio_source_file':'fixture/audio.wav','audio_source_sha256':'0'*64,
     'words':[],'timing_notes':[]},'fixture-transcript',room=None)
text_sample.update(received_sim_time_ms=2000,received_at=wall(2000))
write('examples/observation.radio-transcript.json',text_sample)
write('examples/occupancy.source-count.json',{'scope_id':'office-demo','scope_type':'building',
    'count':12,'basis':'source_count','availability':'fresh','as_of_sim_time_ms':2500,
    'observation_id':people['evidence_id'],'limitations':['Значение вымышленного источника; State Machine не проверяет фактическое присутствие.']})
write('examples/create-run.request.json',{'scenario_id':'contract-demo','speed':1})
write('examples/create-run.response.json',run)
write('examples/play.request.json',{'command_id':'569f86c0-3555-4f0a-9b9f-539258dcb570','expected_generation':0,'action':'play'})
write('examples/play.response.json',{'command_id':'569f86c0-3555-4f0a-9b9f-539258dcb570','run_id':RUN,'generation':0,'applied_sequence':1,'status':'applied','run':playing})
heartbeat={'run_id':RUN,'generation':0,'last_sequence':len(events),'sim_time_ms':4000,'server_time':wall(5000)}
write('examples/heartbeat.json',heartbeat)
write('examples/error.cursor-expired.json',{'error':{'code':'CURSOR_EXPIRED','message':'Получите новый снимок.','request_id':'req-demo-1','retryable':False,'details':{'snapshot_url':base+'/snapshot'}}})
reset_event={'schema_version':'0.2','event_id':'evt-demo-reset','run_id':RUN,'generation':1,'sequence':len(events)+1,
    'cursor':RUN+':'+str(len(events)+1),'kind':'stream.reset','sim_time_ms':0,'emitted_at':wall(6000),
    'data':{'reason':'reset','snapshot_url':base+'/snapshot'}}
write('examples/event.reset.json',reset_event)
frame=lambda event,data,cursor=None: ('id: '+cursor+'\n' if cursor else '')+'event: '+event+'\ndata: '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n\n'
sse='retry: 2000\n\n'+frame('snapshot',initial,initial['as_of']['cursor'])+''.join(frame('event',e,e['cursor']) for e in events)
sse+=frame('heartbeat',heartbeat)
(OUT/'examples/stream.sse').write_text(sse)
manifest={'synthetic':True,'description':'Вымышленные JSON/SSE для команды UI, без реальных аудио, видео и секретов.',
    'examples':{'snapshot.initial.json':'Snapshot','snapshot.after-play.json':'Snapshot','media.video.json':'Media','media.audio.json':'Media',
        'create-run.request.json':'CreateRun','create-run.response.json':'Run','play.request.json':'Command','play.response.json':'CommandResult',
        'heartbeat.json':'Heartbeat','error.cursor-expired.json':'Error','event.reset.json':'Event',
        'observation.people-count.json':'Observation','observation.radio-transcript.json':'Observation',
        'occupancy.source-count.json':'Occupancy','media-streams.json':'MediaStreamList'},'events_file':'events.json','event_schema':'Event'}
write('examples/manifest.json',manifest)
print(f'Generated {len(S)} schemas, {len(paths)} paths, {len(events)} events in {OUT}')
