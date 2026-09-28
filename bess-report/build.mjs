// Збирає друкований звіт: report.html (самодостатній, шрифти вбудовані) + PDF A4 + PNG-прев'ю сторінок.
// Запуск: node bess-report/build.mjs
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('/opt/node22/lib/node_modules/playwright')); }

/* ---------------------------------------------------------------- helpers */
const NB = ' ';
const fmt = (n, d = 0) => {
  const s = Math.abs(n).toFixed(d).split('.');
  s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, NB);
  return (n < 0 ? '−' : '') + s.join(',');
};
const font = (file, family, weight) => {
  const b64 = readFileSync(path.join(here, 'fonts', file)).toString('base64');
  return `@font-face{font-family:'${family}';font-style:normal;font-weight:${weight};font-display:block;src:url(data:font/woff2;base64,${b64}) format('woff2');}`;
};
const FONTS = [
  font('Inter-Regular.woff2', 'Inter', 400),
  font('Inter-Medium.woff2', 'Inter', 500),
  font('Inter-SemiBold.woff2', 'Inter', 600),
  font('Inter-Bold.woff2', 'Inter', 700),
  font('InterDisplay-Bold.woff2', 'Inter Display', 700),
  font('InterDisplay-ExtraBold.woff2', 'Inter Display', 800),
  font('InterDisplay-Black.woff2', 'Inter Display', 900),
].join('\n');

const C = {
  ink: '#0d1b2e', ink2: '#46546a', muted: '#7b8698', line: '#dfe4ec', grid: '#e9edf3', soft: '#f3f5f9',
  v1: '#2a78d6', v1s: '#dbe9fa', v2: '#eb6834', v2s: '#fde5da',
  cheap: '#12a0a0', peak: '#e34948', idle: '#edf0f5',
};

/* ------------------------------------------------------------ SVG: hatch */
const hatch = (id, color, bg) => `<pattern id="${id}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="${bg}"/><line x1="0" y1="0" x2="0" y2="6" stroke="${color}" stroke-width="2.2"/></pattern>`;

