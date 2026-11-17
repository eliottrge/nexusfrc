// nexusfrc UI: tabs, analysis jobs, match page, teams/coach, settings + calibration.
let current = null;      // open match id
let robotsData = null;

// ---------------------------------------------------------------- tabs (#analyze, #match/<id>, #teams/<n>, #settings)
function show(view) {
  document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== 'v-' + view);
  document.querySelectorAll('nav [role=tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === view)));
}
document.querySelectorAll('nav [role=tab]').forEach(b => b.addEventListener('click', () => {
  location.hash = b.dataset.view === 'match' && current ? 'match/' + current : b.dataset.view;
}));
async function route() {
  const [view, arg] = (location.hash.slice(1) || 'analyze').split('/');
  show(['analyze', 'match', 'teams', 'settings'].includes(view) ? view : 'analyze');
  if (view === 'match' && arg && arg !== current) await openMatch(arg);
  if (view === 'teams') await loadTeams(arg ? +arg : null);
  if (view === 'settings') await loadSettings();
  if (view === 'analyze') await loadMatches();
}
addEventListener('hashchange', route);

// ---------------------------------------------------------------- analyze
function showError(msg) { $('#error').hidden = !msg; $('#error').textContent = msg || ''; }

async function startJob(body) {
  showError(''); $('#go').disabled = true;
  try {
    const job = await api('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    $('#job').hidden = false;
    let j;
    for (;;) {
      j = await api('/api/jobs/' + job.id);
      $('#bar').style.width = Math.round(j.progress * 100) + '%';
      $('#stage').textContent = `${j.title ? j.title + ': ' : ''}${j.stage}... ${j.elapsed}s`;
      if (j.status === 'error') throw new Error(j.error);
      if (j.status === 'done') break;
      await new Promise(r => setTimeout(r, 1000));
    }
    $('#job').hidden = true;
    current = null;
    location.hash = 'match/' + j.match;
  } catch (err) { showError(err.message); }
  $('#go').disabled = false;
}
$('#form').addEventListener('submit', e => {
  e.preventDefault();
  startJob({url: $('#url').value, blue: nums($('#blue').value), red: nums($('#red').value)});
});

async function loadMatches() {
  const list = await api('/api/matches').catch(() => []);
  $('#matches').innerHTML = list.map(m => `<button class="item" data-id="${esc(m.id)}"><b>${esc(m.match_id || m.id)}</b>` +
    `<span class="hint">blue ${esc((m.teams.blue || []).join(' '))} &middot; red ${esc((m.teams.red || []).join(' '))}<br>` +
    `final ${m.final_score.blue ?? '?'} - ${m.final_score.red ?? '?'}${m.robots ? '' : ' &middot; no robot tracking'}</span></button>`).join('')
    || '<p class="hint">Nothing analyzed yet.</p>';
  document.querySelectorAll('#matches .item').forEach(b => b.addEventListener('click', () => { location.hash = 'match/' + b.dataset.id; }));
  const st = await api('/api/settings').catch(() => ({}));
  $('#tba-off').hidden = !!st.tba_key_set;
}

$('#tba-form').addEventListener('submit', async e => {
  e.preventDefault();
  $('#tba-err').hidden = true;
  try {
    const ms = await api('/api/tba/event/' + encodeURIComponent($('#tba-event').value.trim()));
    $('#tba-table').innerHTML = '<thead><tr><th class="l">Match</th><th class="l">Blue</th><th class="l">Red</th><th>Score</th><th></th></tr></thead><tbody>' +
      ms.map(m => `<tr><td class="l">${esc(m.name)}</td><td class="l">${esc(m.teams.blue.join(' '))}</td><td class="l">${esc(m.teams.red.join(' '))}</td>` +
        `<td>${m.score.blue ?? ''} - ${m.score.red ?? ''}</td><td>` +
        (m.analyzed ? `<button class="small" data-open="${esc(m.analyzed)}">Open</button>`
          : m.youtube.length ? `<button class="small" data-key="${esc(m.key)}">Analyze</button>` : '<span class="hint">no video</span>') +
        '</td></tr>').join('') + '</tbody>';
    document.querySelectorAll('#tba-table [data-key]').forEach(b => b.addEventListener('click', () => startJob({tba_match: b.dataset.key})));
    document.querySelectorAll('#tba-table [data-open]').forEach(b => b.addEventListener('click', () => { location.hash = 'match/' + b.dataset.open; }));
  } catch (err) { $('#tba-err').hidden = false; $('#tba-err').textContent = err.message; }
});

// ---------------------------------------------------------------- match page
async function openMatch(id) {
  current = id;
  $('#no-match').hidden = true; $('#match-body').hidden = false;
  const m = await api('/api/matches/' + encodeURIComponent(id));
  $('#title').textContent = m.tba ? `${m.tba.event} ${m.tba.name}` : (m.match_id || m.id);
  const t = m.teams || {}, fs = m.final_score || {};
  $('#meta').textContent = `Scoreboard at the end: blue ${fs.blue ?? '?'} - red ${fs.red ?? '?'}` +
    (m.tba && m.tba.score ? `  (official: ${m.tba.score.blue} - ${m.tba.score.red})` : '') +
    `   Blue: ${(t.blue || []).join(', ') || '?'}   Red: ${(t.red || []).join(', ') || '?'}   AUTO won by ${m.auto_winner || '?'}`;
  Chart.show(m);
  const bd = m.tba && m.tba.breakdown;
  $('#tba-box').hidden = !bd;
  if (bd) {
    const keys = [...new Set(Object.values(bd).flatMap(o => Object.keys(o || {})))];
    $('#breakdown').innerHTML = '<thead><tr><th class="l">Field</th><th>Blue</th><th>Red</th></tr></thead><tbody>' +
      keys.map(k => `<tr><td class="l">${esc(k)}</td><td>${esc(JSON.stringify(bd.blue?.[k] ?? ''))}</td><td>${esc(JSON.stringify(bd.red?.[k] ?? ''))}</td></tr>`).join('') + '</tbody>';
  }
  $('#frame-wrap').hidden = true;
  await loadRobots(m);
}

async function loadRobots(m) {
  robotsData = await api(`/api/matches/${current}/robots`);
  $('#robot-warn').hidden = robotsData.available;
  if (!robotsData.available) {
    $('#robot-warn').textContent = 'No robot tracking for this match: ' + robotsData.reason;
    $('#robots').innerHTML = ''; Replay.load(null, m); return;
  }
  Replay.load(robotsData, m);
  const cols = [['Role', s => esc(s.role), 'l'], ['Balls in (est.)', s => s.balls_est.toFixed(0)], ['Shots', s => s.shots],
    ['Shooting', s => s.shooting_s + ' s'], ['Defending', s => s.defense_s + ' s'], ['Opp. contacts', s => s.contacts_opponent],
    ['Distance', s => s.distance_m.toFixed(0) + ' m'], ['Own / mid / opp zone', s => `${s.zone_s.own} / ${s.zone_s.neutral} / ${s.zone_s.opponent} s`],
    ['Seen', s => s.seen_pct + '%']];
  $('#robots').innerHTML = '<thead><tr><th class="l">Robot</th><th class="l">Team</th>' + cols.map(c => `<th class="${c[2] || ''}">${c[0]}</th>`).join('') +
    '<th class="l">Notes</th></tr></thead><tbody>' + robotsData.robots.map(r =>
      `<tr><td class="l"><span class="dot" style="background:var(--${r.alliance})"></span>${r.slot}</td>` +
      `<td class="l"><input class="team" data-slot="${r.slot}" value="${r.team ?? ''}" aria-label="Team for ${r.slot}"> ` +
      `<span class="tag">${r.team_source}</span></td>` +
      cols.map(c => `<td class="${c[2] || ''}">${c[1](r.stats)}</td>`).join('') +
      `<td class="l">${(robotsData.notes[r.slot] || []).map(esc).join('<br>')}</td></tr>`).join('') + '</tbody>';
  document.querySelectorAll('#robots input.team').forEach(i => i.addEventListener('input', () => Replay.relabel(i.dataset.slot, i.value)));
  $('#label-hint').textContent = '';
}

$('#save-labels').addEventListener('click', async () => {
  const labels = {};
  document.querySelectorAll('#robots input.team').forEach(i => { labels[i.dataset.slot] = i.value ? +i.value : null; });
  try {
    await putJSON(`/api/matches/${current}/labels`, labels);
    $('#label-hint').textContent = 'Saved.';
    const m = await api('/api/matches/' + encodeURIComponent(current));
    await loadRobots(m);
    $('#label-hint').textContent = 'Saved.';
  } catch (e) { $('#label-hint').textContent = e.message; }
});

$('#show-frame').addEventListener('click', () => {
  $('#frame-wrap').hidden = false;
  $('#frame').src = `/api/matches/${current}/frame?t=${Replay.time().toFixed(1)}&_=${Date.now()}`;
});

// ---------------------------------------------------------------- teams
let teamsData = null;
async function loadTeams(team) {
  teamsData = await api('/api/teams').catch(() => null);
  if (!teamsData) return;
  const M = teamsData.metrics, keys = Object.keys(M);
  $('#teams-table').innerHTML = '<thead><tr><th class="l">Team</th><th>Matches</th><th class="l">Main role</th>' +
    keys.map(k => `<th>${esc(M[k][0])}</th>`).join('') + '</tr></thead><tbody>' +
    teamsData.teams.map(p => `<tr class="click" data-team="${p.team}"><td class="l"><b>${p.team}</b>${p.guessed_identity ? ' <span class="tag">guess</span>' : ''}</td>` +
      `<td>${p.matches}</td><td class="l">${esc(p.main_role)}</td>` + keys.map(k => `<td>${p.avg[k]}</td>`).join('') + '</tr>').join('') +
    `<tr><td class="l hint">Field average</td><td></td><td></td>` + keys.map(k => `<td class="hint">${teamsData.field[k]}</td>`).join('') + '</tr></tbody>';
  document.querySelectorAll('#teams-table tr[data-team]').forEach(r => r.addEventListener('click', () => { location.hash = 'teams/' + r.dataset.team; }));
  if (team) await teamReport(team); else $('#team-card').hidden = true;
}

async function teamReport(team) {
  const r = await api('/api/teams/' + team).catch(e => ({error: e.message}));
  $('#team-card').hidden = false;
  if (r.error) { $('#team-title').textContent = r.error; return; }
  $('#team-title').textContent = `Team ${team}: ${r.profile.matches} match(es) analyzed`;
  const li = a => a.length ? a.map(x => `<li>${esc(x)}</li>`).join('') : '<li class="hint">Nothing stands out.</li>';
  $('#team-strategy').innerHTML = li(r.strategy);
  $('#team-strengths').innerHTML = li(r.strengths);
  $('#team-weaknesses').innerHTML = li(r.weaknesses);
  $('#team-caveats').innerHTML = r.caveats.map(x => `<li>${esc(x)}</li>`).join('');
  $('#rec-tips').innerHTML = ''; $('#rec-note').textContent = '';
  $('#rec-form').dataset.team = team;
}
$('#rec-form').addEventListener('submit', async e => {
  e.preventDefault();
  const team = $('#rec-form').dataset.team;
  const r = await api(`/api/recommend?team=${team}&partners=${encodeURIComponent($('#rec-partners').value)}&opponents=${encodeURIComponent($('#rec-opponents').value)}`);
  $('#rec-tips').innerHTML = r.tips.map(x => `<li>${esc(x)}</li>`).join('');
  $('#rec-note').textContent = r.note;
});

// ---------------------------------------------------------------- settings + calibration
async function loadSettings() {
  const s = await api('/api/settings');
  $('#status').innerHTML = `<dt>TBA key</dt><dd>${s.tba_key_set ? 'set' : 'not set'}</dd>` +
    `<dt>Robot model</dt><dd>${s.model_found ? 'found' : 'missing: put robots.onnx in ' + esc(s.models_dir)}</dd>` +
    `<dt>Match data</dt><dd>${esc(s.data_dir)}</dd><dt>Settings file</dt><dd>${esc(s.config_file)}</dd>`;
  const list = await api('/api/matches').catch(() => []);
  const sel = $('#cal-match'), keep = sel.value;
  sel.innerHTML = list.map(m => `<option value="${esc(m.id)}">${esc(m.match_id || m.id)}</option>`).join('');
  if (keep) sel.value = keep;
  if (!cal) await loadCalibration();
}
$('#key-form').addEventListener('submit', async e => {
  e.preventDefault();
  await putJSON('/api/settings', {TBA_API_KEY: $('#tba-key').value});
  $('#tba-key').value = '';
  await loadSettings();
});

let cal = null;  // layout being edited
async function loadCalibration() {
  cal = await api('/api/layout');
  drawCalTable();
  if ($('#cal-match').value) loadCalFrame();
}
function loadCalFrame() {
  $('#cal-img').src = `/api/matches/${$('#cal-match').value}/frame?t=${+$('#cal-t').value}&grid=${$('#cal-grid').checked}&_=${Date.now()}`;
}
$('#cal-load').addEventListener('click', loadCalFrame);
$('#cal-grid').addEventListener('change', loadCalFrame);
$('#cal-img').addEventListener('load', drawHandles);
addEventListener('resize', drawHandles);

function drawHandles() {
  document.querySelectorAll('.handle').forEach(h => h.remove());
  const img = $('#cal-img');
  if (!cal || !img.naturalWidth) return;
  const k = img.clientWidth / cal.frame_size[0];
  cal.calibration.forEach((p, i) => {
    const h = document.createElement('div');
    h.className = 'handle'; h.style.left = p.image[0] * k + 'px'; h.style.top = p.image[1] * k + 'px';
    h.innerHTML = `<span>${i + 1}. ${esc(p.label || '')}</span>`;
    h.addEventListener('pointerdown', e => {
      h.setPointerCapture(e.pointerId);
      const move = ev => {
        const r = img.getBoundingClientRect();
        p.image = [Math.round((ev.clientX - r.left) / k), Math.round((ev.clientY - r.top) / k)];
        h.style.left = p.image[0] * k + 'px'; h.style.top = p.image[1] * k + 'px';
        drawCalTable();
      };
      h.addEventListener('pointermove', move);
      h.addEventListener('pointerup', () => h.removeEventListener('pointermove', move), {once: true});
    });
    $('#cal-stage').appendChild(h);
  });
}
function drawCalTable() {
  $('#cal-table').innerHTML = '<thead><tr><th>#</th><th class="l">Label</th><th>Field x (m)</th><th>Field y (m)</th><th>Image x (px)</th><th>Image y (px)</th><th></th></tr></thead><tbody>' +
    cal.calibration.map((p, i) => `<tr><td>${i + 1}</td><td class="l"><input type="text" data-i="${i}" data-k="label" value="${esc(p.label || '')}"></td>` +
      [['field', 0], ['field', 1], ['image', 0], ['image', 1]].map(([k, j]) => `<td><input type="number" step="0.01" data-i="${i}" data-k="${k}" data-j="${j}" value="${p[k][j]}"></td>`).join('') +
      `<td><button class="small" data-del="${i}" aria-label="Remove point ${i + 1}">x</button></td></tr>`).join('') + '</tbody>';
  document.querySelectorAll('#cal-table input').forEach(inp => inp.addEventListener('change', () => {
    const p = cal.calibration[+inp.dataset.i];
    if (inp.dataset.k === 'label') p.label = inp.value; else p[inp.dataset.k][+inp.dataset.j] = +inp.value;
    drawHandles();
  }));
  document.querySelectorAll('#cal-table [data-del]').forEach(b => b.addEventListener('click', () => {
    cal.calibration.splice(+b.dataset.del, 1); drawCalTable(); drawHandles();
  }));
}
$('#cal-add').addEventListener('click', () => {
  cal.calibration.push({label: 'new point', field: [8.27, 4.035], image: [960, 480]});
  drawCalTable(); drawHandles();
});
$('#cal-save').addEventListener('click', async () => {
  try {
    cal = await putJSON('/api/layout', {calibration: cal.calibration});
    $('#cal-msg').textContent = 'Saved. Every match now uses this calibration.';
    loadCalFrame();
  } catch (e) { $('#cal-msg').textContent = e.message; }
});

route();
