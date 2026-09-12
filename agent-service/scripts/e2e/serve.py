import os,pathlib,sys
root=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'agent-service'))
(root/'agent-service/work/e2e').mkdir(parents=True,exist_ok=True)
settings=dict(l.split('=',1) for l in (root/'platform/.env').read_text().splitlines() if '=' in l)
os.environ.update(FIRE_PLATFORM_URL='http://127.0.0.1:8000/mcp-server/mcp',FIRE_PLATFORM_API_KEY=settings['API_KEY'],FIRE_PLATFORM_SCOPE=(root/'agent-service/work/e2e/scope.json').read_text(),FIRE_DB_PATH=str(root/'agent-service/work/e2e/agent-openrouter.sqlite3'),FIRE_ENGINE='sdk',FIRE_PROVIDER='openrouter',FIRE_MODEL=settings.get('FIRE_MODEL','openai/gpt-5.6-sol'),OPENROUTER_API_KEY=settings.get('OPENROUTER_API_KEY',''),OPENAI_AGENTS_DISABLE_TRACING='1')
import uvicorn
uvicorn.run('fire_agents.api:create_app',factory=True,host='127.0.0.1',port=8011)
