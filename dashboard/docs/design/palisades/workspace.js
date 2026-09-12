/* Operator workspace. All scenario classification belongs to adapters, never this view. */
(function () {
  const $ = id => document.getElementById(id);
  const ports = window.PalisadesAdapters || window.createPalisadesAdapters(window.PalisadesFixtures);
  const stamp = n => `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(Math.floor(n % 60)).padStart(2, '0')}`;
  let state, check, lastReady, answer, clip, feedKey = '', questionToken = 0, mediaToken = 0;
  const button = (label, handler) => { const b = document.createElement('button'); b.textContent = label; b.onclick = handler; return b; };
  function cancelQuestion() { questionToken++; $('askSubmit').disabled = false; $('cancelAsk').hidden = true; }
  function clearContext() {
    cancelQuestion(); mediaToken++; $('audio').pause(); clip = answer = lastReady = check = null; feedKey = '';
    ['evidence', 'log', 'brief'].forEach(id => $(id).close());
    $('answerArea').hidden = $('askPanel').hidden = true; $('askToggle').setAttribute('aria-expanded','false'); $('search').value = '';
  }
  function renderData(next) {
    if (state && next.generation !== state.generation) clearContext();
    state = next;
    $('clock').textContent = stamp(state.time); $('modeBadge').textContent = state.omitReply ? 'CONTROL RUN · REPLY OMITTED · MOCK AGENT' : 'PROTOTYPE · SIMULATED AGENT';
    $('published').textContent = `${state.records.length} published`;
    $('play').textContent = state.playing ? 'Pause replay' : state.ended ? 'Replay complete' : 'Start / resume';
    $('play').disabled = state.ended; $('quickPlay').disabled = state.ended; $('quickPlay').textContent = $('play').textContent;
    $('playStatus').textContent = `${state.playing ? 'Playing 1×' : state.ended ? 'End of excerpt' : 'Paused'} · ${state.omitReply ? 'CONTROL: reply omitted' : 'transcript replay · audio on demand'}`;
    $('progress').style.width = Math.max(0, Math.min(100, (state.time - state.startTime) / (state.endTime - state.startTime) * 100)) + '%';
    renderFeed();
    if ($('log').open) renderLog();
    if (answer && state.time > answer.asOf + .1) $('answerScope').textContent = `Answer at ${stamp(answer.asOf)} · newer input may be available. Ask again.`;
    if ($('brief').open && answer && state.time > answer.asOf + .1) $('briefScope').textContent = `Draft at ${stamp(answer.asOf)} · review against newer input.`;
  }
  function renderFeed() {
    const ids = new Set($('copilot').hidden ? [] : lastReady?.evidenceIds || []);
    const key = state.records.map(r => r.id).join('|') + ':' + [...ids].join('|');
    if (key === feedKey) return;
    feedKey = key; const feed = $('feed'); feed.replaceChildren();
    state.records.slice(-5).forEach(r => {
      const row = document.createElement('article'); row.className = 'radio-record' + (ids.has(r.id) ? ' linked' : '');
      const meta = document.createElement('div'); meta.className = 'record-meta';
      const time = document.createElement('span'); time.className = 'mono'; time.textContent = stamp(r.start) + (ids.has(r.id) ? ' · Linked by Copilot' : ' · Radio');
      meta.append(time, button('Listen', () => openEvidence(r.id)));
      const text = document.createElement('p'); text.textContent = r.text; row.append(meta, text); feed.append(row);
    });
    feed.scrollTop = feed.scrollHeight;
  }
  function renderCheck(next) {
    if (!state || next.generation !== state.generation) return;
    if (check && next.revision != null && check.revision != null && next.revision < check.revision) return;
    check = next; if (next.status === 'ready') lastReady = next;
    const view = lastReady || next;
    const copies = {
      request: ['Waiting for a reply', 'A radio channel was requested. No answer found in the published excerpt.', 'Listen to the request'],
      answered: ['Channel assigned. Reply not found yet.', `The assignment names ${view.channel || 'a channel'}. Copilot is following the exchange.`, 'Listen to the assignment'],
      acknowledged: ['A confirming reply was found.', 'The reply repeats the assigned channel. Verify it in the original audio.', 'Listen to the reply']
    };
    const copy = copies[view.stage] || ['Not established', 'No supported finding in the available data.', 'Review source evidence'];
    $('headline').textContent = !lastReady && next.status === 'checking' ? 'Checking the exchange' : copy[0]; $('finding').textContent = !lastReady && next.status === 'checking' ? 'Reading the published messages.' : copy[1];
    $('checkState').textContent = next.status === 'checking' ? 'Checking new input…' : next.status === 'error' ? 'Check failed' : 'Check updated';
    $('assessmentLabel').textContent = next.status === 'error' ? 'LAST FINDING · CHECK FAILED' : next.status === 'checking' && lastReady ? 'LAST FINDING · RECHECKING' : 'COPILOT FINDING';
    if (next.status === 'error') $('finding').textContent = 'The latest check failed. Source messages remain available; retry in Demo checks below.';
    $('assessment').className = 'assessment' + (next.status === 'error' ? ' failed' : view.stage === 'acknowledged' ? ' confirmed' : '');
    renderExchange(view.exchange || []);
    const ids = view.evidenceIds || [], latest = ids.at(-1);
    $('listen').textContent = copy[2]; $('listen').disabled = !latest;
    $('listen').onclick = () => latest && openEvidence(latest);
    $('nextAction').textContent = view.stage === 'acknowledged' ? 'Verify the reply, then brief command.' : 'Check the source. Keep following the exchange.';
    $('coverage').textContent = `${ids.length} linked ${ids.length === 1 ? 'message' : 'messages'} · checked through ${stamp(view.asOf)} · one recorded channel`;
    $('trace').textContent = `${next.origin === 'scripted_mock' ? 'SIMULATED' : 'ADAPTER'} check · revision ${next.revision || 0} · ${next.status} · ${next.queries?.[0]?.count ?? '—'} published records inspected`;
    renderFeed();
  }
  function renderExchange(exchange) {
    $('exchange').replaceChildren();
    const defs = [['request', 'Request', 'Which radio channel?'], ['assignment', 'Assignment', 'No answer found yet'], ['reply', 'Reply', 'No confirming reply found']];
    defs.forEach(([role, label, empty], index) => {
      const entry = exchange.find(e => e.role === role); let record;
      try { if (entry) record = ports.data.getRecord(entry.evidenceId); } catch { /* Missing evidence must remain missing. */ }
      const step = document.createElement('article'); step.className = 'step' + (record ? ' found' : '');
      const number = document.createElement('span'); number.className = 'step-number'; number.textContent = `${index + 1} · ${record ? 'FOUND' : !lastReady && check?.status === 'checking' ? 'CHECKING' : 'NOT FOUND'}`;
      const title = document.createElement('h4'); title.textContent = label;
      const text = document.createElement('p'); text.textContent = !lastReady && check?.status === 'checking' ? 'Checking available evidence' : record ? role === 'assignment' ? (lastReady?.channel || 'Channel named') : role === 'reply' ? 'Channel repeated back' : 'Channel requested' : empty;
      step.append(number, title, text);
      if (record) step.append(button(`▶ ${stamp(record.start)} · Audio`, () => openEvidence(record.id)));
      $('exchange').append(step);
    });
  }
  function renderRefs(el, ids) {
    el.replaceChildren();
    ids.forEach(id => { try { const r = ports.data.getRecord(id); el.append(button(`Source ${stamp(r.start)}`, () => openEvidence(id))); } catch { el.append('Source unavailable'); } });
  }
  async function openEvidence(id) {
    const token = ++mediaToken, generation = state.generation; ports.replay.pause(); $('audio').pause();
    try {
      const result = await ports.media.resolve(id);
      if (token !== mediaToken || generation !== state.generation || result.generation !== state.generation) return;
      clip = result; $('eTitle').textContent = `Radio at ${stamp(clip.start)}`; $('quote').textContent = clip.record.text;
      $('range').textContent = `Focus ${clip.start.toFixed(3)}–${clip.end.toFixed(3)} sec`;
      $('raw').textContent = JSON.stringify(clip.record, null, 2); $('audio').src = clip.url; $('audioStatus').textContent = '';
      $('evidence').showModal(); playClip();
    } catch { if (token === mediaToken) { $('checkState').textContent = 'Source audio unavailable'; } }
  }
  async function playClip() {
    if (!clip) return; const token = mediaToken;
    try {
      const audio = $('audio'); $('audioStatus').textContent = 'Loading source audio…';
      if (audio.readyState < 1) await new Promise((resolve, reject) => {
        const done = () => { cleanup(); resolve(); }, failed = () => { cleanup(); reject(new Error('MEDIA_UNAVAILABLE')); };
        const timer = setTimeout(failed, 10000);
        function cleanup() { clearTimeout(timer); audio.removeEventListener('loadedmetadata', done); audio.removeEventListener('error', failed); }
        audio.addEventListener('loadedmetadata', done); audio.addEventListener('error', failed);
      });
      if (token !== mediaToken || !clip) return;
      audio.currentTime = clip.start;
      await audio.play();
      if (token === mediaToken) $('audioStatus').textContent = 'Playing original audio…'; else audio.pause();
    }
    catch { if (token === mediaToken) $('audioStatus').textContent = 'Playback unavailable. Retry or inspect the source text.'; }
  }
  $('audio').addEventListener('timeupdate', () => { if (clip && $('audio').currentTime >= clip.end) { $('audio').pause(); $('audioStatus').textContent = 'End of source interval'; } });
  $('evidence').addEventListener('close', () => { mediaToken++; $('audio').pause(); });
  $('playClip').onclick = playClip;
  function renderLog() {
    const rows = ports.data.history($('search').value); $('fullLog').replaceChildren();
    $('logScope').textContent = `${rows.length} matching / ${state.records.length} published · through ${stamp(state.time)} · one channel`;
    rows.forEach(r => { const row = document.createElement('article'); row.className = 'log-row'; const text = document.createElement('p'); text.textContent = r.text; row.append(button(`Listen · ${stamp(r.start)}`, () => openEvidence(r.id)), text); $('fullLog').append(row); });
    if (!rows.length) $('fullLog').textContent = 'No matching published messages.';
  }
  $('logButton').onclick = () => { renderLog(); $('log').showModal(); }; $('search').oninput = renderLog;
  $('play').onclick = () => state.playing ? ports.replay.pause() : ports.replay.play();
  $('quickPlay').onclick = () => $('play').click();
  $('reset').onclick = () => ports.replay.reset({ omitReply: false });
  $('missing').onclick = () => { ports.replay.reset({ omitReply: true }); ports.replay.play(); };
  $('failure').onclick = () => ports.agent.simulateError(); $('retry').onclick = () => ports.agent.retry();
  function compare(hide) { $('copilot').hidden = hide; $('comparison').hidden = !hide; $('compare').textContent = hide ? 'Show Copilot' : 'Hide Copilot'; $('compare').setAttribute('aria-pressed', String(hide)); feedKey = ''; renderFeed(); }
  $('compare').onclick = () => compare(!$('copilot').hidden); $('restore').onclick = () => compare(false);
  $('askToggle').onclick = () => { $('askPanel').hidden = !$('askPanel').hidden; $('askToggle').setAttribute('aria-expanded',String(!$('askPanel').hidden)); if (!$('askPanel').hidden) $('question').focus(); };
  async function ask(question) {
    cancelQuestion(); answer = null; const token = questionToken, generation = state.generation;
    $('askPanel').hidden = $('answerArea').hidden = false; $('askToggle').setAttribute('aria-expanded','true'); $('answerText').textContent = 'Checking the published history…'; $('answerRefs').replaceChildren();
    $('answerScope').textContent = ''; $('briefButton').hidden = true; $('askSubmit').disabled = true; $('cancelAsk').hidden = false;
    try { const result = await ports.agent.ask(question); if (token !== questionToken || generation !== state.generation || result.generation !== state.generation) return;
      answer = result; $('answerText').textContent = result.text; renderRefs($('answerRefs'), result.evidenceIds);
      $('answerScope').textContent = `${stamp(result.asOf)} · ${result.origin === 'scripted_mock' ? 'simulated answer' : 'agent answer'}`; $('briefButton').hidden = false;
    } catch { if (token === questionToken) $('answerText').textContent = 'Question failed. Failure is not evidence of a missing reply.'; }
    finally { if (token === questionToken) { $('askSubmit').disabled = false; $('cancelAsk').hidden = true; } }
  }
  $('askAll').onclick = () => ask('Did everyone switch channels?');
  $('askForm').onsubmit = e => { e.preventDefault(); if ($('question').value.trim()) ask($('question').value); };
  $('cancelAsk').onclick = () => { cancelQuestion(); $('answerText').textContent = 'Question cancelled.'; };
  $('briefButton').onclick = () => { if (!answer) return; $('briefText').textContent = answer.text; $('briefScope').textContent = `Draft at ${stamp(answer.asOf)} · verify source audio`; $('copyStatus').textContent = ''; $('brief').showModal(); };
  $('copy').onclick = async () => { try { await navigator.clipboard.writeText($('briefText').textContent); $('copyStatus').textContent = 'Copied. Nothing transmitted.'; } catch { $('copyStatus').textContent = 'Select and copy the draft text.'; } };
  document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => $(b.dataset.close).close());
  ports.data.subscribe(renderData); ports.agent.subscribe(renderCheck);
  window.addEventListener('beforeunload', () => ports.replay.dispose());
})();
