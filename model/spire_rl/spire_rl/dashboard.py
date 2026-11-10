"""Static HTML dashboard: charts are SVG drawn here (visible without scripts);
a small script only adds the hover crosshair/readout and the theme toggle."""
from __future__ import annotations

import html
import json
import math

W, H, L, R, T, B = 380, 180, 46, 48, 20, 24

STYLE = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--plane:#f9f9f7;--text-primary:#0b0b0b;--text-secondary:#52514e;
 --muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--band:rgba(42,120,214,.07);
 --series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--surface-1:#1a1a19;
 --plane:#0d0d0d;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
 --band:rgba(57,135,229,.10);--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-1:#1a1a19;--plane:#0d0d0d;--text-primary:#f0efec;
 --text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--band:rgba(57,135,229,.10);
 --series-1:#3987e5;--series-2:#d95926;--series-3:#199e70}
body{margin:0}
.viz-root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--plane);color:var(--text-primary);
 min-height:100vh;padding:20px 24px;box-sizing:border-box}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--text-secondary);font-size:13px;margin-bottom:14px;max-width:980px}
.controls{margin-bottom:14px}.controls button{font:inherit;font-size:13px;padding:4px 10px;border:1px solid var(--border);
 border-radius:6px;background:var(--surface-1);color:var(--text-primary);cursor:pointer}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-bottom:16px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.tile .v{font-size:22px;font-weight:600}.tile .l{font-size:12px;color:var(--text-secondary);margin-top:2px}
.section{font-size:13px;font-weight:600;color:var(--text-secondary);margin:18px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:12px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:10px 12px;position:relative}
.card h2{font-size:13px;margin:0 0 2px;font-weight:600}.card .note{font-size:11px;color:var(--muted);margin-bottom:4px}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11px;color:var(--text-secondary);margin-bottom:2px}
.legend i{display:inline-block;width:14px;height:2px;vertical-align:middle;margin-right:4px;border-radius:1px}
.legend b{display:inline-block;width:8px;height:8px;border-radius:50%;vertical-align:middle;margin-right:4px}
.legend u{display:inline-block;width:12px;height:10px;vertical-align:middle;margin-right:4px;background:var(--band);
 border:1px solid var(--border);text-decoration:none}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{font-size:10px;fill:var(--muted)}svg .end{fill:var(--text-secondary)}
.tip{position:absolute;pointer-events:none;background:var(--surface-1);border:1px solid var(--border);border-radius:6px;
 padding:6px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.12);display:none;white-space:nowrap;z-index:2}
.tip strong{font-variant-numeric:tabular-nums}.tip .k{display:inline-block;width:12px;height:2px;margin-right:6px;vertical-align:middle}
.tip .x{color:var(--muted);margin-bottom:2px}
.empty{color:var(--muted);font-size:13px;padding:40px 0;text-align:center}
details{margin-top:18px}summary{cursor:pointer;font-size:13px;color:var(--text-secondary)}
.tablewrap{max-height:70vh;overflow:auto;border:1px solid var(--border);border-radius:10px;margin-top:8px}
table{border-collapse:collapse;font-size:12px;background:var(--surface-1);width:100%}
th,td{border-bottom:1px solid var(--grid);padding:3px 6px;text-align:right;font-variant-numeric:tabular-nums}
th{color:var(--text-secondary);position:sticky;top:0;background:var(--surface-1)}
"""

SCRIPT = """
document.getElementById('themeBtn').onclick=()=>{const r=document.documentElement;
 const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
 r.dataset.theme=dark?'light':'dark';};
