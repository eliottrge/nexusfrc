// Shared helpers + the balls-per-second chart (drag to pick a range).
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const mmss = t => { t = Math.max(0, Math.floor(t)); return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0'); };
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : ('Request failed (' + r.status + ')'));
  return body;
};
const putJSON = (url, data) => api(url, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
const nums = s => (String(s).match(/\d+/g) || []).map(Number);

const Chart = (() => {
  const W = 960, L = 44, R = 12, TOP = 26, PH = 150, MID = TOP + PH, BOT = MID + PH;
  let match = null, N = 0, step = 1, ymax = 1, sel = {a: 0, b: 0}, drag = null, seq = 0, timer = null;
  const xs = t => L + t * step;

  function niceMax(v) {
    const p = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1))));
    for (const m of [1, 2, 5, 10]) if (v <= m * p) return m * p;
    return 10 * p;
  }
  function barPath(x, w, h, up) {
    const r = Math.min(4, w / 2, h), y = up ? MID - h : MID + h;
    return up
      ? `M${x},${MID}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${MID}Z`
      : `M${x},${MID}V${y - r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y - r}V${MID}Z`;
  }
  function periods() {
    const out = [];
    for (const s of match.seconds) {
      const last = out[out.length - 1];
      if (last && last.name === s.period) last.b = s.t + 1; else out.push({name: s.period, a: s.t, b: s.t + 1});
    }
    return out;
  }
  function draw() {
    const secs = match.seconds;
    N = secs.length; step = (W - L - R) / N;
    ymax = niceMax(Math.max(1, ...secs.map(s => Math.max(s.blue.estimate, s.red.estimate))));
    let g = `<defs>` + ['blue', 'red'].map(c =>
      `<pattern id="h-${c}" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)">` +
      `<rect width="2.5" height="5" style="fill:var(--${c})"/></pattern>`).join('') + `</defs>`;
    periods().forEach((p, i) => {
      if (i % 2 === 0) g += `<rect x="${xs(p.a)}" y="${TOP}" width="${(p.b - p.a) * step}" height="${2 * PH}" style="fill:var(--band)"/>`;
      g += `<text x="${xs((p.a + p.b) / 2)}" y="${TOP - 9}" text-anchor="middle">${esc(p.name === 'TRANSITION' ? 'TRANS.' : p.name)}</text>`;
    });
    for (const f of [0.5, 1]) for (const dir of [-1, 1]) {
      const y = MID + dir * f * PH;
      g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" style="stroke:var(--grid)"/>` +
           `<text x="${L - 6}" y="${y + 4}" text-anchor="end">${+(f * ymax).toFixed(1)}</text>`;
    }
    g += `<text x="${L - 6}" y="${MID + 4}" text-anchor="end">0</text>`;
    for (const s of secs) for (const c of ['blue', 'red']) {
      const h = s[c].estimate / ymax * PH;
      if (h < 0.5) continue;
      const w = Math.max(1, step - 2);
      g += `<path d="${barPath(xs(s.t) + (step - w) / 2, w, h, c === 'blue')}" style="fill:${s[c].trusted ? `var(--${c})` : `url(#h-${c})`}"/>`;
    }
    g += `<line x1="${L}" x2="${W - R}" y1="${MID}" y2="${MID}" style="stroke:var(--muted)"/>`;
    for (let t = 0; t <= N; t += 10) g += `<text x="${xs(t)}" y="${BOT + 18}" text-anchor="middle">${mmss(t)}</text>`;
    g += `<g><rect id="dimL" y="${TOP}" height="${2 * PH}" style="fill:var(--sel)"/><rect id="dimR" y="${TOP}" height="${2 * PH}" style="fill:var(--sel)"/>` +
         `<line id="sel1" y1="${TOP}" y2="${BOT}" style="stroke:var(--text);stroke-width:1.5"/><line id="sel2" y1="${TOP}" y2="${BOT}" style="stroke:var(--text);stroke-width:1.5"/></g>`;
    g += `<rect id="hit" x="${L}" y="${TOP}" width="${W - L - R}" height="${2 * PH}" fill="transparent" style="cursor:crosshair"/>`;
    $('#chart').innerHTML = g;
    const hit = $('#hit');
    hit.addEventListener('pointerdown', onDown); hit.addEventListener('pointermove', onMove);
    hit.addEventListener('pointerup', onUp); hit.addEventListener('pointerleave', () => { $('#tip').style.display = 'none'; });
    drawSel();
  }
  function drawSel() {
    const x1 = xs(sel.a), x2 = xs(sel.b);
    $('#dimL').setAttribute('x', L); $('#dimL').setAttribute('width', Math.max(0, x1 - L));
    $('#dimR').setAttribute('x', x2); $('#dimR').setAttribute('width', Math.max(0, W - R - x2));
    for (const [id, x] of [['#sel1', x1], ['#sel2', x2]]) { $(id).setAttribute('x1', x); $(id).setAttribute('x2', x); }
    $('#from').value = sel.a; $('#to').value = sel.b; $('#from').max = N - 1; $('#to').max = N;
    $('#range').textContent = `${mmss(sel.a)} to ${mmss(sel.b)}  (${sel.b - sel.a} s)`;
    document.querySelectorAll('#chips .chip').forEach(c =>
      c.setAttribute('aria-pressed', String(+c.dataset.a === sel.a && +c.dataset.b === sel.b)));
  }
  function tAt(e) {
    const r = $('#chart').getBoundingClientRect();
    return Math.max(0, Math.min(N - 1, Math.floor(((e.clientX - r.left) / r.width * W - L) / step)));
  }
  function onDown(e) { drag = tAt(e); sel = {a: drag, b: drag + 1}; e.target.setPointerCapture(e.pointerId); drawSel(); schedule(); }
  function onMove(e) {
    const t = tAt(e);
    if (drag !== null) { sel = {a: Math.min(drag, t), b: Math.max(drag, t) + 1}; drawSel(); schedule(); }
    const s = match.seconds[t], tip = $('#tip'), wr = $('#wrap').getBoundingClientRect();
    const line = (n, c) => `${n} <b>${Math.round(c.estimate)}</b> (scorebug ${c.scored}, video ${c.counted}${c.trusted ? '' : ', hub off / END GAME'})`;
    tip.innerHTML = `<b>${mmss(t)}</b> &middot; ${esc(s.period)}<br>${line('Blue', s.blue)}<br>${line('Red', s.red)}`;
    tip.style.display = 'block';
    tip.style.left = Math.min(e.clientX - wr.left + 14, wr.width - tip.offsetWidth - 4) + 'px';
    tip.style.top = Math.max(0, e.clientY - wr.top - 70) + 'px';
  }
  function onUp() { drag = null; query(); }
  function setRange(a, b) {
    a = Math.max(0, Math.min(N - 1, Math.round(a))); b = Math.max(a + 1, Math.min(N, Math.round(b)));
    sel = {a, b}; drawSel(); query();
  }
  function schedule() { if (!timer) timer = setTimeout(() => { timer = null; query(); }, 90); }
  async function query() {
    const my = ++seq;
    const r = await api(`/api/matches/${match.id}/count?start=${sel.a}&end=${sel.b}`).catch(() => null);
    if (!r || my !== seq) return;
    $('#cards').innerHTML = ['blue', 'red'].map(c => {
      const x = r[c];
      return `<div class="res"><div class="who"><i class="sw ${c}"></i>${c === 'blue' ? 'Blue' : 'Red'} alliance</div>` +
        `<div class="big">${x.estimate} <small>balls (estimate)</small></div><dl>` +
        `<dt>Scorebug points</dt><dd>${x.scored}</dd><dt>Counted on video</dt><dd>${x.counted}</dd>` +
        `<dt>Hub active</dt><dd>${x.active_seconds} of ${x.seconds} s</dd><dt>Seconds estimated from video</dt><dd>${x.video_only_seconds}</dd></dl></div>`;
    }).join('');
    const vo = Math.max(r.blue.video_only_seconds, r.red.video_only_seconds);
    $('#note').textContent = vo
      ? `While a hub is active the estimate is the scorebug point count (one point per ball). The ${vo} s where a hub is inactive, or END GAME, use the video count x ${r.calibration} (the factor that makes the video match the scorebug elsewhere in this match), so those parts are approximate.`
      : 'In this range the estimate is the scorebug point count (one point per ball, exact while the hub is active and there are no foul points).';
    const rows = match.seconds.filter(s => s.t >= r.start && s.t < r.end);
    $('#table').innerHTML = '<thead><tr><th class="l">Time</th><th class="l">Period</th><th>Blue est.</th><th>Blue scorebug</th><th>Blue video</th><th>Red est.</th><th>Red scorebug</th><th>Red video</th></tr></thead><tbody>' +
      rows.map(s => `<tr><td class="l">${mmss(s.t)}</td><td class="l">${esc(s.period)}</td>` +
        ['blue', 'red'].map(c => `<td>${s[c].estimate.toFixed(1)}</td><td>${s[c].scored}</td><td>${s[c].counted}</td>`).join('') + '</tr>').join('') + '</tbody>';
  }
  $('#from').addEventListener('change', () => setRange(+$('#from').value, sel.b));
  $('#to').addEventListener('change', () => setRange(sel.a, +$('#to').value));

  return {
    show(m) {
      match = m; draw();
      $('#chips').innerHTML = [{name: 'Whole match', a: 0, b: N}, ...periods()].map(p =>
        `<button type="button" class="chip" data-a="${p.a}" data-b="${p.b}" aria-pressed="false">${esc(p.name)}</button>`).join('');
      document.querySelectorAll('#chips .chip').forEach(c => c.addEventListener('click', () => setRange(+c.dataset.a, +c.dataset.b)));
      sel = {a: 0, b: N}; drawSel(); query();
    },
  };
})();
