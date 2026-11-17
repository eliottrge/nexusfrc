// Top-down 2D replay of a match from /api/matches/<id>/robots (+ the per-second ball data).
const Replay = (() => {
  const cv = document.getElementById('field'), ctx = cv.getContext('2d');
  const PAD = 18;
  let R = null, M = null, t = 0, playing = false, last = 0, names = {}, cumul = null;
  let F, S, H;  // field info, px per metre, canvas height

  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fx = x => PAD + x * S, fy = y => H - PAD - y * S;

  function setup() {
    F = R.field;
    S = (cv.width - 2 * PAD) / F.length;
    H = Math.round(F.width * S + 2 * PAD);
    cv.height = H;
    names = {};
    for (const r of R.robots) names[r.slot] = r.team ? String(r.team) : r.slot;
    // cumulative ball estimate per alliance, for the score display
    cumul = {blue: [0], red: [0]};
    for (const s of M.seconds) for (const a of ['blue', 'red']) cumul[a].push(cumul[a][cumul[a].length - 1] + s[a].estimate);
    const evs = R.events.filter(e => e.kind === 'shot' ? e.balls >= 1 : e.opponents);
    document.getElementById('events').innerHTML = evs.map((e, i) =>
      `<div data-t="${e.t0}" data-i="${i}">${mmss(e.t0)} ` + (e.kind === 'shot'
        ? `<span class="dot" style="background:var(--${e.slot.slice(0, -1)})"></span>${esc(names[e.slot])} shot, ~${Math.round(e.balls)} in`
        : `contact ${esc(names[e.a])} / ${esc(names[e.b])}`) + `</div>`).join('') || '<div class="hint">No events.</div>';
    document.querySelectorAll('#events div[data-t]').forEach(d => d.addEventListener('click', () => seek(+d.dataset.t)));
  }

  function idx(time) {  // index i with times[i] <= time < times[i+1], and the blend factor
    const ts = R.times;
    let lo = 0, hi = ts.length - 1;
    if (time <= ts[0]) return [0, 0];
    if (time >= ts[hi]) return [hi, 0];
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= time) lo = m; else hi = m; }
    return [lo, (time - ts[lo]) / (ts[lo + 1] - ts[lo])];
  }
  function posAt(slot, time) {
    const [i, f] = idx(time), P = R.positions[slot];
    const a = P[i], b = P[Math.min(i + 1, P.length - 1)];
    if (!a) return b ? [b[0], b[1], 0] : null;
    if (!b) return a;
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, f < 0.5 ? a[2] : b[2]];
  }

  function draw() {
    if (!R) return;
    const blue = css('--blue'), red = css('--red'), line = css('--line'), text = css('--text');
    const col = {blue, red};
    ctx.clearRect(0, 0, cv.width, H);
    ctx.fillStyle = css('--carpet'); ctx.fillRect(0, 0, cv.width, H);
    // alliance zones
    for (const [a, x0] of [['blue', 0], ['red', F.length - F.zone]]) {
      ctx.globalAlpha = 0.13; ctx.fillStyle = col[a];
      ctx.fillRect(fx(x0), fy(F.width), F.zone * S, F.width * S);
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = line; ctx.lineWidth = 2;
    ctx.strokeRect(fx(0), fy(F.width), F.length * S, F.width * S);
    ctx.beginPath(); ctx.moveTo(fx(F.length / 2), fy(0)); ctx.lineTo(fx(F.length / 2), fy(F.width)); ctx.stroke();
    ctx.setLineDash([6, 6]); ctx.lineWidth = 1;
    for (const x of [F.zone, F.length - F.zone]) { ctx.beginPath(); ctx.moveTo(fx(x), fy(0)); ctx.lineTo(fx(x), fy(F.width)); ctx.stroke(); }
    ctx.setLineDash([]);
    ctx.fillStyle = css('--text2'); ctx.font = '12px system-ui';
    ctx.fillText('camera side', fx(F.length / 2) + 6, fy(0) - 6);
    // hubs, coloured when active
    const sec = M.seconds[Math.max(0, Math.min(M.seconds.length - 1, Math.floor(t)))];
    for (const a of ['blue', 'red']) {
      const [hx, hy] = F.hubs[a], h = F.hub_size * S;
      const on = sec && sec[a].active;
      ctx.fillStyle = on ? col[a] : css('--grid'); ctx.globalAlpha = on ? 0.85 : 1;
      ctx.fillRect(fx(hx) - h / 2, fy(hy) - h / 2, h, h);
      ctx.globalAlpha = 1; ctx.strokeStyle = col[a]; ctx.lineWidth = 2; ctx.strokeRect(fx(hx) - h / 2, fy(hy) - h / 2, h, h);
      ctx.fillStyle = on ? '#fff' : css('--text2'); ctx.font = 'bold 11px system-ui'; ctx.textAlign = 'center';
      ctx.fillText(on ? 'HUB' : 'off', fx(hx), fy(hy) + 4); ctx.textAlign = 'start';
    }
    // shots in progress: dashed line robot -> hub
    for (const e of R.events) {
      if (e.kind !== 'shot' || t < e.t0 || t > e.t1 + 0.5) continue;
      const p = posAt(e.slot, t); if (!p) continue;
      ctx.strokeStyle = col[e.slot.slice(0, -1)]; ctx.setLineDash([4, 4]); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(fx(p[0]), fy(p[1])); ctx.lineTo(fx(e.hub[0]), fy(e.hub[1])); ctx.stroke(); ctx.setLineDash([]);
      if (e.balls >= 1) { ctx.fillStyle = text; ctx.font = '12px system-ui'; ctx.fillText(`~${Math.round(e.balls)}`, (fx(p[0]) + fx(e.hub[0])) / 2, (fy(p[1]) + fy(e.hub[1])) / 2 - 4); }
    }
    // trails
    if (document.getElementById('trails').checked) {
      for (const r of R.robots) {
        ctx.strokeStyle = col[r.alliance]; ctx.globalAlpha = 0.35; ctx.lineWidth = 2; ctx.beginPath();
        let first = true;
        for (let k = 30; k >= 0; k--) {
          const p = posAt(r.slot, t - k * 0.1); if (!p) continue;
          if (first) { ctx.moveTo(fx(p[0]), fy(p[1])); first = false; } else ctx.lineTo(fx(p[0]), fy(p[1]));
        }
        ctx.stroke(); ctx.globalAlpha = 1;
      }
    }
    // contacts in progress
    for (const e of R.events) {
      if (e.kind !== 'contact' || t < e.t0 - 0.2 || t > e.t1 + 0.3) continue;
      for (const s of [e.a, e.b]) {
        const p = posAt(s, t); if (!p) continue;
        ctx.strokeStyle = e.opponents ? '#f39c12' : css('--muted'); ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(fx(p[0]), fy(p[1]), 0.75 * S, 0, 7); ctx.stroke();
      }
    }
    // robots
    const rad = 0.45 * S;
    for (const r of R.robots) {
      const p = posAt(r.slot, t); if (!p) continue;
      ctx.beginPath(); ctx.arc(fx(p[0]), fy(p[1]), rad, 0, 7);
      if (p[2]) { ctx.fillStyle = col[r.alliance]; ctx.fill(); }
      ctx.strokeStyle = col[r.alliance]; ctx.lineWidth = 3; ctx.stroke();
      ctx.fillStyle = p[2] ? '#fff' : col[r.alliance]; ctx.font = 'bold 11px system-ui'; ctx.textAlign = 'center';
      ctx.fillText(names[r.slot], fx(p[0]), fy(p[1]) + 4); ctx.textAlign = 'start';
    }
    // side panel
    const k = Math.max(0, Math.min(cumul.blue.length - 1, Math.floor(t)));
    document.getElementById('sc-blue').textContent = Math.round(cumul.blue[k]);
    document.getElementById('sc-red').textContent = Math.round(cumul.red[k]);
    document.getElementById('sc-clock').textContent = mmss(t);
    document.getElementById('sc-period').textContent = sec ? sec.period : '';
    let cur = null;
    document.querySelectorAll('#events div[data-t]').forEach(d => { const on = +d.dataset.t <= t; d.classList.remove('now'); if (on) cur = d; });
    if (cur) cur.classList.add('now');
  }

  function seek(v) {
    t = Math.max(0, Math.min(R ? R.times[R.times.length - 1] : 160, v));
    document.getElementById('slider').value = t;
    draw();
  }
  function frame(now) {
    if (!playing) return;
    const dt = (now - last) / 1000; last = now;
    seek(t + dt * +document.getElementById('speed').value);
    if (t >= R.times[R.times.length - 1]) toggle(false);
    else requestAnimationFrame(frame);
  }
  function toggle(on = !playing) {
    playing = on && !!R;
    const b = document.getElementById('play');
    b.innerHTML = playing ? '&#10074;&#10074;' : '&#9654;'; b.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    if (playing) { last = performance.now(); requestAnimationFrame(frame); }
  }
  document.getElementById('play').addEventListener('click', () => toggle());
  document.getElementById('slider').addEventListener('input', e => { toggle(false); seek(+e.target.value); });
  document.getElementById('trails').addEventListener('change', draw);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);

  return {
    load(robotsData, matchData) {
      toggle(false); R = robotsData; M = matchData;
      if (!R || !R.available) { R = null; ctx.clearRect(0, 0, cv.width, cv.height); return; }
      document.getElementById('slider').max = R.times[R.times.length - 1];
      setup(); seek(0);
    },
    time: () => t,
    seek,
    relabel(slot, team) { names[slot] = team ? String(team) : slot; draw(); },
  };
})();