for(const card of document.querySelectorAll('.card[data-chart]')){
 const spec=JSON.parse(card.dataset.chart), svg=card.querySelector('svg'), hit=svg.querySelector('.hit'),
  cross=svg.querySelector('.cross'), tip=card.querySelector('.tip'); if(!hit) continue;
 const xs=[...new Set(spec.series.flatMap(s=>s.pts.map(p=>p[0])))].sort((a,b)=>a-b);
 const fmt=v=>spec.pct?(100*v).toFixed(1)+'%':(Math.abs(v)>=100?Math.round(v).toLocaleString():(+v.toPrecision(3)).toString());
 hit.addEventListener('pointermove',ev=>{const r=svg.getBoundingClientRect(),px=(ev.clientX-r.left)*spec.W/r.width;
  const xv=(px-spec.L)/spec.pw*spec.xmax; let best=xs[0]; for(const x of xs) if(Math.abs(x-xv)<Math.abs(best-xv)) best=x;
  const cx=spec.L+spec.pw*best/spec.xmax; cross.setAttribute('x1',cx); cross.setAttribute('x2',cx); cross.style.visibility='visible';
  const head=document.createElement('div'); head.className='x'; head.textContent='episode '+Math.round(best).toLocaleString();
  tip.replaceChildren(head);
  spec.series.forEach((s,i)=>{if(!s.pts.length) return; const p=s.pts.reduce((a,q)=>Math.abs(q[0]-best)<Math.abs(a[0]-best)?q:a);
   const row=document.createElement('div'), k=document.createElement('span'), v=document.createElement('strong');
   k.className='k'; k.style.background='var(--series-'+(i+1)+')'; v.textContent=fmt(p[1]);
   row.append(k,v,document.createTextNode(' '+s.name+(p[0]!==best?' (@'+Math.round(p[0]).toLocaleString()+')':''))); tip.appendChild(row);});
  tip.style.display='block'; const cr=card.getBoundingClientRect();
  tip.style.left=Math.max(4,Math.min(ev.clientX-cr.left+12,cr.width-tip.offsetWidth-4))+'px'; tip.style.top=(ev.clientY-cr.top+12)+'px';});
 hit.addEventListener('pointerleave',()=>{tip.style.display='none'; cross.style.visibility='hidden';});
}
"""


def _ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        hi = lo + 1.0
    step0 = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(step0))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= step0)
    v = math.floor(lo / step) * step
    out = []
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def _fmt(v: float, pct: bool = False) -> str:
    if v is None:
        return "–"
    if pct:
        return f"{100 * v:.1f}%"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 100:
        return f"{v:.0f}"
    return f"{v:.3g}"


def _xlabel(v: float) -> str:
    return f"{v / 1000:g}k" if v >= 1000 else f"{v:g}"


def chart(title: str, series: list[dict], xmax: float, sweet: tuple[int, int], stage_x: list[tuple[float, str]],
          note: str = "", pct: bool = False, ymin: float | None = None, ymax: float | None = None) -> str:
    esc = html.escape
    series = [{"name": s["name"], "points": s.get("points", False),
               "pts": [(float(x), float(y)) for x, y in s["data"] if y is not None and math.isfinite(float(y))]}
              for s in series]
    head = f'<h2>{esc(title)}</h2>' + (f'<div class="note">{esc(note)}</div>' if note else "")
    keys = ""
    if len(series) > 1:
        keys = "".join(f'<span><{"b" if s["points"] else "i"} style="background:var(--series-{i + 1})">'
                       f'</{"b" if s["points"] else "i"}>{esc(s["name"])}</span>' for i, s in enumerate(series))
    if sweet[0] < xmax:
        keys += f'<span><u></u>sweet spot {sweet[0] // 1000}k–{sweet[1] // 1000}k</span>'
    if keys:
        head += f'<div class="legend">{keys}</div>'
    allp = [p for s in series for p in s["pts"]]
    if not allp:
        return f'<div class="card">{head}<div class="empty">no data yet</div></div>'
    lo = ymin if ymin is not None else min(p[1] for p in allp)
    hi = ymax if ymax is not None else max(p[1] for p in allp)
    if ymin is None and 0 < lo < hi * 0.5:
        lo = 0.0
    ticks = _ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    pw, ph = W - L - R, H - T - B
    X = lambda x: L + pw * x / xmax
    Y = lambda y: T + ph * (1 - (y - lo) / ((hi - lo) or 1))
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    s0, s1 = sweet
    if s0 < xmax:
        x0, x1 = X(s0), X(min(s1, xmax))
        parts.append(f'<rect x="{x0:.1f}" y="{T}" width="{x1 - x0:.1f}" height="{ph}" fill="var(--band)"/>')
    for v in ticks:
        parts.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{L - 6}" y="{Y(v) + 3:.1f}" text-anchor="end">{esc(_fmt(v, pct))}</text>')
    for v in _ticks(0, xmax, 5):
        if v <= xmax:
            parts.append(f'<text x="{X(v):.1f}" y="{H - 6}" text-anchor="middle">{_xlabel(v)}</text>')
    parts.append(f'<line x1="{L}" x2="{W - R}" y1="{T + ph}" y2="{T + ph}" stroke="var(--axis)" stroke-width="1"/>')
    for x, label in stage_x:
        parts.append(f'<line x1="{X(x):.1f}" x2="{X(x):.1f}" y1="{T - 4}" y2="{T + ph}" stroke="var(--axis)" stroke-width="1"/>')
        parts.append(f'<text x="{X(x):.1f}" y="{T - 7}" text-anchor="middle" font-size="9">{esc(label)}</text>')
    placed: list[float] = []
    for i, s in enumerate(series):
        color = f"var(--series-{i + 1})"
        pts = s["pts"]
        if s["points"]:
            for x, y in pts:
                parts.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4" fill="{color}" stroke="var(--surface-1)" stroke-width="2"/>')
        elif pts:
            d = "".join(("M" if j == 0 else "L") + f"{X(x):.1f},{Y(y):.1f}" for j, (x, y) in enumerate(pts))
            parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            x, y = pts[-1]
            parts.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4" fill="{color}" stroke="var(--surface-1)" stroke-width="2"/>')
        if pts and len(series) <= 4:
            x, y = pts[-1]
            # Converging ends: keep the first label; the rest stay in the readout/table.
            if all(abs(Y(y) - other) >= 11 for other in placed):
                placed.append(Y(y))
                parts.append(f'<text class="end" x="{X(x) + 7:.1f}" y="{Y(y) + 3:.1f}">{esc(_fmt(y, pct))}</text>')
    parts.append(f'<line class="cross" x1="0" x2="0" y1="{T}" y2="{T + ph}" stroke="var(--axis)" stroke-width="1" style="visibility:hidden"/>')
    parts.append(f'<rect class="hit" x="{L}" y="{T}" width="{pw}" height="{ph}" fill="transparent"/></svg>')
    data = {"W": W, "L": L, "pw": pw, "xmax": xmax, "pct": pct,
            "series": [{"name": s["name"], "pts": s["pts"]} for s in series]}
    return (f'<div class="card" data-chart="{esc(json.dumps(data))}">{head}<div class="tip"></div>'
            + "".join(parts) + "</div>")


def render_dashboard(payload: dict) -> str:
    esc = html.escape
    train, evals = payload["train"], [r for r in payload["eval"] if r.get("split", "val") == "val"]
    total, sweet = payload["total"], tuple(payload["sweet"])
    xmax = float(max([total, 1] + [r["episodes"] for r in train] + [r["episodes"] for r in evals]))
    stage_x = [(r.get("episodes_at_rollout_start", r["episodes"]), f'α {r.get("alpha", 0):g}')
               for i, r in enumerate(train) if i and r.get("stage") != train[i - 1].get("stage")]
    T_ = lambda k: [(r["episodes"], r.get(k)) for r in train]
    E_ = lambda k: [(r["episodes"], r.get(k)) for r in evals]
    last = train[-1] if train else {}
    best = max(evals, key=lambda r: (r.get("win_rate", 0), -r["episodes"]), default=None)
    lastv = evals[-1] if evals else None

    def tile(v, label):
        return f'<div class="tile"><div class="v">{esc(v)}</div><div class="l">{esc(label)}</div></div>'

    kpis = "".join([
        tile(f'{last.get("episodes", 0):,} / {total:,}', "training episodes started"),
        tile(_fmt(lastv["win_rate"], True) if lastv else "–",
             f'latest validation win rate @{lastv["episodes"]:,} (95% {_fmt(lastv["win_rate_ci_low"], True)}–'
             f'{_fmt(lastv["win_rate_ci_high"], True)})' if lastv else "latest validation win rate"),
        tile(_fmt(best["win_rate"], True) if best else "–",
             f'best validation (episode {best["episodes"]:,})' if best else "best validation"),
        tile(_fmt(last.get("alpha")) if last else "–", f'progress weight α (stage {last.get("stage", "–")})'),
        tile(_fmt(last.get("episodes_per_hour")) if last else "–", "episodes / hour (average so far, all wall time)"),
        tile(f'{max(0.0, last["eta_hours"]):.1f} h' if last.get("eta_hours") is not None else "–", "ETA to the episode budget"),
    ])
    c = lambda *a, **k: chart(*a, xmax=xmax, sweet=sweet, stage_x=stage_x, **k)
    outcome = "".join([
        c("Win rate", [{"name": "train (this rollout)", "data": T_("win_rate")},
                       {"name": "validation (200 fixed seeds)", "data": E_("win_rate"), "points": True}],
          note="the model is chosen by validation wins only", pct=True, ymin=0),
        c("Mean floor reached", [{"name": "train", "data": T_("floor_mean")},
                                 {"name": "validation", "data": E_("floor_mean"), "points": True}]),
        c("Reached act 2 / act 3 (train)", [{"name": "act 2", "data": T_("reach_act2")},
                                            {"name": "act 3", "data": T_("reach_act3")}], pct=True, ymin=0, ymax=1),
        c("Raw reward per episode (train)", [{"name": "reward", "data": T_("reward_raw_mean")}],
          note="includes floor/act shaping weighted by α"),
    ])
    learning = "".join([
        c("Policy entropy", [{"name": "entropy", "data": T_("entropy")}]),
        c("Approx. KL per optimizer step", [{"name": "KL", "data": T_("approx_kl")}],
          note="an update stops early above 1.5 × target KL"),
        c("Clip fraction", [{"name": "clip fraction", "data": T_("clip_frac")}], pct=True, ymin=0),
        c("Value loss (Huber)", [{"name": "value loss", "data": T_("value_loss")}]),
        c("Policy loss", [{"name": "policy loss", "data": T_("policy_loss")}]),
        c("Auxiliary losses", [{"name": "next-fight survival", "data": T_("aux_survival_loss")},
                               {"name": "post-fight HP", "data": T_("aux_hp_loss")},
                               {"name": "act completion", "data": T_("aux_act_loss")}]),
        c("Gradient norm (before clipping)", [{"name": "grad norm", "data": T_("grad_norm")}]),
    ])
    systems = "".join([
        c("Seconds per episode (all wall time so far / episodes; incl. update, validation, saving)", [{"name": "s / episode", "data": T_("seconds_per_episode")}]),
        c("Wall time per cycle (s)", [{"name": "environments + combat MCTS", "data": T_("env_seconds")},
                                      {"name": "policy inference", "data": T_("inference_seconds")},
                                      {"name": "PPO update", "data": T_("update_seconds")}]),
        c("Peak GPU memory (GiB)", [{"name": "peak allocated", "data": T_("gpu_peak_gib")}]),
    ])
    keys = ["episodes", "updates", "stage", "alpha", "reward_raw_mean", "win_rate", "floor_mean", "reach_act2", "reach_act3",
            "entropy", "approx_kl", "clip_frac", "value_loss", "policy_loss", "seconds_per_episode"]
    rows = "".join("<tr>" + "".join(f"<td>{esc(_fmt(r.get(k)) if isinstance(r.get(k), (int, float)) else str(r.get(k, '–')))}</td>"
                                    for k in keys) + "</tr>" for r in reversed(train))
    vrows = "".join("<tr>" + "".join(f"<td>{esc(_fmt(r.get(k)) if isinstance(r.get(k), (int, float)) else '–')}</td>"
                                     for k in ("episodes", "win_rate", "win_rate_ci_low", "win_rate_ci_high",
                                               "floor_mean", "reach_act2", "reach_act3")) + "</tr>"
                    for r in reversed(evals))
    sub = (f'updated {payload["generated"]} · x axis = training episodes started (budget {total:,}); '
           f'vertical hairlines = reward-stage changes (new α on top); shaded band = sweet spot {sweet[0]:,}–{sweet[1]:,} '
           f'(a prior estimate, not yet verified for this project)')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="120">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(payload['title'])}</title>
<style>{STYLE}</style></head><body><div class="viz-root">
<h1>{esc(payload['title'])}</h1><div class="sub">{esc(sub)}</div>
<div class="controls"><button id="themeBtn" type="button">Toggle dark mode</button></div>
<div class="kpis">{kpis}</div>
<div class="section">Outcomes</div><div class="grid">{outcome}</div>
<div class="section">Learning</div><div class="grid">{learning}</div>
<div class="section">Throughput and resources</div><div class="grid">{systems}</div>
<details><summary>Validation table</summary><div class="tablewrap"><table><tr>{''.join(f'<th>{k}</th>' for k in ('episodes','win rate','95% low','95% high','floor','act 2','act 3'))}</tr>{vrows}</table></div></details>
<details><summary>Training table (one row per update)</summary><div class="tablewrap"><table><tr>{''.join(f'<th>{k}</th>' for k in keys)}</tr>{rows}</table></div></details>
</div><script>{SCRIPT}</script></body></html>"""