/* ------------------------------------------- 02: timeline of charge/discharge */
function timelineSVG() {
  const W = 720, x0 = 196, x1 = 704, maxH = 8, px = (x1 - x0) / maxH;
  const rows = [
    { grp: 'ЗАРЯД' },
    { t: 'Варіант 1', s: 'заряд 125 кВт', c: C.v1, v: 5.76, ext: 6.2, in: '5,76 год · 5 год 46 хв', out: 'реально ≈ 6–6,2 год' },
    { t: 'Варіант 2', s: 'заряд 375 кВт', c: C.v2, v: 1.92, ext: 2.1, in: '1,92 год', out: '1 год 55 хв · реально ≈ 2–2,1 год' },
    { grp: 'РОЗРЯД' },
    { t: 'Рівномірно за 8 год', s: '90 кВт · вистачає 1 × 125 кВт', c: C.v1, v: 8, in: '8 год × 90 кВт = 720 кВт·год', light: true },
    { t: 'Повна потужність 125 кВт', s: 'варіант 1', c: C.v1, v: 5.76, in: '5,76 год ≈ 5,8 год', out: 'з утратами — трохи менше' },
    { t: 'Повна потужність 375 кВт', s: 'варіант 2', c: C.v2, v: 1.92, in: '1,92 год', out: 'уся батарея ≈ за 2 години' },
  ];
  let y = 26, body = '';
  for (const r of rows) {
    if (r.grp) {
      body += `<text x="0" y="${y + 13}" class="t-grp">${r.grp}</text><line x1="${x0}" x2="${x1}" y1="${y + 9}" y2="${y + 9}" stroke="${C.line}" stroke-dasharray="2 3"/>`;
      y += 19; continue;
    }
    const h = 22, w = r.v * px;
    body += `<text x="0" y="${y + 10}" class="t-row">${r.t}</text><text x="0" y="${y + 22}" class="t-sub">${r.s}</text>`;
    if (r.ext) body += `<rect x="${x0 + w - 4}" y="${y}" width="${(r.ext - r.v) * px + 4}" height="${h}" rx="4" fill="url(#h-${r.c === C.v1 ? 'v1' : 'v2'})"/>`;
    body += `<rect x="${x0}" y="${y}" width="${w}" height="${h}" rx="4" fill="${r.light ? (r.c === C.v1 ? '#5b98e2' : r.c) : r.c}"/>`;
    body += `<text x="${x0 + 9}" y="${y + 15}" class="t-in">${r.in}</text>`;
    if (r.out) body += `<text x="${x0 + (r.ext || r.v) * px + 8}" y="${y + 15}" class="t-out">${r.out}</text>`;
    y += h + 10;
  }
  let axis = '';
  for (let hh = 0; hh <= maxH; hh++) {
    const x = x0 + hh * px;
    axis += `<line x1="${x}" x2="${x}" y1="18" y2="${y - 6}" stroke="${C.grid}"/>`;
    axis += `<text x="${x}" y="10" class="t-axis" text-anchor="middle">${hh}${hh === maxH ? ' год' : ''}</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${y}" class="chart" role="img" aria-label="Час заряду і розряду для двох варіантів">
  <defs>${hatch('h-v1', C.v1, C.v1s)}${hatch('h-v2', C.v2, C.v2s)}</defs>${axis}${body}</svg>`;
}

/* ------------------------------------------------------ 04: 24-hour strips */
function stripsSVG() {
  const W = 720, x0 = 118, cell = 24, gap = 2;
  const months = [
    { m: 'Січень', sub: '2026', cheap: [2, 7], peak: [18, 23] },
    { m: 'Лютий', sub: '+ окремі денні години', cheap: [3, 7], peak: [17, 22] },
    { m: 'Вересень', sub: '2026', cheap: [11, 16], peak: [19, 23] },
  ];
  const hh = n => String(n).padStart(2, '0') + ':00';
  let out = '', y = 22;
  for (let h = 0; h <= 24; h += 3) out += `<text x="${x0 + h * cell}" y="10" class="t-axis" text-anchor="middle">${String(h).padStart(2, '0')}</text>`;
  for (const r of months) {
    out += `<text x="0" y="${y + 13}" class="t-row">${r.m}</text><text x="0" y="${y + 25}" class="t-sub">${r.sub}</text>`;
    for (let h = 0; h < 24; h++) {
      if ((h >= r.cheap[0] && h < r.cheap[1]) || (h >= r.peak[0] && h < r.peak[1])) continue;
      out += `<rect x="${x0 + h * cell + gap / 2}" y="${y}" width="${cell - gap}" height="28" rx="3" fill="${C.idle}"/>`;
    }
    for (const [[a, b], f] of [[r.cheap, C.cheap], [r.peak, C.peak]])
      out += `<rect x="${x0 + a * cell + gap / 2}" y="${y}" width="${(b - a) * cell - gap}" height="28" rx="4" fill="${f}"/>`;
    const lab = (a, b) => `<text x="${x0 + ((a + b) / 2) * cell}" y="${y + 18}" class="t-cell" text-anchor="middle">${hh(a)}–${hh(b)}</text>`;
    out += lab(...r.cheap) + lab(...r.peak);
    y += 40;
  }
  return `<svg viewBox="0 0 ${W} ${y - 6}" class="chart" role="img" aria-label="Типові дешеві й дорогі години доби">${out}</svg>`;
}

/* --------------------------------------------------- 04: dumbbell spread */
function dumbbellSVG() {
  const W = 720, x0 = 118, x1 = 700, max = 14000, sx = v => x0 + (v / max) * (x1 - x0);
  const rows = [
    { m: 'Січень', lo: 5346, hi: 12442, d: 7096 },
    { m: 'Лютий', lo: 6013, hi: 13778, d: 7765 },
    { m: 'Вересень', lo: 726, hi: 11599, d: 10873 },
  ];
  let out = '', y = 40;
  for (let v = 0; v <= max; v += 2000) {
    out += `<line x1="${sx(v)}" x2="${sx(v)}" y1="18" y2="${18 + rows.length * 50}" stroke="${C.grid}"/>`;
    out += `<text x="${sx(v)}" y="10" class="t-axis" text-anchor="middle">${fmt(v)}</text>`;
  }
  for (const r of rows) {
    const a = sx(r.lo), b = sx(r.hi);
    out += `<text x="0" y="${y + 4}" class="t-row">${r.m}</text>`;
    out += `<line x1="${a}" x2="${b}" y1="${y}" y2="${y}" stroke="#b9c2cf" stroke-width="3" stroke-linecap="round"/>`;
    out += `<text x="${(a + b) / 2}" y="${y - 7}" class="t-delta" text-anchor="middle">Δ ${fmt(r.d)}</text>`;
    out += `<circle cx="${a}" cy="${y}" r="6.5" fill="${C.cheap}" stroke="#fff" stroke-width="2"/>`;
    out += `<circle cx="${b}" cy="${y}" r="6.5" fill="${C.peak}" stroke="#fff" stroke-width="2"/>`;
    out += `<text x="${a}" y="${y + 20}" class="t-val" text-anchor="middle">${fmt(r.lo)}</text>`;
    out += `<text x="${b}" y="${y + 20}" class="t-val" text-anchor="middle">${fmt(r.hi)}</text>`;
    y += 50;
  }
  return `<svg viewBox="0 0 ${W} ${y - 18}" class="chart" role="img" aria-label="Середня ціна 6 найдешевших і 6 найдорожчих годин, грн/МВт·год">${out}</svg>`;
}

/* ------------------------------------------------------ 04: 28 September */
function sept28SVG() {
  const W = 330, H = 292, x0 = 40, y0 = 262, top = 24, max = 14000, sy = v => y0 - (v / max) * (y0 - top);
  const bars = [
    { l: '12:00–16:00', v: 10, c: C.cheap, lbl: '≈ 10', wide: true },
    { l: '20:00', v: 11500, c: C.peak }, { l: '21:00', v: 12500, c: C.peak },
    { l: '22:00', v: 9500, c: C.peak }, { l: '23:00', v: 8500, c: C.peak },
  ];
  let out = '';
  for (let v = 0; v <= max; v += 3500) {
    out += `<line x1="${x0}" x2="${W - 4}" y1="${sy(v)}" y2="${sy(v)}" stroke="${v ? C.grid : '#c3cad6'}"/>`;
    out += `<text x="${x0 - 6}" y="${sy(v) + 3}" class="t-axis" text-anchor="end">${fmt(v)}</text>`;
  }
  let x = x0 + 12;
  bars.forEach((b, i) => {
    const w = b.wide ? 66 : 36, h = Math.max(y0 - sy(b.v), 3);
    out += `<rect x="${x}" y="${y0 - h}" width="${w}" height="${h}" rx="${Math.min(4, h / 2)}" fill="${b.c}"/>`;
    out += `<text x="${x + w / 2}" y="${y0 - h - 6}" class="t-val" text-anchor="middle">${b.lbl || fmt(b.v)}</text>`;
    out += `<text x="${x + w / 2}" y="${y0 + 14}" class="t-axis" text-anchor="middle">${b.l}</text>`;
    x += w + (i === 0 ? 30 : 11);
    if (i === 0) out += `<text x="${x - 15}" y="${y0 - 8}" class="t-axis" text-anchor="middle">…</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img" aria-label="Ціни РДН 28 вересня">${out}
  <text x="${x0}" y="10" class="t-sub">грн/МВт·год</text></svg>`;
}

/* ---------------------------------------------------- 07: margin bars */
function marginSVG(title, data, diffLabel) {
  const W = 340, H = 232, x0 = 34, y0 = 176, top = 20, max = 250, sy = v => y0 - (v / max) * (y0 - top);
  let out = '';
  for (let v = 0; v <= max; v += 50) {
    out += `<line x1="${x0}" x2="${W - 4}" y1="${sy(v)}" y2="${sy(v)}" stroke="${v ? C.grid : '#c3cad6'}"/>`;
    out += `<text x="${x0 - 6}" y="${sy(v) + 3}" class="t-axis" text-anchor="end">${v}</text>`;
  }
  const gw = (W - x0 - 4) / data.length, bw = 30;
  data.forEach((d, i) => {
    const cx = x0 + gw * i + gw / 2;
    [[d.a, C.v1, cx - bw - 1], [d.b, C.v2, cx + 1]].forEach(([v, c, x]) => {
      out += `<path d="M${x},${y0} V${sy(v) + 4} q0,-4 4,-4 h${bw - 8} q4,0 4,4 V${y0} Z" fill="${c}"/>`;
      out += `<text x="${x + bw / 2}" y="${sy(v) - 5}" class="t-val" text-anchor="middle">${v}</text>`;
    });
    out += `<text x="${cx}" y="${y0 + 15}" class="t-row" text-anchor="middle">${d.m}</text>`;
    out += `<text x="${cx}" y="${y0 + 30}" class="t-diff" text-anchor="middle">${d.d}</text>`;
  });
  out += `<text x="${x0}" y="${y0 + 46}" class="t-sub">${diffLabel}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img" aria-label="${title}">${out}<text x="${x0}" y="9" class="t-sub">тис. грн / місяць</text></svg>`;
}

/* ------------------------------------------- 08: equal-area rectangles */
function equalAreaSVG() {
  const W = 720, x0 = 150, x1 = 706, maxH = 6.5, px = (x1 - x0) / maxH, ky = 0.2; // 0.2 px per кВт
  const rows = [
    { t: '3 × 125 кВт', s: '375 кВт × 1,92 год', p: 375, h: 1.92, c: C.v2, note: 'уся батарея — за 2 найдорожчі години' },
    { t: '1 × 125 кВт', s: '125 кВт × 5,76 год', p: 125, h: 5.76, c: C.v1, note: 'продаж ≈ 6 годин — частина вже не за піковими цінами' },
  ];
  let out = '', y = 26;
  const peakW = 2 * px;
  const total = rows.reduce((s, r) => s + r.p * ky + 26, 0);
  out += `<rect x="${x0}" y="18" width="${peakW}" height="${total}" fill="${C.peak}" opacity=".09"/>`;
  out += `<text x="${x0 + 6}" y="${18 + total - 6}" class="t-peak">2 найдорожчі години</text>`;
  for (const r of rows) {
    const h = r.p * ky;
    out += `<text x="0" y="${y + 12}" class="t-row">${r.t}</text><text x="0" y="${y + 25}" class="t-sub">${r.s}</text>`;
    out += `<rect x="${x0}" y="${y}" width="${r.h * px}" height="${h}" rx="4" fill="${r.c}"/>`;
    out += `<text x="${x0 + 9}" y="${y + 16}" class="t-in">720 кВт·год</text>`;
    if (r.p > 200) out += `<text x="${x0 + r.h * px + 10}" y="${y + 16}" class="t-out">${r.note}</text>`;
    else out += `<text x="${x0 + r.h * px - 10}" y="${y + 16}" class="t-in" text-anchor="end" style="font-weight:500">${r.note}</text>`;
    y += h + 26;
  }
  let axis = '';
  for (let hh = 0; hh <= 6; hh++) {
    const x = x0 + hh * px;
    axis += `<line x1="${x}" x2="${x}" y1="18" y2="${y - 20}" stroke="${C.grid}"/><text x="${x}" y="10" class="t-axis" text-anchor="middle">${hh}${hh === 6 ? ' год' : ''}</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${y - 12}" class="chart" role="img" aria-label="Однакова енергія 720 кВт·год при різній потужності">${axis}${out}</svg>`;
}

/* ------------------------------------------------------ small icons */
const I = {
  inverter: `<svg viewBox="0 0 40 40" class="ico"><rect x="3" y="3" width="34" height="34" rx="7" fill="currentColor"/><path d="M9 21c2.2-6 4.4-6 6.6 0s4.4 6 6.6 0 4.4-6 6.6 0" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><path d="M10 11h8M10 29.5h20" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".55"/></svg>`,
  battery: `<svg viewBox="0 0 40 40" class="ico"><rect x="13" y="2" width="14" height="5" rx="1.5" fill="currentColor"/><rect x="6" y="6" width="28" height="32" rx="5" fill="none" stroke="currentColor" stroke-width="2.6"/><rect x="10" y="10" width="20" height="24" rx="2.5" fill="currentColor" opacity=".9"/><path d="M22 13l-6 9h5l-2 8 6-10h-5z" fill="#fff"/></svg>`,
  check: `<svg viewBox="0 0 16 16" class="mk"><circle cx="8" cy="8" r="8" fill="#0f8a4a"/><path d="M4.6 8.3l2.2 2.2 4.6-4.9" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  minus: `<svg viewBox="0 0 16 16" class="mk"><circle cx="8" cy="8" r="8" fill="#c63d3c"/><path d="M4.8 8h6.4" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`,
  warn: `<svg viewBox="0 0 24 24" class="wi"><path d="M12 2.5 1.8 20.5h20.4z" fill="#eda100" stroke="#eda100" stroke-width="2" stroke-linejoin="round"/><path d="M12 9v5.2" stroke="#1b1300" stroke-width="2.3" stroke-linecap="round"/><circle cx="12" cy="17.4" r="1.35" fill="#1b1300"/></svg>`,
  bolt: `<svg viewBox="0 0 24 24" class="bi"><path d="M13.5 2 4.5 13.5h6L9.5 22l9-11.5h-6z" fill="currentColor"/></svg>`,
  arrow: `<svg viewBox="0 0 24 12" class="arr"><path d="M1 6h19M15 1.5 21 6l-6 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};
const rep = (s, n) => Array.from({ length: n }, () => s).join('');

/* ------------------------------------------------------ page chrome */
const TOTAL = 8;
const head = (sec) => `<header class="run-head"><span><b>BESS 720 кВт·год</b> · 1 × 125 кВт vs 3 × 125 кВт</span><span>${sec}</span></header>`;
const foot = (n) => `<footer class="run-foot"><span>Попередній розрахунок · усі значення приблизні</span><span class="pg">${String(n).padStart(2, '0')} <i>/ ${String(TOTAL).padStart(2, '0')}</i></span></footer>`;
const sec = (num, title, lede = '') => `<div class="sec-head"><span class="sec-num">${num}</span><div><h2>${title}</h2>${lede ? `<p class="lede">${lede}</p>` : ''}</div></div>`;

/* ================================================================= HTML */
const html = `<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Накопичувач 720 кВт·год</title>
<style>
${FONTS}
:root{
  --ink:${C.ink};--ink2:${C.ink2};--muted:${C.muted};--line:${C.line};--soft:${C.soft};
  --navy:#0a1628;--navy2:#13243d;--lime:#c5f03c;--lime-ink:#5b7a00;
  --v1:${C.v1};--v1s:${C.v1s};--v2:${C.v2};--v2s:${C.v2s};--cheap:${C.cheap};--peak:${C.peak};
  --good:#0f8a4a;--good-s:#e5f5ec;--bad:#c63d3c;--amber:#eda100;--amber-s:#fff5dc;
}
@page{size:A4;margin:0}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:#d9dee6;color:var(--ink);font:400 9.1pt/1.45 Inter,system-ui,sans-serif;
  font-feature-settings:"cv11","ss03";-webkit-print-color-adjust:exact;print-color-adjust:exact;
  -webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
.page{width:210mm;height:297mm;margin:8mm auto;background:#fff;position:relative;overflow:hidden;
  padding:12mm 15mm 16mm;display:flex;flex-direction:column;box-shadow:0 2px 18px rgba(10,22,40,.18);
  break-after:page;page-break-after:always}
.page:last-child{break-after:auto;page-break-after:auto}
@media print{body{background:#fff}.page{margin:0;box-shadow:none}}
@media screen and (max-width:820px){.page{zoom:.45}}
h1,h2,h3,.disp{font-family:'Inter Display',Inter,sans-serif;letter-spacing:-.01em;margin:0}
p{margin:0}
b,strong{font-weight:600}
.num,.tbl td,.tbl th{font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
/* running head/foot */
.run-head{display:flex;justify-content:space-between;align-items:center;font-size:7.3pt;color:var(--muted);
  letter-spacing:.02em;padding-bottom:3mm;border-bottom:1px solid var(--line);margin-bottom:6.5mm}
.run-head b{color:var(--ink);font-weight:700}
.run-foot{position:absolute;left:15mm;right:15mm;bottom:8mm;display:flex;justify-content:space-between;align-items:flex-end;
  font-size:7.2pt;color:var(--muted);border-top:1px solid var(--line);padding-top:2.4mm}
.run-foot .pg{font:800 10pt 'Inter Display';color:var(--ink);letter-spacing:.02em}
.run-foot .pg i{font-style:normal;color:var(--muted);font-weight:700}
/* sections */
.sec-head{display:flex;gap:4mm;align-items:flex-start;margin:0 0 3.6mm}
.sec-num{flex:none;font:800 9.5pt/1 'Inter Display';color:var(--lime);background:var(--navy);border-radius:5px;
  padding:5px 7px 5px;margin-top:2px;letter-spacing:.04em}
.sec-head h2{font-size:16.5pt;line-height:1.12;font-weight:800;color:var(--navy)}
.lede{color:var(--ink2);margin-top:1.3mm;font-size:9pt;max-width:160mm}
section+section{margin-top:7mm}
.sub-h{font:700 10.5pt/1.2 'Inter Display';color:var(--navy);margin:0 0 2.4mm}
.eyebrow{font-size:7pt;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
/* charts */
.chart{width:100%;height:auto;display:block;overflow:visible}
.chart text{font-family:Inter,sans-serif}
.t-axis{font-size:9px;fill:${C.muted};font-variant-numeric:tabular-nums}
.t-row{font-size:11px;font-weight:600;fill:${C.ink}}
.t-sub{font-size:9px;fill:${C.muted}}
.t-grp{font-size:8.5px;font-weight:700;letter-spacing:.12em;fill:${C.muted}}
.t-in{font-size:10px;font-weight:600;fill:#fff;font-variant-numeric:tabular-nums}
.t-out{font-size:10px;fill:${C.ink2};font-variant-numeric:tabular-nums}
.t-cell{font-size:9.5px;font-weight:600;fill:#fff;font-variant-numeric:tabular-nums}
.t-val{font-size:10px;font-weight:600;fill:${C.ink};font-variant-numeric:tabular-nums}
.t-delta{font-size:10.5px;font-weight:700;fill:${C.ink};font-variant-numeric:tabular-nums}
.t-diff{font-size:10px;font-weight:700;fill:#0f7a41;font-variant-numeric:tabular-nums}
.t-peak{font-size:9px;font-weight:600;fill:#b2302f}
.legend{display:flex;flex-wrap:wrap;gap:2.2mm 5mm;font-size:8pt;color:var(--ink2);margin:0 0 2.6mm}
.legend span{display:inline-flex;align-items:center;gap:1.6mm}
.sw{width:11px;height:11px;border-radius:3px;display:inline-block}
.sw.h1{background:repeating-linear-gradient(45deg,var(--v1) 0 2px,var(--v1s) 2px 5px)}
.fig{border:1px solid var(--line);border-radius:10px;padding:4mm 4.5mm 3.4mm}
.fig-cap{font-size:7.6pt;color:var(--muted);margin-top:2mm}
/* cards & callouts */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:4.5mm}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:3.2mm}
.card{border:1px solid var(--line);border-radius:10px;padding:4mm 4.5mm;background:#fff}
.callout{border-radius:10px;padding:3.6mm 4.5mm;display:flex;gap:3.5mm;align-items:flex-start}
.callout.note{background:var(--soft)}
.callout.good{background:var(--good-s)}
.callout.warn{background:var(--amber-s);border:1px solid #f3d27a}
.callout .wi{width:22px;height:22px;flex:none;margin-top:1px}
.callout h3{font-size:10.5pt;font-weight:800;color:var(--navy);margin-bottom:1mm}
.bi{width:14px;height:14px;display:inline-block;vertical-align:-2px}
.arr{width:22px;height:11px;color:var(--muted);flex:none}
.formula{font:700 12.5pt/1.2 'Inter Display';color:var(--navy);font-variant-numeric:tabular-nums;letter-spacing:-.005em}
.formula .eq{color:var(--muted);font-weight:700;margin:0 .15em}
.kv{display:grid;grid-template-columns:auto 1fr;gap:1mm 3mm;font-size:8.6pt}
.kv dt{color:var(--muted)}
.kv dd{margin:0;font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:7pt;font-weight:700;letter-spacing:.08em;text-transform:uppercase;border-radius:4px;padding:2px 6px}
.tag.v1{background:var(--v1s);color:#1b5aa6}
.tag.v2{background:var(--v2s);color:#b0441a}
/* tables */
.tbl{width:100%;border-collapse:collapse;font-size:8.6pt}
.tbl th{font-size:7pt;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-align:right;
  padding:0 2.4mm 1.8mm;border-bottom:1.5px solid var(--navy);vertical-align:bottom}
.tbl th:first-child,.tbl td:first-child{text-align:left;padding-left:0}
.tbl td{padding:2.1mm 2.4mm;border-bottom:1px solid var(--line);text-align:right}
.tbl td:last-child,.tbl th:last-child{padding-right:0}
.tbl tr:last-child td{border-bottom:none}
.tbl .hi{font-weight:700}
.tbl .pos{color:#0f7a41;font-weight:700}
.tbl .grp th{border-bottom:none;padding-bottom:1mm;text-align:center;color:var(--ink2)}
.tbl .grp th span{display:block;border-bottom:1px solid var(--line);padding-bottom:1mm}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:1.4mm;vertical-align:0}
/* lists */
ul.ticks{list-style:none;margin:0;padding:0;display:grid;gap:2.1mm}
ul.ticks li{display:grid;grid-template-columns:14px 1fr;gap:2.4mm;align-items:start;font-size:8.8pt}
.mk{width:13px;height:13px;margin-top:1.5px}

/* ============ COVER ============ */
.cover{padding:0}
.cover .band{background:var(--navy);color:#fff;padding:15mm 15mm 11mm;position:relative;overflow:hidden}
.cover .band::before{content:"";position:absolute;inset:0;opacity:.5;
  background-image:linear-gradient(rgba(255,255,255,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.055) 1px,transparent 1px);
  background-size:7mm 7mm}
.cover .band>*{position:relative}
.cover .kicker{display:flex;align-items:center;gap:2.4mm;font-size:7.6pt;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--lime)}
.cover .kicker i{display:inline-block;width:9mm;height:2px;background:var(--lime)}
.cover h1{font-size:31pt;line-height:1.02;font-weight:900;letter-spacing:-.022em;margin:6mm 0 4mm;max-width:130mm}
.cover h1 em{font-style:normal;color:var(--lime)}
.cover .subtitle{font-size:10.6pt;line-height:1.45;color:#c6d0de;max-width:118mm}
.cover .big{position:absolute;right:15mm;top:17mm;text-align:right}
.cover .big .n{font:900 64pt/0.9 'Inter Display';letter-spacing:-.04em;color:#fff}
.cover .big .u{font:700 12pt 'Inter Display';color:var(--lime);margin-top:1.5mm}
.cover .big .cells{display:flex;gap:2mm;justify-content:flex-end;margin-top:4mm}
.cover .big .cells span{width:13mm;height:6.5mm;border:1.6px solid #6f84a3;border-radius:2.2mm;position:relative;padding:1mm}
.cover .big .cells span::after{content:"";display:block;height:100%;background:var(--lime);border-radius:1.1mm}
.cover .big .cells span::before{content:"";position:absolute;right:-2.2mm;top:1.6mm;width:1.2mm;height:2.2mm;background:#6f84a3;border-radius:0 1px 1px 0}
.cover .big .cap{font-size:7.4pt;color:#8ea0bb;margin-top:1.6mm}
.cover .meta{display:grid;grid-template-columns:repeat(4,auto);gap:0;margin-top:9mm;border-top:1px solid rgba(255,255,255,.14)}
.cover .meta div{padding:3.2mm 5mm 0 0;margin-right:5mm;border-right:1px solid rgba(255,255,255,.14)}
.cover .meta div:last-child{border-right:none;margin-right:0}
.cover .meta small{display:block;font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:#8ea0bb;font-weight:700;margin-bottom:.8mm}
.cover .meta b{font-size:9.6pt;font-weight:600;color:#fff}
.cover .inner{padding:8mm 15mm 16mm;display:flex;flex-direction:column;gap:6.4mm;flex:1}
.stat{border-top:3px solid var(--navy);padding-top:2.6mm}
.stat .v{font:800 19pt/1.05 'Inter Display';color:var(--navy);letter-spacing:-.015em;white-space:nowrap}
.stat .v small{font-size:9pt;font-weight:700;color:var(--ink2);letter-spacing:0;margin-left:.6mm}
.stat .l{font-size:8pt;color:var(--ink2);margin-top:1.4mm;line-height:1.35}
.verdict{border-radius:12px;padding:5mm 5.5mm 4.6mm;position:relative;overflow:hidden;border:1px solid var(--line)}
.verdict.v1{border-top:5px solid var(--v1)}
.verdict.v2{border-top:5px solid var(--v2)}
.verdict .if{font-size:7.4pt;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.verdict .goal{font:700 11pt/1.3 'Inter Display';color:var(--navy);margin:1.6mm 0 3mm}
.verdict .cfg{display:flex;align-items:center;gap:2.6mm;padding:3mm 3.4mm;background:var(--soft);border-radius:8px}
.verdict .cfg .ico{width:22px;height:22px}
.verdict.v1 .cfg{color:var(--v1)} .verdict.v2 .cfg{color:var(--v2)}
.verdict .cfg b{font:800 12.5pt/1.1 'Inter Display';color:var(--navy);margin-left:.6mm;white-space:nowrap}
.verdict .cfg .ico{flex:none}
.verdict .cfg .plus{color:var(--muted);font-weight:700}
.verdict p{font-size:8.6pt;color:var(--ink2);margin-top:3mm}
.verdict .gain{display:flex;align-items:baseline;gap:2mm;margin-top:3mm;padding-top:2.6mm;border-top:1px dashed var(--line)}
.verdict .gain b{font:800 13pt 'Inter Display';color:#0f7a41;white-space:nowrap}
.verdict .gain span{font-size:7.8pt;color:var(--muted)}
.toc{display:grid;grid-template-columns:1fr 1fr;gap:0 8mm;font-size:8.6pt}
.toc div{display:flex;align-items:baseline;gap:2mm;padding:1.5mm 0;border-bottom:1px solid var(--line)}
.toc .n{font:800 8pt 'Inter Display';color:var(--muted);width:6mm}
.toc .d{flex:1;border-bottom:1px dotted #c7ced9;transform:translateY(-2px)}
.toc .p{font-weight:700;font-variant-numeric:tabular-nums}

/* variant cards */
.variant{border:1px solid var(--line);border-radius:12px;overflow:hidden}
.variant .top{padding:3.6mm 4.5mm 2mm;display:flex;justify-content:space-between;align-items:flex-start}
.variant.v1 .top{background:linear-gradient(180deg,var(--v1s),#fff)}
.variant.v2 .top{background:linear-gradient(180deg,var(--v2s),#fff)}
.variant h3{font-size:18pt;font-weight:900;letter-spacing:-.02em;color:var(--navy);margin-top:1.4mm}
.variant .power{text-align:right}
.variant .power b{font:800 18pt/1 'Inter Display';letter-spacing:-.02em}
.variant.v1 .power b{color:#1b5aa6}.variant.v2 .power b{color:#b0441a}
.variant .power small{display:block;font-size:7pt;color:var(--muted);margin-top:1mm}
.schema{display:flex;align-items:center;gap:2.4mm;padding:1.6mm 4.5mm 3mm}
.schema .grp{display:flex;gap:1.2mm}
.schema .ico{width:30px;height:30px}
.variant.v1 .schema .inv{color:var(--v1)} .variant.v2 .schema .inv{color:var(--v2)}
.schema .bat{color:#33455f}
.schema .lbl{font-size:7pt;color:var(--muted);text-align:center;margin-top:.6mm}
.variant .kv{padding:2.8mm 4.5mm 3.4mm;border-top:1px solid var(--line)}
/* formula cards */
.fcard{border:1px solid var(--line);border-radius:10px;padding:3mm 4mm;display:flex;flex-direction:column;gap:1.3mm}
.fcard .t{display:flex;justify-content:space-between;align-items:center}
.fcard p{font-size:8.4pt;color:var(--ink2)}
.fcard .res{display:flex;gap:4mm;font-size:8.2pt;margin-top:auto;padding-top:1.8mm;border-top:1px dashed var(--line)}
.fcard .res b{font-variant-numeric:tabular-nums}
/* efficiency flow */
.flow{display:flex;align-items:center;gap:2.5mm}
.flow .st{flex:1;border-radius:10px;padding:3.2mm 3.6mm;background:var(--soft);text-align:center}
.flow .st b{display:block;font:800 17pt/1.05 'Inter Display';color:var(--navy);font-variant-numeric:tabular-nums}
.flow .st span{font-size:7.8pt;color:var(--ink2)}
.flow .st.out{background:var(--navy)}
.flow .st.out b{color:var(--lime)} .flow .st.out span{color:#c6d0de}
.flow .op{font:800 9pt 'Inter Display';color:var(--ink2);text-align:center;display:flex;flex-direction:column;align-items:center;gap:.6mm;white-space:nowrap}
.flow .op small{font:500 7pt Inter;color:var(--muted)}
/* progress */
.prog{display:grid;grid-template-columns:24mm 1fr 30mm;gap:3mm;align-items:center;padding:3.4mm 0;border-bottom:1px solid var(--line)}
.prog:last-child{border-bottom:none}
.prog .m{font-weight:700}
.prog .bar{display:flex;gap:2px;height:20px}
.prog .bar i{flex:1;border-radius:2px;background:var(--good)}
.prog .bar i.x{background:#fff;border:1.5px solid #9aa6b8}
.prog .bar i.p{background:repeating-linear-gradient(45deg,#9aa6b8 0 1.5px,#fff 1.5px 4px);border:1.5px solid #9aa6b8}
.prog .r{text-align:right;font:800 13pt 'Inter Display';color:var(--navy);font-variant-numeric:tabular-nums}
.prog .r small{font:600 8pt Inter;color:var(--muted)}
.prog .note{grid-column:2 / 4;font-size:7.8pt;color:var(--ink2);margin-top:-1mm}
.daystrip{display:grid;grid-template-columns:repeat(24,1fr);gap:2px;margin-top:2mm}
.daystrip i{height:24px;border-radius:3px;background:${C.idle};position:relative}
.daystrip i.c{background:var(--v1)}
.dayaxis{display:grid;grid-template-columns:repeat(8,1fr);font-size:7pt;color:var(--muted);margin-top:1mm;font-variant-numeric:tabular-nums}
/* pros cons */
.pc{border:1px solid var(--line);border-radius:12px;overflow:hidden}
.pc .top{padding:3.6mm 4.5mm;display:flex;align-items:center;justify-content:space-between;color:#fff}
.pc.v1 .top{background:var(--v1)} .pc.v2 .top{background:var(--v2)}
.pc .top h3{font-size:15pt;font-weight:900;letter-spacing:-.01em;margin-top:1mm}
.pc .top span{font-size:7.2pt;font-weight:700;letter-spacing:.14em;text-transform:uppercase;opacity:.85}
.pc .body{padding:4.4mm 4.5mm 4.8mm;display:flex;flex-direction:column;gap:4mm}
.pc .lbl{font-size:7pt;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:.4mm}
/* connection */
.stack{display:flex;height:34px;border-radius:6px;overflow:hidden;gap:2px}
.stack div{display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:9pt;font-variant-numeric:tabular-nums}
.chk{display:grid;grid-template-columns:repeat(4,1fr);gap:2.4mm;margin-top:3mm}
.chk div{border:1px solid #efd58d;background:#fff;border-radius:8px;padding:2.4mm 2.8mm;font-size:8.2pt;font-weight:600;display:flex;gap:2mm;align-items:center}
.chk div i{width:11px;height:11px;border:1.5px solid var(--ink2);border-radius:2px;flex:none}
/* conclusion */
.concl{display:grid;grid-template-columns:1fr 1fr;gap:4.5mm}
.concl .c{border-radius:12px;padding:5mm 5mm 4.6mm;border:1px solid var(--line);display:flex;flex-direction:column;gap:3mm}
.concl .c.v1{border-left:5px solid var(--v1)} .concl .c.v2{border-left:5px solid var(--v2)}
.concl .task{display:flex;flex-direction:column;gap:1.2mm}
.concl .task div{background:var(--soft);border-radius:7px;padding:2.2mm 3mm;font-size:8.8pt;font-weight:600}
.concl .task .pl{background:none;padding:0;text-align:center;color:var(--muted);font-weight:800}
.concl .ans{display:flex;align-items:center;gap:2.4mm;margin-top:auto}
.concl .ans .res{font:800 13pt/1.15 'Inter Display';color:var(--navy)}
.concl .ans .arr{width:26px;height:13px;color:var(--ink2)}
.reco{background:var(--navy);color:#fff;border-radius:14px;padding:6mm 6mm 5.4mm}
.reco .eyebrow{color:var(--lime)}
.reco h3{font-size:14pt;font-weight:900;margin:1.4mm 0 4mm;letter-spacing:-.01em}
.reco .row{display:grid;grid-template-columns:1fr 20px 62mm;gap:3.6mm;align-items:center;padding:3.4mm 0;border-top:1px solid rgba(255,255,255,.14)}
.reco .row p{font-size:9pt;color:#d3dbe7}
.reco .row .arr{color:var(--lime);width:20px}
.reco .row .res{font:800 11.5pt/1.25 'Inter Display';color:#fff}
.reco .row .res small{display:block;font:500 7.6pt Inter;color:#8ea0bb;margin-top:.6mm}
.reco .pill{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:2mm;vertical-align:1px}
/* form */
.form{display:flex;flex-direction:column;gap:0}
.fld{display:grid;grid-template-columns:9mm 1fr 58mm;gap:3mm;align-items:end;padding:4.2mm 0 2.6mm;border-bottom:1px solid var(--line)}
.fld .n{font:900 15pt/1 'Inter Display';color:var(--navy)}
.fld .q{font-size:9.6pt;font-weight:600;line-height:1.3}
.fld .q small{display:block;font-size:7.8pt;font-weight:400;color:var(--muted);margin-top:.5mm}
.fld .line{display:flex;align-items:flex-end;gap:2mm;font-size:8.4pt;color:var(--muted);white-space:nowrap}
.fld .line i{flex:1;border-bottom:1.3px solid var(--ink2);height:6mm}
.opts{display:grid;grid-template-columns:1fr 1fr;gap:2.6mm 5mm;margin:2.4mm 0 1mm 12mm}
.opts div{display:flex;align-items:flex-end;gap:2mm;font-size:8.8pt;white-space:nowrap}
.opts .box{width:12px;height:12px;border:1.5px solid var(--ink);border-radius:2.5px;flex:none;align-self:center}
.opts i{flex:1;border-bottom:1.3px solid var(--ink2);height:4mm;min-width:12mm}
.calc{display:grid;grid-template-columns:repeat(5,1fr);gap:3mm}
.calc .g{border-top:3px solid var(--navy);padding-top:2.4mm}
.calc .g h4{margin:0 0 2mm;font:800 9pt 'Inter Display';color:var(--navy);text-transform:uppercase;letter-spacing:.06em}
.calc .g ul{margin:0;padding:0;list-style:none;display:grid;gap:1.6mm}
.calc .g li{font-size:8.2pt;line-height:1.3;padding-left:3.4mm;position:relative;color:var(--ink2)}
.calc .g li::before{content:"";position:absolute;left:0;top:.52em;width:4px;height:4px;border-radius:50%;background:var(--lime-ink)}
.ruled{display:grid;gap:0}
.ruled i{display:block;height:8mm;border-bottom:1px solid #b9c2cf}
.fine{font-size:7.6pt;color:var(--muted);line-height:1.45}
</style>
</head>
<body>

<!-- ============================ 1. ОБКЛАДИНКА ============================ -->
<div class="page cover">
  <div class="band">
    <div class="kicker"><i></i>Попередній техніко-економічний аналіз</div>
    <h1>Накопичувач <em>720&nbsp;кВт·год</em> для підприємства 120&nbsp;кВт</h1>
    <p class="subtitle">Порівняння конфігурацій <b style="color:#fff">1 × 125 кВт</b> і <b style="color:#fff">3 × 125 кВт</b>: час заряду й розряду, ціни РДН, арбітраж, валова маржа та рекомендація.</p>
    <div class="big">
      <div class="n">720</div>
      <div class="u">кВт·год</div>
      <div class="cells"><span></span><span></span><span></span></div>
      <div class="cap">3 × 240 кВт·год</div>
    </div>
    <div class="meta">
      <div><small>Навантаження</small><b>≈ 120 кВт</b></div>
      <div><small>Ємність батарей</small><b>3 × 240 = 720 кВт·год</b></div>
      <div><small>Ціни РДН</small><b>січень, лютий, вересень 2026</b></div>
      <div><small>Дата</small><b>28.09.2026</b></div>
    </div>
  </div>

  <div class="inner">
    <div>
      <div class="eyebrow" style="margin-bottom:3mm">Ключові цифри</div>
      <div class="grid4">
        <div class="stat"><div class="v">5,76 <small>год</small></div><div class="l">повний заряд при 125 кВт<br>(1,92 год при 375 кВт)</div></div>
        <div class="stat"><div class="v">≈ 90 <small>%</small></div><div class="l">round-trip ККД<br>0,95 × 0,95 = 0,9025</div></div>
        <div class="stat"><div class="v">10 873</div><div class="l">грн/МВт·год — спред РДН<br>у вересні 2026</div></div>
        <div class="stat"><div class="v">31 · 23 · 27</div><div class="l">днів із повним циклом при<br>1 × 125 кВт (січ · лют · вер)</div></div>
      </div>
    </div>

    <div>
      <div class="eyebrow" style="margin-bottom:3mm">Висновок одним поглядом</div>
      <div class="grid2">
        <div class="verdict v1">
          <div class="if">Якщо головне — власне споживання</div>
          <div class="goal">Заряджатися дешево й закривати навантаження 120 кВт у дорогі години</div>
          <div class="cfg">${I.inverter}<b>1 × 125 кВт</b><span class="plus">+</span>${I.battery}<b>720 кВт·год</b></div>
          <p>Інвертор майже точно відповідає навантаженню. Додаткові два інвертори тут майже нічого не дають.</p>
          <div class="gain"><b>+6,6…11,5 тис.</b><span>грн/міс — усього стільки додали б ще 2 інвертори</span></div>
        </div>
        <div class="verdict v2">
          <div class="if">Якщо головне — активна торгівля</div>
          <div class="goal">Заряд за 1–2 найдешевші години, продаж усієї батареї за 1–2 найдорожчі</div>
          <div class="cfg">${I.inverter}<b>3 × 125 кВт</b><span class="plus">+</span>${I.battery}<b>720 кВт·год</b></div>
          <p>Має сенс лише тоді, коли мережа дозволяє імпорт і експорт ≈ 375 кВт.</p>
          <div class="gain"><b>+20…40 тис.</b><span>грн/міс — перевага 3 × 125 кВт, якщо дозволено продаж</span></div>
        </div>
      </div>
    </div>

    <div>
      <div class="eyebrow" style="margin-bottom:1.4mm">Зміст</div>
      <div class="toc">
        <div><span class="n">01</span>Вихідні дані<span class="d"></span><span class="p">2</span></div>
        <div><span class="n">07</span>Валова маржа<span class="d"></span><span class="p">6</span></div>
        <div><span class="n">02</span>Час заряду і розряду<span class="d"></span><span class="p">2</span></div>
        <div><span class="n">08</span>Чому 375 кВт краще для продажу<span class="d"></span><span class="p">6</span></div>
        <div><span class="n">03</span>ККД<span class="d"></span><span class="p">3</span></div>
        <div><span class="n">09</span>Потужність приєднання<span class="d"></span><span class="p">7</span></div>
        <div><span class="n">04</span>Аналіз цін РДН<span class="d"></span><span class="p">3</span></div>
        <div><span class="n">10</span>Головний висновок і рекомендація<span class="d"></span><span class="p">7</span></div>
        <div><span class="n">05</span>Чи встигає 1 × 125 кВт зарядитися<span class="d"></span><span class="p">4</span></div>
        <div><span class="n">11</span>Дані для розрахунку окупності<span class="d"></span><span class="p">8</span></div>
        <div><span class="n">06</span>Порівняння варіантів<span class="d"></span><span class="p">5</span></div>
        <div style="border-bottom:none"></div>
      </div>
    </div>
  </div>
  ${foot(1)}
</div>

<!-- ============================ 2. ВИХІДНІ ДАНІ + ЧАС ============================ -->
<div class="page">
  ${head('Вихідні дані · Час заряду')}
  <section>
    ${sec('01', 'Вихідні дані', 'Потужність підприємства — приблизно 120 кВт. Обидва варіанти мають однакову ємність батарей, відрізняється лише інверторна потужність.')}
    <div class="grid2">
      <div class="variant v1">
        <div class="top"><div><span class="tag v1">Варіант 1</span><h3>1 × 125 кВт</h3></div>
          <div class="power"><b>125 кВт</b><small>макс. заряд / розряд</small></div></div>
        <div class="schema">
          <div><div class="grp inv">${I.inverter}</div><div class="lbl">інвертор</div></div>
          <span style="color:var(--muted);font-weight:800">+</span>
          <div><div class="grp bat">${rep(I.battery, 3)}</div><div class="lbl">3 батареї × 240</div></div>
        </div>
        <dl class="kv"><dt>Інвертор</dt><dd>1 × 125 кВт</dd><dt>Батареї</dt><dd>3 × 240 кВт·год</dd><dt>Загальна ємність</dt><dd>720 кВт·год</dd><dt>Макс. потужність заряду/розряду</dt><dd>125 кВт</dd></dl>
      </div>
      <div class="variant v2">
        <div class="top"><div><span class="tag v2">Варіант 2</span><h3>3 × 125 кВт</h3></div>
          <div class="power"><b>375 кВт</b><small>макс. заряд / розряд</small></div></div>
        <div class="schema">
          <div><div class="grp inv">${rep(I.inverter, 3)}</div><div class="lbl">3 інвертори</div></div>
          <span style="color:var(--muted);font-weight:800">+</span>
          <div><div class="grp bat">${rep(I.battery, 3)}</div><div class="lbl">3 батареї × 240</div></div>
        </div>
        <dl class="kv"><dt>Інвертори</dt><dd>3 × 125 кВт</dd><dt>Батареї</dt><dd>3 × 240 кВт·год</dd><dt>Загальна ємність</dt><dd>720 кВт·год</dd><dt>Макс. потужність заряду/розряду</dt><dd>375 кВт</dd></dl>
      </div>
    </div>
  </section>

  <section>
    ${sec('02', 'Час заряду і розряду', 'Скільки годин потрібно, щоб повністю зарядити або розрядити 720 кВт·год при різній потужності.')}
    <div class="fig">
      <div class="legend"><span><i class="sw" style="background:var(--v1)"></i>Варіант 1 · 1 × 125 кВт</span><span><i class="sw" style="background:var(--v2)"></i>Варіант 2 · 3 × 125 кВт</span><span><i class="sw h1"></i>додатковий час через втрати</span></div>
      ${timelineSVG()}
    </div>
    <div class="grid2" style="margin-top:3.4mm;gap:3.4mm 4.5mm">
      <div class="fcard"><div class="t"><span class="tag v1">Заряд · варіант 1</span></div>
        <div class="formula">720 ÷ 125 <span class="eq">=</span> 5,76 год</div>
        <div class="res"><span>Теоретично <b>5 год 46 хв</b></span><span>Реально <b>≈ 6–6,2 год</b></span></div></div>
      <div class="fcard"><div class="t"><span class="tag v2">Заряд · варіант 2</span></div>
        <div class="formula">720 ÷ 375 <span class="eq">=</span> 1,92 год</div>
        <div class="res"><span>Теоретично <b>1 год 55 хв</b></span><span>Реально <b>≈ 2–2,1 год</b></span></div></div>
      <div class="fcard"><div class="t"><span class="tag v1">Розряд за 8 годин</span></div>
        <div class="formula">720 ÷ 8 <span class="eq">=</span> 90 кВт</div>
        <p>Для розряду протягом 8 годин достатньо ≈ 90 кВт середньої потужності — <b>один інвертор 125 кВт для цього повністю підходить</b>.</p></div>
      <div class="fcard"><div class="t"><span class="tag v1">Розряд на повній потужності</span></div>
        <div class="formula">720 ÷ 125 <span class="eq">=</span> 5,76 год</div>
        <p>Повністю заряджена батарея на 125 кВт працюватиме ≈ 5,8 години. З урахуванням втрат — трохи менше.</p></div>
    </div>
  </section>
  ${foot(2)}
</div>

<!-- ============================ 3. ККД + РДН ============================ -->
<div class="page">
  ${head('ККД · Аналіз цін РДН')}
  <section>
    ${sec('03', 'ККД', 'Для розрахунку приймаємо ККД заряду ≈ 95 % і ККД розряду ≈ 95 %.')}
    <div class="flow">
      <div class="st"><b>100</b><span>кВт·год куплено<br>з мережі</span></div>
      <div class="op">× 0,95${I.arrow}<small>заряд</small></div>
      <div class="st"><b>95</b><span>кВт·год<br>у батареї</span></div>
      <div class="op">× 0,95${I.arrow}<small>розряд</small></div>
      <div class="st out"><b>≈ 90</b><span>кВт·год<br>на виході</span></div>
    </div>
    <p class="fine" style="margin-top:2.4mm">Загальний round-trip efficiency: <b style="color:var(--ink)">0,95 × 0,95 = 0,9025 ≈ 90 %</b>. Тобто з кожних 100 кВт·год, узятих із мережі, назад повертається приблизно 90 кВт·год.</p>
  </section>

  <section>
    ${sec('04', 'Аналіз цін РДН', 'Типові дешеві й дорогі години доби та середні ціни 6 найдешевших і 6 найдорожчих годин. Різниця між ними (спред) — валовий потенціал арбітражу на кожну МВт·год.')}
    <div class="fig">
      <div class="sub-h">Коли енергія дешева, а коли дорога</div>
      <div class="legend"><span><i class="sw" style="background:var(--cheap)"></i>типові дешеві години — заряд</span><span><i class="sw" style="background:var(--peak)"></i>типові дорогі години — розряд / продаж</span></div>
      ${stripsSVG()}
    </div>
    <div class="fig" style="margin-top:4mm">
      <div class="sub-h">Середня ціна 6 найдешевших і 6 найдорожчих годин, грн/МВт·год</div>
      <div class="legend"><span><i class="sw" style="background:var(--cheap);border-radius:50%"></i>6 найдешевших годин</span><span><i class="sw" style="background:var(--peak);border-radius:50%"></i>6 найдорожчих годин</span><span><b style="color:var(--ink)">Δ</b> — різниця (спред)</span></div>
      ${dumbbellSVG()}
    </div>
    <table class="tbl" style="margin-top:4mm">
      <thead><tr><th>Місяць 2026</th><th>Дешеві години</th><th>Дорогі години</th><th>6 найдешевших</th><th>6 найдорожчих</th><th>Різниця</th></tr></thead>
      <tbody>
        <tr><td><b>Січень</b></td><td>02:00–07:00</td><td>18:00–23:00</td><td>≈ 5 346</td><td>≈ 12 442</td><td class="hi">≈ 7 096</td></tr>
        <tr><td><b>Лютий</b></td><td>03:00–07:00 + окремі денні</td><td>17:00–22:00</td><td>≈ 6 013</td><td>≈ 13 778</td><td class="hi">≈ 7 765</td></tr>
        <tr><td><b>Вересень</b></td><td>11:00–16:00</td><td>19:00–23:00</td><td>≈ 726</td><td>≈ 11 599</td><td class="hi">≈ 10 873</td></tr>
      </tbody>
    </table>
    <p class="fine" style="margin-top:1.6mm">Ціни — грн/МВт·год. У вересні дешеве вікно зміщується на денні години, а спред — найбільший із трьох місяців.</p>
  </section>
  ${foot(3)}
</div>

<!-- ============================ 4. 28 ВЕРЕСНЯ + ЧИ ВСТИГАЄ ============================ -->
<div class="page">
  ${head('Аналіз цін РДН · Час заряду 1 × 125 кВт')}
  <section>
    <div class="sub-h" style="font-size:13pt">Приклад: 28 вересня 2026</div>
    <div style="display:grid;grid-template-columns:92mm 1fr;gap:6mm;align-items:stretch">
      <div class="fig" style="padding:3.4mm 3.6mm 2.4mm">${sept28SVG()}</div>
      <div style="display:flex;flex-direction:column;gap:3mm;justify-content:space-between">
        <table class="tbl">
          <thead><tr><th>Година</th><th>Ціна, грн/МВт·год</th></tr></thead>
          <tbody>
            <tr><td><span class="dot" style="background:var(--cheap)"></span>12:00–16:00</td><td>до ≈ 10</td></tr>
            <tr><td><span class="dot" style="background:var(--peak)"></span>20:00</td><td>≈ 11 500</td></tr>
            <tr><td><span class="dot" style="background:var(--peak)"></span>21:00</td><td class="hi">≈ 12 500</td></tr>
            <tr><td><span class="dot" style="background:var(--peak)"></span>22:00</td><td>≈ 9 500</td></tr>
            <tr><td><span class="dot" style="background:var(--peak)"></span>23:00</td><td>≈ 8 500</td></tr>
          </tbody>
        </table>
        <div class="callout good" style="flex-direction:column;gap:1.2mm">
          <h3>Дуже хороший день для батарейного арбітражу</h3>
          <p>Зарядитися вдень практично безкоштовно і використати або продати електроенергію ввечері.</p>
        </div>
      </div>
    </div>
  </section>

  <section>
    ${sec('05', 'Чи встигає 1 × 125 кВт зарядити 720 кВт·год?', 'Так. Приблизний результат моделювання повного циклу 720 кВт·год за цінами РДН:')}
    <div class="fig" style="padding-top:2mm;padding-bottom:2mm">
      <div class="prog"><div class="m">Січень</div><div class="bar">${rep('<i></i>', 31)}</div><div class="r">31 <small>із 31 дня</small></div></div>
      <div class="prog"><div class="m">Лютий</div><div class="bar">${rep('<i></i>', 23)}${rep('<i class="p"></i>', 5)}</div><div class="r">23 <small>із 28 днів</small></div>
        <div class="note">Ще декілька днів — майже повний цикл. Приблизно 8–9 лютого спред був недостатньо привабливим для нормального циклу.</div></div>
      <div class="prog"><div class="m">Вересень</div><div class="bar">${rep('<i></i>', 27)}${rep('<i class="p"></i>', 1)}</div><div class="r">27 <small>із 28 днів</small></div></div>
    </div>
    <div class="legend" style="margin-top:2mm"><span><i class="sw" style="background:var(--good)"></i>повний цикл</span><span><i class="sw" style="background:repeating-linear-gradient(45deg,#9aa6b8 0 1.5px,#fff 1.5px 4px);border:1.5px solid #9aa6b8"></i>неповний або недоцільний цикл</span></div>

    <div class="grid2" style="margin-top:3mm;grid-template-columns:1fr 1.15fr">
      <div class="callout note" style="flex-direction:column;gap:1.6mm">
        <h3>Висновок</h3>
        <p><b>6 годин зарядки не є критичною проблемою.</b> Система не зобов'язана заряджатися 6 годин поспіль — вона добирає найдешевші години доби, де б вони не були.</p>
      </div>
      <div class="fig" style="padding:3.4mm 4mm">
        <div class="eyebrow">Приклад розбиття заряду</div>
        <div style="font:700 10.5pt 'Inter Display';color:var(--navy);margin-top:1mm">2 години вночі + 4 години вдень</div>
        <div class="daystrip">${Array.from({ length: 24 }, (_, h) => `<i class="${(h >= 3 && h < 5) || (h >= 11 && h < 15) ? 'c' : ''}"></i>`).join('')}</div>
        <div class="dayaxis"><span>00</span><span>03</span><span>06</span><span>09</span><span>12</span><span>15</span><span>18</span><span>21</span></div>
        <p class="fine" style="margin-top:1.4mm">Ілюстрація: заряд у ті години, які саме цього дня найдешевші.</p>
      </div>
    </div>
  </section>
  ${foot(4)}
</div>

<!-- ============================ 5. ПОРІВНЯННЯ ============================ -->
<div class="page">
  ${head('Порівняння варіантів')}
  <section>
    ${sec('06', 'Порівняння варіантів', 'Переваги та недоліки кожної конфігурації з однаковою ємністю 720 кВт·год.')}
    <div class="grid2" style="align-items:stretch">
      <div class="pc v1">
        <div class="top"><div><span>Варіант 1</span><h3>1 × 125 кВт + 720 кВт·год</h3></div></div>
        <div class="body">
          <div><div class="lbl">Переваги</div>
          <ul class="ticks">
            <li>${I.check}<span>Нижча вартість обладнання.</span></li>
            <li>${I.check}<span>125 кВт майже повністю відповідає потужності підприємства 120 кВт.</span></li>
            <li>${I.check}<span>Можна зарядити 720 кВт·год приблизно за 6 годин.</span></li>
            <li>${I.check}<span>Можна розряджати приблизно 8 годин по 90 кВт.</span></li>
            <li>${I.check}<span>Можна повністю закривати більшу частину дорогого періоду.</span></li>
            <li>${I.check}<span>У більшості днів є достатньо дешевих годин для повного заряду.</span></li>
            <li>${I.check}<span>Немає необхідності переплачувати за 375 кВт інверторної потужності, якщо основна ціль — власне споживання.</span></li>
          </ul></div>
          <div><div class="lbl">Недолік</div>
          <ul class="ticks">
            <li>${I.minus}<span>Неможливо швидко продати всю батарею за 1–2 найдорожчі години: для розряду 720 кВт·год при 125 кВт потрібно ≈ 5,8 години.</span></li>
          </ul></div>
        </div>
      </div>
      <div class="pc v2">
        <div class="top"><div><span>Варіант 2</span><h3>3 × 125 кВт + 720 кВт·год</h3></div></div>
        <div class="body">
          <div><div class="lbl">Переваги</div>
          <ul class="ticks">
            <li>${I.check}<span>Максимальна потужність — <b>375 кВт</b>.</span></li>
            <li>${I.check}<span>Повний заряд — приблизно <b>2 години</b>.</span></li>
            <li>${I.check}<span>Повний розряд — приблизно <b>2 години</b>.</span></li>
            <li>${I.check}<span>Можна максимально використовувати 2 найдешевші години дня.</span></li>
            <li>${I.check}<span>Можна продати енергію саме у 2–3 найдорожчі години.</span></li>
            <li>${I.check}<span>Набагато цікавіший варіант для активної торгівлі електроенергією.</span></li>
          </ul></div>
          <div><div class="lbl">Недоліки</div>
          <ul class="ticks">
            <li>${I.minus}<span>Значно більша вартість.</span></li>
            <li>${I.minus}<span>Для підприємства з навантаженням ≈ 120 кВт велика частина потужності 375 кВт не потрібна.</span></li>
            <li>${I.minus}<span>Головна перевага з'являється лише тоді, коли дозволено продавати значну потужність у мережу.</span></li>
          </ul></div>
        </div>
      </div>
    </div>
  </section>

  <section>
    <div class="sub-h">Порівняння в цифрах</div>
    <table class="tbl">
      <thead><tr><th>Показник</th><th><span class="dot" style="background:var(--v1)"></span>1 × 125 кВт</th><th><span class="dot" style="background:var(--v2)"></span>3 × 125 кВт</th></tr></thead>
      <tbody>
        <tr><td>Макс. потужність заряду / розряду</td><td>125 кВт</td><td class="hi">375 кВт</td></tr>
        <tr><td>Ємність батарей</td><td>720 кВт·год</td><td>720 кВт·год</td></tr>
        <tr><td>Повний заряд (теоретично / реально)</td><td>5,76 год / ≈ 6–6,2 год</td><td class="hi">1,92 год / ≈ 2–2,1 год</td></tr>
        <tr><td>Повний розряд на макс. потужності</td><td>≈ 5,8 год</td><td class="hi">≈ 2 год</td></tr>
        <tr><td>Відповідність навантаженню 120 кВт</td><td class="hi">майже точна</td><td>надлишкова</td></tr>
        <tr><td>Вартість обладнання</td><td class="hi">нижча</td><td>значно більша</td></tr>
        <tr><td>Оптимальне застосування</td><td class="hi">власне споживання</td><td class="hi">активна торгівля</td></tr>
      </tbody>
    </table>
  </section>
  ${foot(5)}
</div>

<!-- ============================ 6. МАРЖА + ЧОМУ 375 ============================ -->
<div class="page">
  ${head('Валова маржа')}
  <section>
    ${sec('07', 'Приблизна валова маржа', 'Щомісячна валова маржа двох конфігурацій за цінами РДН — окремо для власного споживання і для випадку, коли дозволено продавати електроенергію.')}
    <div class="legend"><span><i class="sw" style="background:var(--v1)"></i>1 × 125 кВт</span><span><i class="sw" style="background:var(--v2)"></i>3 × 125 кВт</span><span style="color:#0f7a41;font-weight:700">+ перевага 3 × 125, тис. грн</span></div>
    <div class="grid2">
      <div class="fig"><div class="sub-h">Власне споживання підприємства</div>
        ${marginSVG('Валова маржа — власне споживання', [{ m: 'Січень', a: 138, b: 145, d: '+6,6' }, { m: 'Лютий', a: 136, b: 148, d: '+11,5' }, { m: 'Вересень', a: 198, b: 206, d: '+7,7' }], 'перевага відносно невелика')}</div>
      <div class="fig"><div class="sub-h">Якщо дозволено продавати</div>
        ${marginSVG('Валова маржа — з продажем', [{ m: 'Січень', a: 140, b: 162, d: '+22' }, { m: 'Лютий', a: 137, b: 157, d: '+20' }, { m: 'Вересень', a: 200, b: 240, d: '+40' }], 'перевага відчутна')}</div>
    </div>
    <table class="tbl" style="margin-top:4mm">
      <thead>
        <tr class="grp"><th></th><th colspan="3"><span>Власне споживання, грн/міс</span></th><th colspan="3"><span>З продажем, грн/міс</span></th></tr>
        <tr><th>Місяць</th><th>1 × 125</th><th>3 × 125</th><th>Різниця</th><th>1 × 125</th><th>3 × 125</th><th>Перевага</th></tr>
      </thead>
      <tbody>
        <tr><td><b>Січень</b></td><td>≈ 138 000</td><td>≈ 145 000</td><td class="pos">+6 600</td><td>≈ 140 000</td><td>≈ 162 000</td><td class="pos">+22 000</td></tr>
        <tr><td><b>Лютий</b></td><td>≈ 136 000</td><td>≈ 148 000</td><td class="pos">+11 500</td><td>≈ 137 000</td><td>≈ 157 000</td><td class="pos">+20 000</td></tr>
        <tr><td><b>Вересень</b></td><td>≈ 198 000</td><td>≈ 206 000</td><td class="pos">+7 700</td><td>≈ 200 000</td><td>≈ 240 000</td><td class="pos">+40 000</td></tr>
      </tbody>
    </table>
    <div class="grid2" style="margin-top:4mm">
      <div class="callout note" style="flex-direction:column;gap:1.2mm"><h3>Висновок для власного споживання</h3>
        <p>Додаткові 2 інвертори дають відносно невелику перевагу. Підприємство споживає ≈ 120 кВт, тому система 375 кВт не може повністю використати свою потужність лише на підприємстві.</p></div>
      <div class="callout good" style="flex-direction:column;gap:1.2mm"><h3>Якщо дозволено продавати</h3>
        <p>Результат змінюється: 3 × 125 кВт дає <b>+20…40 тис. грн на місяць</b> більше, бо продає енергію саме в пікові години.</p></div>
    </div>
  </section>

  <section>
    ${sec('08', 'Чому 375 кВт краще для продажу')}
    <div class="fig">
      ${equalAreaSVG()}
      <div class="fig-cap">Площа прямокутника = потужність × час = та сама енергія 720 кВт·год. При 375 кВт її можна продати практично за 2 найдорожчі години (720 ÷ 375 = 1,92 год), при 125 кВт — лише за ≈ 6 годин (720 ÷ 125 = 5,76 год).</div>
    </div>
  </section>
  ${foot(6)}
</div>

<!-- ============================ 7. ПРИЄДНАННЯ + ВИСНОВОК ============================ -->
<div class="page">
  ${head('Потужність приєднання · Висновок')}
  <section>
    ${sec('09', 'Важливо: потужність приєднання')}
    <div class="callout warn" style="flex-direction:column;align-items:stretch;gap:3.4mm;padding:5mm">
      <div style="display:flex;gap:3mm;align-items:flex-start">${I.warn}
        <p style="font-size:9.4pt"><b>Якщо 120 кВт — це не фактичне споживання, а дозволена потужність точки приєднання</b>, то три інвертори можуть не дати можливості заряджатися на 375 кВт.</p></div>
      <div>
        <div class="eyebrow" style="margin-bottom:1.6mm">Приклад: одночасне споживання з мережі</div>
        <div class="stack">
          <div style="flex:120;background:#33455f">120 кВт</div>
          <div style="flex:375;background:var(--v2)">375 кВт</div>
        </div>
        <div style="display:flex;gap:2px;font-size:7.8pt;color:var(--ink2);margin-top:1mm"><span style="flex:120;text-align:center">підприємство</span><span style="flex:375;text-align:center">заряд батареї (3 × 125 кВт)</span></div>
        <div style="display:flex;justify-content:flex-end;align-items:baseline;gap:2mm;margin-top:1.8mm">
          <span class="fine">загальне споживання з мережі</span><span class="formula" style="font-size:14pt">120 + 375 = 495 кВт</span></div>
      </div>
      <div>
        <p style="font-size:8.8pt">Тобто повинні дозволяти приблизно <b>495 кВт</b>:</p>
        <div class="chk"><div><i></i>точка приєднання</div><div><i></i>трансформатор</div><div><i></i>кабельна лінія</div><div><i></i>договір з оператором</div></div>
      </div>
      <p style="font-size:8.8pt;border-top:1px solid #f0d58c;padding-top:3mm">Так само треба окремо перевірити <b>максимально дозволену потужність видачі в мережу</b>. Якщо дозволено віддавати лише 125 кВт, то встановлення 375 кВт інверторів для продажу майже втрачає сенс.</p>
    </div>
  </section>

  <section>
    ${sec('10', 'Головний висновок')}
    <div class="concl">
      <div class="c v1">
        <div class="eyebrow">Якщо головна задача</div>
        <div class="task"><div>Заряджатися дешево</div><div class="pl">+</div><div>Закривати власне споживання підприємства 120 кВт у дорогі години</div></div>
        <div class="ans">${I.arrow}<div><div class="eyebrow">оптимально</div><div class="res">1 × 125 кВт + 720 кВт·год</div></div></div>
      </div>
      <div class="c v2">
        <div class="eyebrow">Якщо головна задача</div>
        <div class="task"><div>Зарядитися в 1–2 найдешевші години</div><div class="pl">+</div><div>Продати практично всю батарею в 1–2 найдорожчі години</div></div>
        <div class="ans">${I.arrow}<div><div class="eyebrow">набагато цікавіше</div><div class="res">3 × 125 кВт + 720 кВт·год</div></div></div>
      </div>
    </div>
  </section>

  <section>
    <div class="reco">
      <div class="eyebrow">Попередня рекомендація</div>
      <h3>Вибір залежить від того, чи гарантовано можна продавати 375 кВт</h3>
      <div class="row"><p>Продаж активному споживачу — <b style="color:#fff">додаткова можливість</b>, а не основний бізнес</p>${I.arrow}
        <div class="res"><span class="pill" style="background:var(--v1)"></span>1 × 125 кВт + 720 кВт·год<small>інвертор під навантаження підприємства</small></div></div>
      <div class="row"><p><b style="color:#fff">Гарантовано</b> можна продавати до 375 кВт і купувати / заряджати на такій самій потужності</p>${I.arrow}
        <div class="res"><span class="pill" style="background:var(--v2)"></span>3 × 125 кВт + 3 × 240 кВт·год<small>може бути економічно цікавішим</small></div></div>
    </div>
  </section>
  ${foot(7)}
</div>

<!-- ============================ 8. ДАНІ ДЛЯ ОКУПНОСТІ ============================ -->
<div class="page">
  ${head('Дані для розрахунку окупності')}
  <section>
    ${sec('11', 'Для точного розрахунку окупності потрібні ще 5 показників', 'Заповніть і поверніть — після цього можна порахувати окупність кожного варіанта.')}
    <div class="form">
      <div class="fld"><div class="n">1</div><div class="q">Ціна одного інвертора 125 кВт</div><div class="line"><i></i>грн</div></div>
      <div class="fld"><div class="n">2</div><div class="q">Ціна однієї батареї 240 кВт·год</div><div class="line"><i></i>грн</div></div>
      <div class="fld"><div class="n">3</div><div class="q">Максимальна дозволена потужність імпорту з мережі<small>скільки можна одночасно споживати з мережі</small></div><div class="line"><i></i>кВт</div></div>
      <div class="fld"><div class="n">4</div><div class="q">Максимальна дозволена потужність експорту в мережу<small>скільки можна одночасно віддавати в мережу</small></div><div class="line"><i></i>кВт</div></div>
      <div class="fld" style="border-bottom:none;padding-bottom:1mm"><div class="n">5</div><div class="q" style="grid-column:2 / 4">Формула продажу електроенергії активному споживачу</div></div>
      <div class="opts">
        <div><span class="box"></span>РДН</div>
        <div><span class="box"></span>РДН мінус комісія<i></i>%</div>
        <div><span class="box"></span>Фіксована ціна<i></i>грн/МВт·год</div>
        <div><span class="box"></span>Інша формула<i></i></div>
      </div>
      <div style="border-bottom:1px solid var(--line);margin-top:3mm"></div>
    </div>
  </section>

  <section>
    <div class="sub-h" style="font-size:12pt;margin-bottom:3.6mm">Після цього можна точно порахувати</div>
    <div class="calc">
      <div class="g"><h4>Вартість</h4><ul><li>1 × 125 кВт +<br>720 кВт·год</li><li>3 × 125 кВт +<br>720 кВт·год</li></ul></div>
      <div class="g"><h4>Дохід</h4><ul><li>за кожен день</li><li>за місяць</li><li>за рік</li></ul></div>
      <div class="g"><h4>Батарея</h4><ul><li>втрати батареї</li><li>вартість одного циклу</li><li>деградацію батареї</li></ul></div>
      <div class="g"><h4>Ефект</h4><ul><li>економію на власному споживанні</li><li>прибуток від продажу надлишків</li></ul></div>
      <div class="g"><h4>Окупність</h4><ul><li>одного інвертора</li><li>трьох інверторів</li><li>за скільки років окупляться додаткові два інвертори</li></ul></div>
    </div>
  </section>

  <section>
    <div class="callout note" style="flex-direction:column;gap:1.2mm">
      <h3>Примітки</h3>
      <p class="fine" style="color:var(--ink2)">Усі значення приблизні й отримані моделюванням на цінах РДН за січень, лютий і вересень 2026 року. Валова маржа не враховує вартість обладнання; втрати, вартість циклу та деградацію батареї буде враховано в точному розрахунку окупності. ККД прийнято: заряд ≈ 95 %, розряд ≈ 95 %, round-trip ≈ 90 %.</p>
    </div>
  </section>

  <section>
    <div class="sub-h">Коментарі / додаткові умови</div>
    <div class="ruled"><i></i><i></i><i></i></div>
  </section>

  <section style="margin-top:auto">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10mm;padding-bottom:1mm">
      <div><div class="eyebrow">Підготував</div><div style="border-bottom:1.3px solid var(--ink2);height:9mm"></div><div class="fine" style="margin-top:1mm">ПІБ, підпис</div></div>
      <div><div class="eyebrow">Отримав / погоджено</div><div style="border-bottom:1.3px solid var(--ink2);height:9mm"></div><div class="fine" style="margin-top:1mm">ПІБ, підпис, дата</div></div>
    </div>
  </section>
  ${foot(8)}
</div>

</body>
</html>`;

/* ================================================================ render */
// нерозривні пробіли: число + одиниця, «≈ 90», «3 × 125» не розриваються між рядками
const tidy = html
  .replace(/(\d) (?=(кВт|год|грн|МВт|днів|дня|хв|години|годин|тис|%))/g, `$1${NB}`)
  .replace(/≈ /g, `≈${NB}`)
  .replace(/(\d) × (?=\d)/g, `$1${NB}×${NB}`);
const outHtml = path.join(here, 'report.html');
writeFileSync(outHtml, tidy);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 900, height: 1200 }, deviceScaleFactor: 2 });
await page.goto('file://' + outHtml);
await page.evaluate(() => document.fonts.ready);
const overflow = await page.evaluate(() => [...document.querySelectorAll('.page')].map((p, i) => {
  const foot = p.querySelector('.run-foot');
  const limit = foot ? foot.getBoundingClientRect().top : p.getBoundingClientRect().bottom;
  let maxBottom = 0;
  p.querySelectorAll(':scope > *:not(.run-foot)').forEach(el => { maxBottom = Math.max(maxBottom, el.getBoundingClientRect().bottom); });
  return { page: i + 1, free_px: Math.round(limit - maxBottom) };
}));
console.table(overflow);
await page.pdf({ path: path.join(here, 'BESS-720-analiz.pdf'), format: 'A4', printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 }, preferCSSPageSize: true });
if (process.argv.includes('--png')) {
  const dir = process.env.PNG_DIR || path.join(here, 'preview');
  mkdirSync(dir, { recursive: true });
  await page.emulateMedia({ media: 'print' });
  const pages = await page.$$('.page');
  for (let i = 0; i < pages.length; i++) await pages[i].screenshot({ path: path.join(dir, `page-${i + 1}.png`) });
}
await browser.close();
console.log('ok');
