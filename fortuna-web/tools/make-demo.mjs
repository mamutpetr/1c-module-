#!/usr/bin/env node
// ФОРТУНА — deterministic demo-data generator (format "fortuna-data" v1, see docs/CONTRACT.md).
//
//   node tools/make-demo.mjs           build, self-check, write src/demo-data.js + demo/fortuna-demo.json
//   node tools/make-demo.mjs --check   build and self-check only (writes nothing)
//
// World: a Ukrainian plant making frozen semi-finished foods (вареники, пельмені, сирники, млинці, хінкалі,
// галушки, котлети, чебуреки). Recipes are per 1000 kg of finished product, purchase prices are the last
// receipts (without VAT), sales are the last shipment per product, priced per box without VAT.
//
// Every run produces byte-identical output: quantities come from a seeded PRNG (one stream per recipe/product),
// ids are hashes of stable keys formatted as lower-case UUIDs. The generator recomputes the catalogue exactly
// like the form v5.0 (ЗагрузитьВсеНаСервере + UX40_ОбойтиДерево + UX40_ТипПроблемы) and refuses to write
// anything if the margin distribution or a required edge case is missing.

import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT_JS = join(ROOT, 'src', 'demo-data.js');
const OUT_JSON = join(ROOT, 'demo', 'fortuna-demo.json');
const CORE_JS = join(ROOT, 'src', 'core.js');
const CHECK_ONLY = process.argv.includes('--check');

const SEED = 'fortuna-demo-v1';
const GENERATED_AT = '2026-10-14T09:30:00';
const BATCH_KG = 1000;
const PROCESSING_PER_TON = 50000;
const HISTORY_TAG = 'v3.3 грн/кг; переробка 50000 грн/т';
const MARGIN_THRESHOLD = 20;
const STALE_DAYS = 90;

// ============================================================================
// Deterministic helpers
// ============================================================================

function cyrb128(str) {
  let h1 = 1779033703, h2 = 3144134277, h3 = 1013904242, h4 = 2773480762;
  for (let i = 0, k; i < str.length; i++) {
    k = str.charCodeAt(i);
    h1 = h2 ^ Math.imul(h1 ^ k, 597399067);
    h2 = h3 ^ Math.imul(h2 ^ k, 2869860233);
    h3 = h4 ^ Math.imul(h3 ^ k, 951274213);
    h4 = h1 ^ Math.imul(h4 ^ k, 2716044179);
  }
  h1 = Math.imul(h3 ^ (h1 >>> 18), 597399067);
  h2 = Math.imul(h4 ^ (h2 >>> 22), 2869860233);
  h3 = Math.imul(h1 ^ (h3 >>> 17), 951274213);
  h4 = Math.imul(h2 ^ (h4 >>> 19), 2716044179);
  h1 ^= h2 ^ h3 ^ h4; h2 ^= h1; h3 ^= h1; h4 ^= h1;
  return [h1 >>> 0, h2 >>> 0, h3 >>> 0, h4 >>> 0];
}

function mulberry32(a) {
  return function next() {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Independent PRNG stream per key, so adding a recipe never reshuffles the others. */
function rngFor(key) {
  const next = mulberry32(cyrb128(SEED + '|' + key)[0]);
  return {
    next,
    range: (min, max) => min + (max - min) * next(),
    q: (min, max, step = 0.5) => round(Math.round((min + (max - min) * next()) / step) * step, 3),
    int: (min, max) => min + Math.floor(next() * (max - min + 1)),
    pick: (arr) => arr[Math.floor(next() * arr.length)],
    shuffle: (arr) => {
      const a = arr.slice();
      for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(next() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
      return a;
    },
  };
}

/** Lower-case UUID (v4 layout) derived from a stable key. */
function makeId(kind, key) {
  const hex = cyrb128(`${SEED}/${kind}/${key}`).map((n) => n.toString(16).padStart(8, '0')).join('');
  const v = hex.slice(0, 12) + '4' + hex.slice(13, 16) + ((parseInt(hex[16], 16) & 3) | 8).toString(16) + hex.slice(17, 32);
  return `${v.slice(0, 8)}-${v.slice(8, 12)}-${v.slice(12, 16)}-${v.slice(16, 20)}-${v.slice(20, 32)}`;
}

/** 1C Окр(x, n): half away from zero, on the decimal representation (no binary drift). */
function round(x, digits = 0) {
  if (typeof x !== 'number' || !isFinite(x)) return x;
  const shift = (v, d) => { const [m, e] = String(v).split('e'); return Number(m + 'e' + ((Number(e) || 0) + d)); };
  const r = shift(Math.round(shift(Math.abs(x), digits)), -digits);
  return r === 0 ? 0 : (x < 0 ? -r : r);
}

/** True if rounding x to `digits` decimals is (numerically) a .5 tie — avoided so every implementation agrees. */
function nearTie(x, digits) {
  const s = Math.abs(x) * Math.pow(10, digits);
  return Math.abs(s - Math.floor(s) - 0.5) < 1e-6;
}

const comma = (n) => String(n).replace('.', ',');
const ddmmyyyy = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
const isoToMs = (iso) => Date.parse(iso + 'Z');
const daysBefore = (isoA, isoB) => (isoToMs(isoB) - isoToMs(isoA)) / 86400000;

// ============================================================================
// BSL ports used by the generator and the self-check
// ============================================================================

/** ЭтоГривнаИлиПусто */
function isUah(currency) {
  const t = String(currency == null ? '' : currency).trim().toLowerCase();
  return t === '' || t.includes('uah') || t.includes('грн') || t.includes('грив');
}

/** ИзвлечьВесЯщикаКг */
function extractBoxKg(unit) {
  const text = String(unit == null ? '' : unit).trim().toLowerCase();
  if (!text) return 0;
  if (text === 'кг' || text === 'кілограм') return 1;
  const posKg = text.indexOf('кг');
  if (posKg < 0) return 0;
  const posBracket = text.lastIndexOf('(', posKg);
  let num = posBracket >= 0 ? text.slice(posBracket + 1, posKg) : text.slice(0, posKg);
  num = num.trim().replace(/ /g, '').replace(/\./g, ',');
  if (!num || !/^[0-9]*,?[0-9]*$/.test(num)) return 0;
  const kg = Number(num.replace(',', '.'));
  return kg > 0 && kg <= 1000 ? kg : 0;
}

const CATEGORY_PATHS = {
  UA_RUD: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Рудь'],
  UA_SILPO: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Сільпо'],
  UA_METRO: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Метро'],
  UA_FEDYK: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Привати', 'Федик'],
  UA_OP: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Привати', 'ОП'],
  UA_MIDAS: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Привати', 'Мидас'],
  EX_DOVGAN: ['ВИКОРИСТОВУЮТЬСЯ', 'ЕКСПОРТ', 'Довгань'],
  EX_ITALY: ['ВИКОРИСТОВУЮТЬСЯ', 'ЕКСПОРТ', 'Італія'],
  EX_ROMANIA: ['ВИКОРИСТОВУЮТЬСЯ', 'ЕКСПОРТ', 'Румунія'],
  EX_GEYA: ['ВИКОРИСТОВУЮТЬСЯ', 'ЕКСПОРТ', 'Гея Фуд'],
  EX_CZECH: ['ВИКОРИСТОВУЮТЬСЯ', 'ЕКСПОРТ', 'Чехія'],
  EX_ISRAEL: ['ВИКОРИСТОВУЮТЬСЯ', 'ЕКСПОРТ', 'Ізраїль'],
};
const CATEGORY_CODES = Object.keys(CATEGORY_PATHS);
const FOLDER_NONE = ['ВИКОРИСТОВУЮТЬСЯ', 'Без категорії'];
const FOLDER_OLD = ['НЕ ВИКОРИСТОВУЮТЬСЯ'];
const FOLDER_ORDER = [...CATEGORY_CODES.map((c) => CATEGORY_PATHS[c].join(' / ')), FOLDER_NONE.join(' / '), FOLDER_OLD.join(' / ')];

/** UX40_ТипПроблемы */
function problemType(r, threshold) {
  const st = String(r.dataStatus || '').toUpperCase();
  if (r.materials === 0) return 'НЕМАЄ СКЛАДУ';
  if (r.materials !== r.pricesFound) return 'НЕМАЄ ЦІН: ' + (r.materials - r.pricesFound);
  if (st.includes('ВАГУ')) return 'НЕ ВИЗНАЧЕНО ВАГУ';
  if (st.includes('ВАЛЮТ') || st.includes('ПДВ')) return 'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ';
  if (r.sale <= 0) return 'НЕМАЄ ЦІНИ ПРОДАЖУ';
  if (r.sale < r.cost) return 'ЗБИТКОВА ПОЗИЦІЯ';
  if (r.margin < threshold) return 'НИЗЬКА МАРЖА';
  return 'OK';
}

/**
 * Catalogue exactly as ЗагрузитьВсеНаСервере + UX40_ОбойтиДерево build it, from the contract document alone.
 * Returned in tree (depth-first) order.
 */
function computeCatalogue(data, threshold = MARGIN_THRESHOLD) {
  const specById = new Map(data.specs.map((s) => [s.id, s]));
  const recs = new Map();
  for (const row of data.rows) {
    if (!row.spec || !row.material) continue;
    let rec = recs.get(row.spec);
    if (!rec) {
      const spec = specById.get(row.spec);
      const old = String(spec.status || '').trim().toLowerCase().includes('стар');
      const code = String(spec.category || '').trim();
      const folder = old ? FOLDER_OLD : (CATEGORY_PATHS[code] || FOLDER_NONE);
      rec = {
        id: spec.id, spec, productId: spec.product,
        name: data.products[spec.product] + ' — ' + spec.name,
        categoryCode: CATEGORY_PATHS[code] ? code : '', categoryPath: folder.join(' / '), active: !old,
        materials: 0, pricesFound: 0, costSum: 0, seq: recs.size,
      };
      recs.set(row.spec, rec);
    }
    rec.materials += 1;
    const price = data.purchasePrices[row.material + '|' + (row.char || '')];
    if (!price || !isUah(price.currency)) continue;
    rec.pricesFound += 1;
    rec.costSum += row.qty * price.exVat;
  }
  const list = [...recs.values()];
  for (const r of list) {
    const methodology = data.methodology || {};
    const perTon = methodology.processingPerTon ?? PROCESSING_PER_TON;
    const batch = methodology.batchKg ?? BATCH_KG;
    r.costRaw = (r.costSum + perTon) / batch;
    r.cost = round(r.costRaw, 4);
    r.sale = 0; r.markup = 0; r.saleRaw = null;
    r.dataStatus = r.materials === r.pricesFound ? 'OK' : 'НЕМАЄ ЦІН: ' + (r.materials - r.pricesFound);
    const s = data.sales[r.productId];
    r.saleInfo = s || null;
    if (!s) r.dataStatus += '; НЕМАЄ ПРОДАЖУ';
    else if (s.status !== 'OK') r.dataStatus += '; ' + s.status;
    else if (!(s.boxKg > 0)) r.dataStatus += '; НЕ ВИЗНАЧЕНО ВАГУ ЯЩИКА: ' + s.unit;
    else {
      r.saleRaw = s.exVat / s.boxKg;
      r.sale = round(r.saleRaw, 4);
      if (r.materials === r.pricesFound && r.materials > 0 && r.cost > 0) {
        r.markupRaw = (r.sale - r.cost) / r.cost * 100;
        r.markup = round(r.markupRaw, 2);
      }
    }
    r.fullCost = r.materials > 0 && r.materials === r.pricesFound && r.cost > 0;
    r.hasSale = r.sale > 0;
    r.hasMarkup = r.fullCost && r.hasSale;
    r.margin = 0; r.marginRaw = null;
    if (r.fullCost && r.sale > 0) { r.marginRaw = (r.sale - r.cost) / r.sale * 100; r.margin = round(r.marginRaw, 2); }
    r.problem = problemType(r, threshold);
  }
  list.sort((a, b) => FOLDER_ORDER.indexOf(a.categoryPath) - FOLDER_ORDER.indexOf(b.categoryPath) || a.seq - b.seq);
  return list;
}

// History snapshot helpers (ЗагрузитьИсториюКалькуляций / СнимкиОтличаются)
function snapFromRecipe(r) {
  return { sale: r.sale, cost: r.cost, markup: r.markup, materials: r.materials, pricesFound: r.pricesFound,
    hasSale: r.hasSale, fullCost: r.fullCost, hasMarkup: r.hasMarkup };
}
function snapFromHistory(h) {
  const hasSale = h.sale > 0;
  const fullCost = h.materials > 0 && h.materials === h.pricesFound && h.cost > 0;
  return { ...h, hasSale, fullCost, hasMarkup: hasSale && fullCost };
}
function snapshotsDiffer(a, b) {
  if (!b) return true;
  return round(a.sale, 2) !== round(b.sale, 2) || round(a.cost, 2) !== round(b.cost, 2)
    || round(a.markup, 2) !== round(b.markup, 2) || a.hasSale !== b.hasSale || a.fullCost !== b.fullCost
    || a.hasMarkup !== b.hasMarkup || a.materials !== b.materials || a.pricesFound !== b.pricesFound;
}
/** Which history entry the form shows as "Було" (null, 0 or 1). */
function prevIndex(r, hist) {
  if (!hist || !hist.length) return null;
  if (!snapshotsDiffer(snapFromRecipe(r), snapFromHistory(hist[0])) && hist[1]) return 1;
  return 0;
}

// ============================================================================
// Product world: materials and last purchase receipts
// ============================================================================

// price: for vat 'incl' it is the document price WITH VAT (exVat = price / 1.2, 4 decimals, like the BSL query);
// for 'excl' it is the price without VAT (withVat = price * 1.2); for 'none' (ФОП / import) both are equal.
// date: last receipt; sup: supplier tag (same date + supplier = same receipt document).
const MATERIALS = [
  // --- сировина ---
  { key: 'flour_vg', name: 'Борошно пшеничне в/г', unit: 'кг', price: 19.5, vat: 'incl', date: '2026-09-02T10:14:00', sup: 'mlyn' },
  { key: 'flour_1', name: 'Борошно пшеничне 1 ґатунку', unit: 'кг', price: 17.3, vat: 'incl', date: '2026-09-02T10:14:00', sup: 'mlyn' },
  { key: 'semolina', name: 'Крупа манна', unit: 'кг', price: 30.96, vat: 'incl', date: '2026-08-19T11:30:00', sup: 'bakal' },
  { key: 'starch', name: 'Крохмаль картопляний', unit: 'кг', price: 57.0, vat: 'incl', date: '2026-08-19T11:30:00', sup: 'bakal' },
  { key: 'potato', name: 'Картопля', unit: 'кг', price: 12.0, vat: 'none', date: '2026-10-06T07:40:00', sup: 'fop_ovochi' },
  { key: 'onion', name: 'Цибуля ріпчаста', unit: 'кг', price: 13.5, vat: 'none', date: '2026-10-06T07:40:00', sup: 'fop_ovochi' },
  { key: 'cabbage', name: 'Капуста білокачанна', unit: 'кг', price: 9.2, vat: 'none', date: '2026-10-06T07:40:00', sup: 'fop_ovochi' },
  { key: 'carrot', name: 'Морква столова', unit: 'кг', price: 11.0, vat: 'none', date: '2026-10-06T07:40:00', sup: 'fop_ovochi' },
  { key: 'mushroom', name: 'Печериці свіжі', unit: 'кг', price: 68.0, vat: 'excl', date: '2026-10-03T08:05:00', sup: 'gryby' },
  { key: 'pork', name: 'Свинина лопатка н/ж', unit: 'кг', price: 207.0, vat: 'incl', date: '2026-10-08T06:55:00', sup: 'myaso' },
  { key: 'beef', name: 'Яловичина 2 ґатунку', unit: 'кг', price: 295.2, vat: 'incl', date: '2026-10-08T06:55:00', sup: 'myaso' },
  { key: 'lard', name: 'Шпик свинячий', unit: 'кг', price: 103.2, vat: 'incl', date: '2026-10-08T06:55:00', sup: 'myaso' },
  { key: 'chicken', name: 'Філе куряче', unit: 'кг', price: 175.0, vat: 'incl', date: '2026-10-09T07:20:00', sup: 'ptytsia' },
  { key: 'liver', name: 'Печінка куряча', unit: 'кг', price: 85.8, vat: 'incl', date: '2026-10-09T07:20:00', sup: 'ptytsia' },
  { key: 'ham', name: 'Шинка варена', unit: 'кг', price: 196.0, vat: 'excl', date: '2026-09-24T09:10:00', sup: 'kovbasy' },
  { key: 'cherry', name: 'Вишня с/м без кісточки', unit: 'кг', price: 88.0, vat: 'excl', date: '2026-08-28T13:00:00', sup: 'frost' },
  { key: 'strawberry', name: 'Полуниця с/м', unit: 'кг', price: 96.5, vat: 'excl', date: '2026-08-28T13:00:00', sup: 'frost' },
  { key: 'blueberry', name: 'Чорниця с/м', unit: 'кг', price: 158.0, vat: 'excl', date: '2026-09-11T10:45:00', sup: 'frost2' },
  { key: 'apple', name: 'Яблуко с/м (кубик)', unit: 'кг', price: 38.0, vat: 'excl', date: '2026-09-11T10:45:00', sup: 'frost2' },
  { key: 'parsley', name: 'Петрушка с/м', unit: 'кг', price: 94.0, vat: 'excl', date: '2026-09-11T10:45:00', sup: 'frost2' },
  { key: 'cottage', name: 'Сир кисломолочний', unit: 'кг', price: 116.16, vat: 'incl', date: '2026-09-29T08:15:00', sup: 'moloko' },
  { key: 'hard_cheese', name: 'Сир твердий «Голландський»', unit: 'кг', price: 314.4, vat: 'incl', date: '2026-09-24T12:30:00', sup: 'syrzavod' },
  { key: 'butter', name: 'Масло вершкове 72,5%', unit: 'кг', price: 343.2, vat: 'incl', date: '2026-09-17T09:00:00', sup: 'moloko' },
  { key: 'milk', name: 'Молоко 2,5%', unit: 'л', price: 37.8, vat: 'incl', date: '2026-10-10T06:30:00', sup: 'moloko' },
  { key: 'melange', name: 'Меланж яєчний', unit: 'кг', price: 72.4, vat: 'excl', date: '2026-10-01T08:40:00', sup: 'yaytse' },
  { key: 'oil', name: 'Олія соняшникова рафінована', unit: 'кг', price: 74.16, vat: 'incl', date: '2026-09-05T14:20:00', sup: 'bakal' },
  { key: 'sugar', name: 'Цукор білий', unit: 'кг', price: 31.68, vat: 'incl', date: '2026-08-14T10:00:00', sup: 'bakal' },
  { key: 'vanilla_sugar', name: 'Цукор ванільний', unit: 'кг', price: 141.6, vat: 'incl', date: '2026-08-14T10:00:00', sup: 'bakal' },
  { key: 'breadcrumbs', name: 'Сухарі панірувальні', unit: 'кг', price: 50.16, vat: 'incl', date: '2026-09-05T14:20:00', sup: 'bakal' },
  // a petty-cash receipt without a document currency: ЭтоГривнаИлиПусто treats '' as UAH
  { key: 'salt', name: 'Сіль кухонна', unit: 'кг', price: 5.4, vat: 'excl', date: '2026-07-22T15:45:00', sup: 'kasa', currency: '' },
  { key: 'pepper', name: 'Перець чорний мелений', unit: 'кг', price: 340.8, vat: 'incl', date: '2026-07-30T11:00:00', sup: 'spetsii' },
  { key: 'garlic', name: 'Часник сушений', unit: 'кг', price: 230.4, vat: 'incl', date: '2026-07-30T11:00:00', sup: 'spetsii' },
  { key: 'paprika', name: 'Паприка мелена', unit: 'кг', price: 309.6, vat: 'incl', date: '2026-07-30T11:00:00', sup: 'spetsii' },
  { key: 'khmeli', name: 'Хмелі-сунелі', unit: 'кг', price: 372.0, vat: 'incl', date: '2026-07-30T11:00:00', sup: 'spetsii' },
  // stale receipts (older than 90 days before generatedAt)
  { key: 'dill', name: 'Кріп сушений', unit: 'кг', price: 285.6, vat: 'incl', date: '2026-05-27T10:30:00', sup: 'spetsii' },
  { key: 'nutmeg', name: 'Мускатний горіх мелений', unit: 'кг', price: 1104.0, vat: 'incl', date: '2026-03-20T09:15:00', sup: 'spetsii' },
  { key: 'raisins', name: 'Родзинки світлі', unit: 'кг', price: 170.4, vat: 'incl', date: '2026-06-11T13:40:00', sup: 'bakal' },
  // imported, priced in EUR -> НЕМАЄ ЦІН in the catalogue, "ІНША ВАЛЮТА: EUR" in details
  { key: 'provencal', name: 'Прованські трави (імпорт)', unit: 'кг', price: 18.6, vat: 'none', date: '2026-08-21T12:00:00', sup: 'import', currency: 'EUR' },
  // own semi-finished product: never purchased -> no price at all
  { key: 'onion_fried', name: 'Цибуля пасерована (н/ф власного виробництва)', unit: 'кг', price: null },
  // --- упаковка ---
  { key: 'bag900', name: 'Пакет флексо 900 г', unit: 'шт', price: 2.62, vat: 'excl', date: '2026-09-12T10:00:00', sup: 'pack' },
  { key: 'bag500', name: 'Пакет флексо 400–500 г', unit: 'шт', price: 2.08, vat: 'excl', date: '2026-09-12T10:00:00', sup: 'pack' },
  { key: 'bag1kg', name: 'Пакет прозорий 1 кг', unit: 'шт', price: 3.15, vat: 'excl', date: '2026-08-07T09:30:00', sup: 'pack' },
  { key: 'tray', name: 'Лоток пластиковий', unit: 'шт', price: 3.4, vat: 'excl', date: '2026-09-12T10:00:00', sup: 'pack' },
  { key: 'box_big', name: 'Гофроящик 380×280×160', unit: 'шт', price: 19.2, vat: 'excl', date: '2026-09-19T11:15:00', sup: 'gofro' },
  { key: 'box_small', name: 'Гофроящик 300×200×150', unit: 'шт', price: 15.6, vat: 'excl', date: '2026-09-19T11:15:00', sup: 'gofro' },
  { key: 'label', name: 'Етикетка 58×40', unit: 'шт', price: 0.42, vat: 'excl', date: '2026-08-25T14:00:00', sup: 'druk' },
  { key: 'label_export', name: 'Етикетка експортна 100×70', unit: 'шт', price: 0.68, vat: 'excl', date: '2026-08-25T14:00:00', sup: 'druk' },
  { key: 'tape', name: 'Стрічка клейка 48 мм × 66 м', unit: 'рул', price: 38.5, vat: 'excl', date: '2026-08-25T14:00:00', sup: 'druk' },
];
const MAT = Object.fromEntries(MATERIALS.map((m) => [m.key, m]));

const CHARACTERISTICS = { c5: '5%', c9: '9%' };

// Extra receipts with a characteristic. Сир 9% has its own price; сир 5% has none, so НайтиПоследнююЦену
// falls back to the material-only receipt above.
const CHAR_RECEIPTS = [
  { material: 'cottage', char: 'c9', price: 125.4, vat: 'incl', date: '2026-10-07T08:50:00', sup: 'moloko2' },
];

function priceOf(p) {
  if (p.vat === 'incl') return { exVat: round(p.price / 1.2, 4), withVat: p.price };
  if (p.vat === 'excl') return { exVat: p.price, withVat: round(p.price * 1.2, 4) };
  return { exVat: p.price, withVat: p.price };
}

// ============================================================================
// Products and recipes
// ============================================================================

// sale: 'OK' (default, per box), 'KG' (sold by kg), 'PCS' (sold per piece, no weight), 'EUR', 'PDV', 'NONE'
const PRODUCTS = {
  p01: { name: 'Вареники з картоплею 900 г', packG: 900, perBox: 5 },
  p02: { name: 'Вареники з картоплею та грибами 900 г', packG: 900, perBox: 5 },
  p03: { name: 'Вареники з вишнею 900 г', packG: 900, perBox: 5 },
  p04: { name: 'Пельмені «Домашні» 900 г', packG: 900, perBox: 5 },
  p05: { name: 'Сирники класичні 450 г', packG: 450, perBox: 8 },
  p06: { name: 'Вареники з капустою 900 г', packG: 900, perBox: 5 },
  p07: { name: 'Вареники з сиром 450 г', packG: 450, perBox: 8 },
  p08: { name: 'Пельмені курячі 450 г', packG: 450, perBox: 8 },
  p09: { name: 'Млинці з м\'ясом 370 г', packG: 370, perBox: 12, sale: 'PCS' },
  p10: { name: 'Сирники з родзинками 450 г', packG: 450, perBox: 8 },
  p11: { name: 'Вареники з полуницею 450 г', packG: 450, perBox: 8 },
  p12: { name: 'Котлети по-київськи 500 г', packG: 500, perBox: 6 },
  p13: { name: 'Пельмені «Домашні» вагові', packG: 1000, perBox: 5, sale: 'KG' },
  p14: { name: 'Вареники з картоплею вагові', packG: 1000, perBox: 5, sale: 'KG' },
  p15: { name: 'Котлети курячі 1 кг', packG: 1000, perBox: 5 },
  p16: { name: 'Хінкалі з яловичиною 1 кг', packG: 1000, perBox: 5 },
  p17: { name: 'Галушки полтавські 1 кг', packG: 1000, perBox: 5 },
  p18: { name: 'Вареники з картоплею та шкварками 500 г', packG: 500, perBox: 10 },
  p19: { name: 'Пельмені свинні 500 г', packG: 500, perBox: 10 },
  p20: { name: 'Млинці з сиром 400 г', packG: 400, perBox: 10 },
  p21: { name: 'Вареники з печінкою 500 г', packG: 500, perBox: 10 },
  p22: { name: 'Вареники з картоплею 500 г', packG: 500, perBox: 10 },
  p23: { name: 'Галушки з м\'ясом 500 г', packG: 500, perBox: 10, sale: 'PDV' },
  p24: { name: 'Котлети «Домашні» 500 г', packG: 500, perBox: 6 },
  p25: { name: 'Млинці з шинкою та сиром 400 г', packG: 400, perBox: 10 },
  p26: { name: 'Хінкалі з сиром 500 г', packG: 500, perBox: 10 },
  p27: { name: 'Вареники з вишнею 500 г', packG: 500, perBox: 10, sale: 'NONE' },
  p28: { name: 'Пельмені «Домашні» 1 кг (експорт)', packG: 1000, perBox: 6, export: true },
  p29: { name: 'Вареники з картоплею 1 кг (експорт)', packG: 1000, perBox: 6, export: true },
  p30: { name: 'Вареники з вишнею 1 кг (експорт)', packG: 1000, perBox: 6, export: true },
  p31: { name: 'Сирники класичні 400 г (експорт)', packG: 400, perBox: 10, export: true },
  p32: { name: 'Млинці з м\'ясом 400 г (експорт)', packG: 400, perBox: 10, export: true },
  p33: { name: 'Вареники з картоплею та грибами 1 кг (IT)', packG: 1000, perBox: 6, export: true, sale: 'EUR' },
  p34: { name: 'Вареники з сиром та зеленню 500 г (IT)', packG: 500, perBox: 10, export: true },
  p35: { name: 'Пельмені курячі 1 кг (IT)', packG: 1000, perBox: 6, export: true },
  p36: { name: 'Вареники з картоплею 900 г (RO)', packG: 900, perBox: 5, export: true, sale: 'EUR' },
  p37: { name: 'Пельмені свинні 900 г (RO)', packG: 900, perBox: 5, export: true },
  p38: { name: 'Галушки з картоплею 900 г (RO)', packG: 900, perBox: 5, export: true },
  p39: { name: 'Хінкалі з яловичиною та свининою 1 кг (GF)', packG: 1000, perBox: 6, export: true },
  p40: { name: 'Вареники з капустою 1 кг (GF)', packG: 1000, perBox: 6, export: true },
  p41: { name: 'Котлети курячі 1 кг (GF)', packG: 1000, perBox: 5, export: true },
  p42: { name: 'Пельмені «Домашні» 500 г (CZ)', packG: 500, perBox: 10, export: true, sale: 'EUR' },
  p43: { name: 'Вареники з полуницею 500 г (CZ)', packG: 500, perBox: 10, export: true },
  p44: { name: 'Сирники з родзинками 400 г (CZ)', packG: 400, perBox: 10, export: true },
  p45: { name: 'Сирники класичні 400 г (IL, кошер)', packG: 400, perBox: 10, export: true },
  p46: { name: 'Вареники з картоплею 1 кг (IL, кошер)', packG: 1000, perBox: 6, export: true },
  p47: { name: 'Вареники ліниві 900 г', packG: 900, perBox: 5 },
  p48: { name: 'Пельмені «Святкові» 800 г', packG: 800, perBox: 6 },
  p49: { name: 'Чебуреки з м\'ясом та зеленню 500 г', packG: 500, perBox: 8 },
  p50: { name: 'Вареники з чорницею 450 г', packG: 450, perBox: 8, sale: 'NONE' },
  p51: { name: 'Млинці з яблуком 400 г', packG: 400, perBox: 10 },
  p52: { name: 'Сирники класичні 1 кг', packG: 1000, perBox: 6 },
  p53: { name: 'Пельмені «Мисливські» 500 г', packG: 500, perBox: 10, sale: 'NONE' },
  p54: { name: 'Вареники з м\'ясом 900 г', packG: 900, perBox: 5, saleDate: '2025-11-18T10:40:00' },
  p55: { name: 'Млинці з куркою 370 г', packG: 370, perBox: 12, saleDate: '2025-12-05T09:15:00' },
  p56: { name: 'Котлети «Бабусині» 450 г', packG: 450, perBox: 6, saleDate: '2025-10-21T14:30:00' },
  p57: { name: 'Галушки з сиром 450 г', packG: 450, perBox: 8, saleDate: '2026-01-27T11:05:00' },
  p58: { name: 'Пельмені курячі 900 г', packG: 900, perBox: 5 },
  p59: { name: 'Вареники з сиром 900 г', packG: 900, perBox: 5 },
  p60: { name: 'Галушки полтавські 1 кг (експорт)', packG: 1000, perBox: 6, export: true },
};

// [product, spec name, СтатусРецептуры, КатегорияКалькуляции, family, sale target for the product's first spec]
// target: 'ok' 22–42 % margin, 'low' 8–17 %, 'loss' -12…-4 %; secondary specs of a product share its sale.
const SPECS = [
  // ВИКОРИСТОВУЮТЬСЯ / УКРАЇНА / Рудь
  ['p01', 'Рецептура 2024 v2', 'Нова', 'UA_RUD', 'var_potato', 'ok'],
  ['p02', 'Рецептура 2025', 'Нова', 'UA_RUD', 'var_potato_mush', 'ok'],
  ['p03', 'Рецептура 2024 v2', 'Нова', 'UA_RUD', 'var_cherry', 'ok'],
  ['p04', 'Рецептура 2025 v1', 'Нова', 'UA_RUD', 'pel_home', 'ok'],
  ['p05', 'Рецептура 2024', 'Нова', 'UA_RUD', 'syrnyky', 'ok'],
  ['p06', 'Рецептура 2023 v3', 'Нова', 'UA_RUD', 'var_cabbage', 'ok'],
  // Сільпо
  ['p07', 'Рецептура Сільпо 2025', 'Нова', 'UA_SILPO', 'var_cheese', 'ok'],
  ['p08', 'Рецептура 2025', 'Нова', 'UA_SILPO', 'pel_chicken', 'low'],
  ['p09', 'Рецептура 2024 v1', 'Нова', 'UA_SILPO', 'mlyntsi_meat', 'ok'],
  ['p10', 'Рецептура 2025', 'Нова', 'UA_SILPO', 'syrnyky_raisin', 'ok'],
  ['p11', 'Рецептура 2025 v2', 'Нова', 'UA_SILPO', 'var_strawberry', 'ok'],
  ['p12', 'Рецептура 2024 v2', 'Нова', 'UA_SILPO', 'kotl_kyiv', 'loss'],
  // Метро
  ['p13', 'Рецептура HoReCa 2025', 'Нова', 'UA_METRO', 'pel_home', 'ok'],
  ['p14', 'Рецептура HoReCa 2025', 'Нова', 'UA_METRO', 'var_potato', 'low'],
  ['p15', 'Рецептура HoReCa 2025', 'Нова', 'UA_METRO', 'kotl_chicken', 'loss'],
  ['p16', 'Рецептура 2025', 'Нова', 'UA_METRO', 'khinkali_beef', 'ok'],
  ['p17', 'Рецептура 2024', 'Нова', 'UA_METRO', 'halushky_plain', 'ok'],
  ['p52', 'Рецептура HoReCa 2025', 'Нова', 'UA_METRO', 'syrnyky', 'ok'],
  // Привати / Федик
  ['p18', 'Рецептура 2024 v2', 'Нова', 'UA_FEDYK', 'var_potato_lard', 'ok'],
  ['p19', 'Рецептура 2025', 'Нова', 'UA_FEDYK', 'pel_pork', 'low'],
  ['p20', 'Рецептура 2024', 'Нова', 'UA_FEDYK', 'mlyntsi_cheese', 'ok'],
  ['p21', 'Рецептура 2025', 'Нова', 'UA_FEDYK', 'var_liver', 'ok'],
  ['p58', 'Рецептура 2025', 'Нова', 'UA_FEDYK', 'pel_chicken', 'ok'],
  // Привати / ОП
  ['p22', 'Рецептура 2024 v2', 'Нова', 'UA_OP', 'var_potato', 'ok'],
  ['p23', 'Рецептура 2025', 'Нова', 'UA_OP', 'halushky_meat', 'ok'],
  ['p24', 'Рецептура 2024', 'Нова', 'UA_OP', 'kotl_home', 'ok'],
  ['p59', 'Рецептура 2025', 'Нова', 'UA_OP', 'var_cheese', 'ok'],
  // Привати / Мидас
  ['p25', 'Рецептура 2025', 'Нова', 'UA_MIDAS', 'mlyntsi_ham', 'ok'],
  ['p26', 'Рецептура 2025', 'Нова', 'UA_MIDAS', 'khinkali_cheese', 'ok'],
  ['p27', 'Рецептура 2026', 'Нова', 'UA_MIDAS', 'var_cherry', 'ok'],
  // ЕКСПОРТ / Довгань
  ['p28', 'Рецептура EXP 2025', 'Нова', 'EX_DOVGAN', 'pel_home', 'low'],
  ['p29', 'Рецептура EXP 2025', 'Нова', 'EX_DOVGAN', 'var_potato', 'ok'],
  ['p30', 'Рецептура EXP 2025', 'Нова', 'EX_DOVGAN', 'var_cherry', 'ok'],
  ['p31', 'Рецептура EXP 2024', 'Нова', 'EX_DOVGAN', 'syrnyky', 'ok'],
  ['p32', 'Рецептура EXP 2024', 'Нова', 'EX_DOVGAN', 'mlyntsi_meat', 'ok'],
  ['p60', 'Рецептура EXP 2025', 'Нова', 'EX_DOVGAN', 'halushky_plain', 'ok'],
  // Італія
  ['p33', 'Рецептура IT 2025', 'Нова', 'EX_ITALY', 'var_potato_mush', 'ok'],
  ['p34', 'Рецептура IT 2025', 'Нова', 'EX_ITALY', 'var_cheese_herbs', 'ok'],
  ['p35', 'Рецептура IT 2025', 'Нова', 'EX_ITALY', 'pel_chicken', 'ok'],
  // Румунія
  ['p36', 'Рецептура RO 2025', 'Нова', 'EX_ROMANIA', 'var_potato', 'ok'],
  ['p37', 'Рецептура RO 2025', 'Нова', 'EX_ROMANIA', 'pel_pork', 'loss'],
  ['p38', 'Рецептура RO 2025', 'Нова', 'EX_ROMANIA', 'halushky_potato', 'ok'],
  // Гея Фуд
  ['p39', 'Рецептура 2025', 'Нова', 'EX_GEYA', 'khinkali_beef_pork', 'ok'],
  ['p40', 'Рецептура 2024 v2', 'Нова', 'EX_GEYA', 'var_cabbage', 'low'],
  ['p41', 'Рецептура 2025', 'Нова', 'EX_GEYA', 'kotl_chicken', 'ok'],
  // Чехія
  ['p42', 'Рецептура CZ 2025', 'Нова', 'EX_CZECH', 'pel_home', 'ok'],
  ['p43', 'Рецептура CZ 2025', 'Нова', 'EX_CZECH', 'var_strawberry', 'ok'],
  ['p44', 'Рецептура CZ 2025', 'Нова', 'EX_CZECH', 'syrnyky_raisin', 'ok'],
  // Ізраїль
  ['p45', 'Рецептура кошер 2025', 'Нова', 'EX_ISRAEL', 'syrnyky', 'ok'],
  ['p46', 'Рецептура кошер 2025', 'Нова', 'EX_ISRAEL', 'var_potato', 'ok'],
  // Без категорії (status not set yet, an unknown legacy code, a second spec of an existing product)
  ['p47', 'Рецептура 2023', '', '', 'var_lazy', 'ok'],
  ['p48', 'Рецептура 2022 v4', 'Нова', 'OLD_X', 'pel_festive', 'ok'],
  ['p49', 'Рецептура 2025', 'Нова', '', 'chebureky', 'ok'],
  ['p50', 'Рецептура 2026', 'Нова', '', 'var_blueberry', 'ok'],
  ['p51', 'Рецептура 2024', '', '', 'mlyntsi_apple', 'ok'],
  ['p04', 'Рецептура 2025 (економ)', 'Нова', '', 'pel_home_econ', null],
  // НЕ ВИКОРИСТОВУЮТЬСЯ (some keep their old category code)
  ['p01', 'Рецептура 2022', 'Стара', 'UA_RUD', 'var_potato_old', null],
  ['p07', 'Рецептура 2023', 'Стара', 'UA_SILPO', 'var_cheese_old', null],
  ['p16', 'Рецептура 2023', 'Стара', 'UA_METRO', 'khinkali_beef_old', null],
  ['p53', 'Рецептура 2021', 'Стара', '', 'pel_hunter', 'ok'],
  ['p54', 'Рецептура 2022 v1', 'Стара', '', 'var_meat_old', 'loss'],
  ['p55', 'Рецептура 2023', 'Стара', 'EX_DOVGAN', 'mlyntsi_chicken_old', 'ok'],
  ['p56', 'Рецептура 2021', 'Стара', '', 'kotl_grandma_old', 'ok'],
  ['p57', 'Рецептура 2022', 'Стара', '', 'halushky_cheese_old', 'ok'],
  // a draft without composition rows: in `specs`, but not in the catalogue (contract rule)
  ['p11', 'Рецептура 2026 (чернетка)', 'Нова', '', null, null],
];

// Recipe families: rows per 1000 kg of finished product. role: dough | fill | pack (used by the self-check only).
const D = (mat, qty, char = null) => ({ role: 'dough', mat, qty, char });
const F = (mat, qty, char = null, dup = false) => ({ role: 'fill', mat, qty, char, dup });

function dough(r, min = 370, max = 430, flour = 'flour_vg') {
  return [D(flour, r.q(min, max)), D('melange', r.q(14, 24)), D('oil', r.q(5, 8)), D('salt', r.q(5, 7, 0.1))];
}
const spice = (r, mat, min, max, step = 0.05) => F(mat, r.q(min, max, step));

const FAMILIES = {
  var_potato: (r) => [...dough(r, 380, 430), F('potato', r.q(420, 460)), F('onion', r.q(45, 60)), F('oil', r.q(8, 12)),
    spice(r, 'pepper', 0.6, 0.9), F('salt', r.q(4, 6, 0.1))],
  var_potato_old: (r) => [...dough(r, 400, 420), F('potato', r.q(440, 460)), F('onion', r.q(55, 65)), F('butter', r.q(18, 24)),
    F('oil', r.q(10, 14)), spice(r, 'pepper', 0.8, 1.0), F('salt', r.q(4, 6, 0.1))],
  var_potato_mush: (r) => [...dough(r, 380, 420), F('potato', r.q(320, 350)), F('mushroom', r.q(110, 130)), F('onion', r.q(40, 50)),
    F('oil', r.q(9, 12)), spice(r, 'dill', 0.8, 1.2), spice(r, 'pepper', 0.5, 0.7), F('salt', r.q(4, 5, 0.1))],
  var_potato_lard: (r) => [...dough(r, 380, 420), F('potato', r.q(360, 400)), F('lard', r.q(60, 80)), F('onion', r.q(50, 60)),
    spice(r, 'pepper', 0.6, 0.8), F('salt', r.q(4, 5, 0.1))],
  var_cabbage: (r) => [...dough(r, 380, 420), F('cabbage', r.q(380, 420)), F('carrot', r.q(30, 40)), F('onion', r.q(40, 50)),
    F('oil', r.q(16, 22)), spice(r, 'pepper', 0.4, 0.6), F('salt', r.q(4, 6, 0.1))],
  var_cherry: (r) => [...dough(r, 400, 440), F('cherry', r.q(380, 420)), F('sugar', r.q(55, 70)), F('starch', r.q(12, 16))],
  var_strawberry: (r) => [...dough(r, 400, 440), F('strawberry', r.q(380, 410)), F('sugar', r.q(60, 75)), F('starch', r.q(12, 16))],
  var_blueberry: (r) => [...dough(r, 410, 440), F('blueberry', r.q(360, 390)), F('sugar', r.q(60, 70)), F('starch', r.q(13, 16))],
  var_cheese: (r) => [...dough(r, 370, 410), F('cottage', r.q(420, 460), 'c5'), F('sugar', r.q(35, 45)), F('melange', r.q(15, 20)),
    spice(r, 'vanilla_sugar', 1.5, 2.0), F('semolina', r.q(12, 16))],
  var_cheese_old: (r) => [...dough(r, 380, 400), F('cottage', r.q(460, 480)), F('sugar', r.q(45, 55)), F('melange', r.q(20, 25)),
    spice(r, 'vanilla_sugar', 2.0, 2.5), F('semolina', r.q(14, 18))],
  var_cheese_herbs: (r) => [...dough(r, 380, 410), F('cottage', r.q(400, 430), 'c5'), F('parsley', r.q(14, 18)),
    spice(r, 'provencal', 1.6, 2.2), F('salt', r.q(2, 3, 0.1))],
  var_liver: (r) => [...dough(r, 390, 420), F('liver', r.q(340, 370)), F('onion_fried', r.q(60, 75)), F('oil', r.q(7, 9)),
    spice(r, 'pepper', 0.5, 0.7), F('salt', r.q(4, 5, 0.1))],
  var_meat_old: (r) => [...dough(r, 395, 410), F('pork', r.q(230, 250)), F('beef', r.q(150, 170)), F('onion', r.q(60, 70)),
    spice(r, 'pepper', 1.1, 1.3), F('salt', r.q(6, 8, 0.1))],
  var_lazy: (r) => [F('cottage', r.q(560, 590), 'c9'), D('flour_vg', r.q(210, 240)), F('melange', r.q(60, 70)), F('sugar', r.q(60, 70)),
    F('semolina', r.q(35, 45)), spice(r, 'vanilla_sugar', 1.8, 2.2), F('salt', r.q(1.5, 2.5, 0.1))],
  pel_home: (r) => [...dough(r, 360, 400), F('pork', r.q(240, 265)), F('beef', r.q(170, 190)), F('onion', r.q(60, 75)),
    spice(r, 'garlic', 1.5, 2.5), spice(r, 'pepper', 1.2, 1.6), spice(r, 'nutmeg', 0.15, 0.25, 0.01), F('salt', r.q(7, 9, 0.1), null, true)],
  pel_home_econ: (r) => [...dough(r, 380, 410), F('pork', r.q(225, 240)), F('beef', r.q(95, 110)), F('onion', r.q(105, 120)),
    spice(r, 'garlic', 1.3, 1.7), spice(r, 'pepper', 1.2, 1.4), spice(r, 'nutmeg', 0.12, 0.16, 0.01), F('salt', r.q(7, 9, 0.1), null, true)],
  pel_chicken: (r) => [...dough(r, 370, 400), F('chicken', r.q(420, 455)), F('onion', r.q(60, 75)), spice(r, 'garlic', 1.2, 1.8),
    spice(r, 'pepper', 1.0, 1.3), F('salt', r.q(7, 9, 0.1), null, true)],
  pel_pork: (r) => [...dough(r, 370, 400), F('pork', r.q(360, 390)), F('lard', r.q(40, 55)), F('onion', r.q(65, 80)),
    spice(r, 'garlic', 1.8, 2.4), spice(r, 'pepper', 1.3, 1.6), F('salt', r.q(7, 9, 0.1), null, true)],
  pel_hunter: (r) => [...dough(r, 375, 390), F('pork', r.q(245, 255)), F('beef', r.q(115, 125)), F('lard', r.q(55, 65)),
    spice(r, 'paprika', 2.8, 3.2), spice(r, 'pepper', 1.8, 2.2), spice(r, 'garlic', 1.8, 2.2), F('salt', r.q(8, 9, 0.1), null, true)],
  pel_festive: (r) => [...dough(r, 370, 390), F('pork', r.q(220, 240)), F('beef', r.q(150, 170)), F('chicken', r.q(70, 90)),
    F('onion', r.q(55, 65)), spice(r, 'pepper', 1.2, 1.4), F('salt', r.q(7, 9, 0.1), null, true)],
  khinkali_beef: (r) => [...dough(r, 350, 380), F('beef', r.q(390, 420)), F('onion', r.q(90, 110)), F('parsley', r.q(14, 18)),
    spice(r, 'khmeli', 2.0, 3.0), spice(r, 'pepper', 1.4, 1.8), F('salt', r.q(7, 9, 0.1))],
  khinkali_beef_old: (r) => [...dough(r, 360, 375), F('beef', r.q(425, 435)), F('onion', r.q(95, 105)), F('parsley', r.q(18, 22)),
    spice(r, 'khmeli', 2.8, 3.2), spice(r, 'pepper', 1.6, 1.9), F('salt', r.q(7, 9, 0.1))],
  khinkali_beef_pork: (r) => [...dough(r, 350, 380), F('beef', r.q(220, 240)), F('pork', r.q(190, 210)), F('onion', r.q(90, 100)),
    F('parsley', r.q(15, 18)), spice(r, 'khmeli', 2.0, 2.6), spice(r, 'pepper', 1.4, 1.6), F('salt', r.q(7, 9, 0.1))],
  khinkali_cheese: (r) => [...dough(r, 360, 380), F('hard_cheese', r.q(200, 230)), F('cottage', r.q(210, 240), 'c9'),
    F('melange', r.q(12, 16)), F('parsley', r.q(10, 12)), F('salt', r.q(2, 3, 0.1))],
  syrnyky: (r) => [F('cottage', r.q(620, 660), 'c9'), D('flour_vg', r.q(85, 105)), F('semolina', r.q(35, 45)), F('melange', r.q(55, 65)),
    F('sugar', r.q(60, 75)), spice(r, 'vanilla_sugar', 1.5, 2.2), F('oil', r.q(10, 14)), F('salt', r.q(1.5, 2.5, 0.1))],
  syrnyky_raisin: (r) => [F('cottage', r.q(580, 610), 'c9'), F('raisins', r.q(70, 85)), D('flour_vg', r.q(85, 100)),
    F('semolina', r.q(35, 40)), F('melange', r.q(55, 65)), F('sugar', r.q(50, 60)), spice(r, 'vanilla_sugar', 1.5, 2.0),
    F('oil', r.q(10, 12)), F('salt', r.q(1.5, 2.5, 0.1))],
  mlyntsi_meat: (r) => [D('flour_1', r.q(170, 195)), D('milk', r.q(260, 290)), D('melange', r.q(70, 85)), D('oil', r.q(18, 24)),
    D('sugar', r.q(6, 9)), D('salt', r.q(4, 6, 0.1)), F('pork', r.q(170, 190)), F('beef', r.q(110, 125)), F('onion', r.q(45, 55)),
    spice(r, 'pepper', 0.7, 0.9)],
  mlyntsi_cheese: (r) => [D('flour_1', r.q(170, 195)), D('milk', r.q(270, 295)), D('melange', r.q(75, 90)), D('oil', r.q(14, 17)),
    D('salt', r.q(2.5, 3.5, 0.1)), F('cottage', r.q(300, 330), 'c5'), F('sugar', r.q(45, 55)), spice(r, 'vanilla_sugar', 1.3, 1.7),
    F('butter', r.q(12, 16))],
  mlyntsi_ham: (r) => [D('flour_1', r.q(175, 195)), D('milk', r.q(270, 290)), D('melange', r.q(75, 85)), D('oil', r.q(14, 18)),
    D('salt', r.q(3.5, 4.5, 0.1)), F('ham', r.q(170, 185)), F('hard_cheese', r.q(110, 125))],
  mlyntsi_apple: (r) => [D('flour_1', r.q(180, 200)), D('milk', r.q(280, 300)), D('melange', r.q(75, 85)), D('oil', r.q(14, 18)),
    D('salt', r.q(2.5, 3.5, 0.1)), F('apple', r.q(320, 350)), F('sugar', r.q(55, 65)), F('starch', r.q(8, 10))],
  mlyntsi_chicken_old: (r) => [D('flour_1', r.q(180, 190)), D('milk', r.q(275, 285)), D('melange', r.q(75, 85)), D('oil', r.q(16, 20)),
    D('salt', r.q(4.5, 5.5, 0.1)), F('chicken', r.q(290, 310)), F('onion', r.q(50, 60)), spice(r, 'pepper', 0.7, 0.9)],
  halushky_plain: (r) => [D('flour_1', r.q(460, 480)), D('melange', r.q(70, 80)), D('butter', r.q(22, 28)), D('milk', r.q(110, 130)),
    D('salt', r.q(8, 9, 0.1))],
  halushky_meat: (r) => [...dough(r, 400, 430, 'flour_1'), F('pork', r.q(320, 345)), F('onion', r.q(80, 90)), spice(r, 'pepper', 0.8, 1.0),
    F('salt', r.q(5, 6, 0.1))],
  halushky_potato: (r) => [...dough(r, 420, 450, 'flour_1'), F('potato', r.q(380, 410)), F('onion', r.q(45, 55)), F('oil', r.q(12, 16)),
    F('salt', r.q(4, 5, 0.1))],
  halushky_cheese_old: (r) => [...dough(r, 395, 405, 'flour_1'), F('cottage', r.q(410, 430)), F('sugar', r.q(28, 32)), F('melange', r.q(14, 16))],
  kotl_kyiv: (r) => [F('chicken', r.q(600, 630)), F('butter', r.q(110, 125)), F('parsley', r.q(10, 13)), F('breadcrumbs', r.q(110, 125)),
    F('melange', r.q(70, 85)), F('flour_vg', r.q(25, 32)), F('salt', r.q(7, 9, 0.1)), spice(r, 'pepper', 0.9, 1.1)],
  kotl_chicken: (r) => [F('chicken', r.q(580, 610)), F('onion', r.q(85, 100)), F('breadcrumbs', r.q(60, 75)), F('melange', r.q(35, 45)),
    F('starch', r.q(15, 20)), F('oil', r.q(18, 22)), F('salt', r.q(8, 10, 0.1)), spice(r, 'pepper', 1.1, 1.3)],
  kotl_home: (r) => [F('pork', r.q(340, 365)), F('beef', r.q(220, 240)), F('onion', r.q(85, 95)), F('breadcrumbs', r.q(65, 75)),
    F('melange', r.q(38, 45)), spice(r, 'garlic', 2.5, 3.2), spice(r, 'paprika', 1.5, 2.0), F('salt', r.q(9, 11, 0.1)), spice(r, 'pepper', 1.3, 1.6)],
  kotl_grandma_old: (r) => [F('pork', r.q(385, 395)), F('beef', r.q(145, 155)), F('onion_fried', r.q(75, 85)), F('breadcrumbs', r.q(65, 75)),
    F('melange', r.q(38, 42)), spice(r, 'garlic', 2.8, 3.2), F('salt', r.q(9, 11, 0.1)), spice(r, 'pepper', 1.4, 1.6)],
  chebureky: (r) => [D('flour_1', r.q(430, 450)), D('oil', r.q(30, 36)), D('salt', r.q(7, 9, 0.1)), F('pork', r.q(200, 220)),
    F('beef', r.q(150, 165)), F('onion_fried', r.q(55, 65)), spice(r, 'provencal', 1.8, 2.2), spice(r, 'pepper', 1.1, 1.3)],
};

// Families with a dough shell + filling: flour 350–480 kg and filling 400–600 kg per 1000 kg are asserted for these.
const DUMPLING_FAMILIES = new Set(Object.keys(FAMILIES).filter((f) => /^(var_|pel_|khinkali_|halushky_|chebureky)/.test(f)
  && f !== 'var_lazy' && f !== 'halushky_plain'));
const TRAY_FAMILIES = /^(syrnyky|kotl_|mlyntsi_)/;

function packagingRows(prod, family) {
  const rows = [];
  const packs = Math.ceil((1000 / (prod.packG / 1000)) * 1.01);
  const boxKg = (prod.packG * prod.perBox) / 1000;
  const boxes = Math.ceil((1000 / boxKg) * 1.005);
  const bag = prod.packG >= 1000 ? 'bag1kg' : prod.packG >= 800 ? 'bag900' : 'bag500';
  const P = (mat, qty) => ({ role: 'pack', mat, qty, char: null });
  if (TRAY_FAMILIES.test(family) && prod.packG < 1000) rows.push(P('tray', packs));
  rows.push(P(bag, packs));
  if (prod.export) rows.push(P('label_export', packs));
  rows.push(P(boxKg <= 3.6 ? 'box_small' : 'box_big', boxes));
  if (!prod.export) rows.push(P('label', boxes));
  rows.push(P('tape', round(boxes / 110, 1)));
  return rows;
}

/** Merge repeated material+characteristic lines (dough + filling), except deliberate duplicates. */
function mergeRows(rows) {
  const out = [];
  const idx = new Map();
  for (const r of rows) {
    const k = r.mat + '|' + (r.char || '');
    if (!r.dup && idx.has(k)) { const t = out[idx.get(k)]; t.qty = round(t.qty + r.qty, 3); continue; }
    if (!r.dup) idx.set(k, out.length);
    out.push({ ...r });
  }
  return out;
}

// Sales channels: last shipment date and VAT mode of the sales documents.
const CHANNELS = {
  UA_RUD: { date: '2026-10-10T14:05:00', vat: 'excl' },
  UA_SILPO: { date: '2026-10-09T11:20:00', vat: 'incl' },
  UA_METRO: { date: '2026-10-12T08:40:00', vat: 'excl' },
  UA_FEDYK: { date: '2026-10-07T15:30:00', vat: 'incl' },
  UA_OP: { date: '2026-10-02T10:10:00', vat: 'incl' },
  UA_MIDAS: { date: '2026-09-30T13:45:00', vat: 'incl' },
  EX_DOVGAN: { date: '2026-09-26T09:00:00', vat: 'export' },
  EX_ITALY: { date: '2026-09-18T12:00:00', vat: 'export' },
  EX_ROMANIA: { date: '2026-10-03T16:20:00', vat: 'export' },
  EX_GEYA: { date: '2026-09-23T10:30:00', vat: 'export' },
  EX_CZECH: { date: '2026-09-15T11:10:00', vat: 'export' },
  EX_ISRAEL: { date: '2026-08-29T09:50:00', vat: 'export' },
  '': { date: '2026-10-05T12:00:00', vat: 'incl' },
};

// ============================================================================
// Build
// ============================================================================

function build() {
  const ids = {
    product: (k) => makeId('product', k),
    material: (k) => makeId('material', k),
    char: (k) => makeId('char', k),
    spec: (p, name) => makeId('spec', p + '/' + name),
  };

  // --- receipts (output of ПолучитьПоследниеЦеныЗакупки: last receipt per material+characteristic) ---
  const receipts = [];
  for (const m of MATERIALS) {
    if (m.price == null) continue;
    receipts.push({ material: m.key, char: null, date: m.date, sup: m.sup, currency: m.currency ?? 'грн', ...priceOf(m) });
  }
  for (const c of CHAR_RECEIPTS) {
    receipts.push({ material: c.material, char: c.char, date: c.date, sup: c.sup, currency: 'грн', ...priceOf(c) });
  }
  // receipt documents: one per date + supplier, numbered chronologically
  const receiptDocKeys = [...new Set(receipts.map((r) => r.date + '|' + r.sup))].sort();
  const receiptDoc = new Map(receiptDocKeys.map((k, i) => [k, `Прихідна накладна 00-000${String(612 + i * 7).padStart(3, '0')} від ${ddmmyyyy(k)}`]));
  for (const r of receipts) r.doc = receiptDoc.get(r.date + '|' + r.sup);

  /** НайтиПоследнююЦену over the receipts table. */
  function findLastPrice(mat, char) {
    const rows = receipts.filter((r) => r.material === mat);
    if (!rows.length) return null;
    if (char) {
      let best = null;
      for (const r of rows) if (r.char === char && (!best || r.date > best.date)) best = r;
      if (best) return best;
    }
    for (const r of rows) if (!r.char) return r;
    return rows.reduce((b, r) => (r.date > b.date ? r : b), rows[0]);
  }

  // --- specs and rows ---
  const products = {};
  const specs = [];
  const specRows = new Map(); // spec id -> internal rows
  const specMeta = new Map(); // spec id -> {pKey, family, target, primary}
  const seenProduct = new Set();
  for (const [pKey, specName, status, category, family, target] of SPECS) {
    const prod = PRODUCTS[pKey];
    if (!prod) throw new Error('unknown product ' + pKey);
    const pid = ids.product(pKey);
    products[pid] = prod.name;
    const id = ids.spec(pKey, specName);
    specs.push({ id, name: specName, product: pid, status, category, _pKey: pKey });
    const primary = !seenProduct.has(pKey) && family != null;
    if (primary) seenProduct.add(pKey);
    specMeta.set(id, { pKey, family, target, primary, specName });
    if (!family) continue;
    if (!FAMILIES[family]) throw new Error('unknown family ' + family);
    const r = rngFor('spec:' + pKey + ':' + specName);
    const rows = mergeRows([...FAMILIES[family](r), ...packagingRows(prod, family)]);
    specRows.set(id, rows);
  }

  // Sort like the BSL query: Товар, Спецификация, НомерСтроки (by presentation)
  const cmp = (a, b) => a.localeCompare(b, 'uk');
  specs.sort((a, b) => cmp(products[a.product], products[b.product]) || cmp(a.name, b.name));

  const materials = {};
  const characteristics = {};
  const purchasePrices = {};
  const usedPairs = new Set();
  for (const rows of specRows.values()) for (const r of rows) usedPairs.add(r.mat + '|' + (r.char || ''));
  for (const pair of [...usedPairs].sort()) {
    const [mat, char] = pair.split('|');
    materials[ids.material(mat)] = MAT[mat].name;
    if (char) characteristics[ids.char(char)] = CHARACTERISTICS[char];
    const p = findLastPrice(mat, char || null);
    if (!p) continue;
    purchasePrices[ids.material(mat) + '|' + (char ? ids.char(char) : '')] = {
      exVat: p.exVat, withVat: p.withVat, date: p.date, doc: p.doc, currency: p.currency,
    };
  }

  function contractRows() {
    const out = [];
    for (const s of specs) {
      const rows = specRows.get(s.id);
      if (!rows) continue;
      for (const r of rows) {
        out.push({ spec: s.id, material: ids.material(r.mat), char: r.char ? ids.char(r.char) : null, unit: MAT[r.mat].unit, qty: r.qty });
      }
    }
    return out;
  }

  const data = {
    format: 'fortuna-data',
    version: 1,
    source: 'demo',
    generatedAt: GENERATED_AT,
    base: 'Виробництво заморожених напівфабрикатів (демо)',
    user: 'Демо-користувач',
    methodology: { batchKg: BATCH_KG, processingPerTon: PROCESSING_PER_TON, historyTag: HISTORY_TAG },
    features: { statusAttribute: true, categoryAttribute: true, historyRegister: true, materialHistoryRegister: true, writes: true },
    messages: [],
    products,
    materials,
    characteristics,
    specs: specs.map(({ _pKey, ...s }) => s),
    rows: [],
    purchasePrices,
    sales: {},
    history: {},
  };

  // --- remove rounding ties from the cost (bump the main filling line by 0.5 kg until clean) ---
  for (let guard = 0; guard < 50; guard++) {
    data.rows = contractRows();
    const cat = computeCatalogue(data);
    const bad = cat.filter((r) => nearTie(r.costRaw, 4) || nearTie(r.cost, 2));
    if (!bad.length) break;
    for (const r of bad) {
      const rows = specRows.get(r.id);
      const main = rows.filter((x) => x.role === 'fill').sort((a, b) => b.qty - a.qty)[0] || rows[0];
      main.qty = round(main.qty + 0.5, 3);
    }
  }

  // --- sales: price the product's primary spec at its target margin, per box, without VAT ---
  const costById = new Map(computeCatalogue(data).map((r) => [r.id, r]));
  const saleDocKeys = [];
  const saleDraft = {};
  for (const s of specs) {
    const meta = specMeta.get(s.id);
    if (!meta.primary) continue;
    const prod = PRODUCTS[meta.pKey];
    if (prod.sale === 'NONE') continue;
    const r = rngFor('sale:' + meta.pKey);
    const channelKey = CHANNELS[s.category] ? s.category : '';
    const channel = CHANNELS[channelKey];
    let date = prod.saleDate || channel.date;
    if (!prod.saleDate) {
      const back = r.pick([0, 0, 0, 0, 2, 5, 9]);
      date = new Date(isoToMs(date) - back * 86400000).toISOString().slice(0, 19);
    }
    const m = meta.target === 'low' ? r.range(0.08, 0.17) : meta.target === 'loss' ? -r.range(0.04, 0.12) : r.range(0.22, 0.42);
    const cost = costById.get(s.id).cost;
    const perKg = cost / (1 - m);
    const boxKg = (prod.packG * prod.perBox) / 1000;
    let unit = `ящ (${comma(boxKg)} кг)`;
    let unitKg = boxKg;
    let gross = perKg * boxKg;
    if (prod.sale === 'KG') { unit = 'кг'; unitKg = 1; gross = perKg; }
    if (prod.sale === 'PCS') { unit = 'шт'; unitKg = 0; gross = (perKg * prod.packG) / 1000; }
    const fine = prod.sale === 'KG' || prod.sale === 'PCS';
    const vat = channel.vat;
    const docKey = date + '|' + channelKey;
    saleDocKeys.push(docKey);
    saleDraft[s.product] = { pKey: meta.pKey, prod, vat, fine, gross, unit, unitKg, date, docKey };
  }
  const saleDocNo = new Map([...new Set(saleDocKeys)].sort().map((k, i) => [k, 1104 + i * 9]));

  function priceSale(d, bump) {
    const step = d.fine ? 0.1 : d.vat === 'excl' ? 0.5 : 1;
    let exVat; let withVat;
    if (d.vat === 'incl') {
      withVat = round(Math.round((d.gross * 1.2) / step) * step + bump * step, 2);
      exVat = round(withVat / 1.2, 4);
    } else if (d.vat === 'excl') {
      exVat = round(Math.round(d.gross / step) * step + bump * step, 2);
      withVat = round(exVat * 1.2, 4);
    } else {
      exVat = round(Math.round(d.gross / step) * step + bump * step, 2);
      withVat = exVat;
    }
    return { exVat, withVat };
  }

  for (const [pid, d] of Object.entries(saleDraft)) {
    const { exVat, withVat } = priceSale(d, 0);
    const sale = { status: 'OK', exVat, withVat, unit: d.unit, boxKg: d.unitKg, date: d.date,
      doc: `Видаткова накладна 00-00${saleDocNo.get(d.docKey)} від ${ddmmyyyy(d.date)}` };
    if (d.prod.sale === 'EUR') Object.assign(sale, { status: 'ЦІНА В ІНШІЙ ВАЛЮТІ: EUR', exVat: 0, withVat: 0 });
    if (d.prod.sale === 'PDV') Object.assign(sale, { status: 'ПЕРЕВІР ПДВ У РОЗХІДНІЙ', exVat: 0, withVat: 0 });
    data.sales[pid] = sale;
  }
  // order sales like products appear in specs
  data.sales = Object.fromEntries(Object.keys(products).filter((p) => data.sales[p]).map((p) => [p, data.sales[p]]));

  // --- remove rounding ties from sale / markup / margin (bump the box price by one step) ---
  for (let guard = 0; guard < 50; guard++) {
    const cat = computeCatalogue(data);
    const badProducts = new Set(cat.filter((r) => (r.saleRaw != null && (nearTie(r.saleRaw, 4) || nearTie(r.sale, 2)))
      || (r.markupRaw != null && nearTie(r.markupRaw, 2)) || (r.marginRaw != null && nearTie(r.marginRaw, 2))).map((r) => r.productId));
    if (!badProducts.size) break;
    for (const pid of badProducts) {
      const d = saleDraft[pid];
      d.bump = (d.bump || 0) + 1;
      Object.assign(data.sales[pid], priceSale(d, d.bump));
    }
  }

  // --- history: about half of the recipes, ЗагрузитьИсториюКалькуляций shape [current, previous] ---
  const catalogue = computeCatalogue(data);
  const hr = rngFor('history');
  const S = ['2026-07-01T08:42:10', '2026-08-03T09:05:33', '2026-09-01T08:15:02', '2026-10-01T08:10:47', '2026-10-09T16:40:12'];
  const entry = (rec, period) => ({ period, cost: round(rec.cost, 2), sale: round(rec.sale, 2), markup: round(rec.markup, 2),
    materials: rec.materials, pricesFound: rec.pricesFound });
  const markupOf = (e) => (e.materials > 0 && e.materials === e.pricesFound && e.cost > 0 && e.sale > 0
    ? round((e.sale - e.cost) / e.cost * 100, 2) : 0);
  /** An earlier snapshot: purchase prices were lower, sometimes the selling price too. */
  const older = (e, period) => {
    const cost = round(e.cost * (1 - hr.range(0.012, 0.045)), 2);
    const sale = e.sale > 0 && hr.next() < 0.45 ? round(e.sale * (1 - hr.range(0.025, 0.06)), 2) : e.sale;
    const o = { period, cost, sale, markup: 0, materials: e.materials, pricesFound: e.pricesFound };
    o.markup = markupOf(o);
    return o;
  };
  const plan = [
    ['prevIncomplete', 2], ['prevNoSale', 1], ['changed2', 11], ['identical2', 10], ['changed1', 6], ['identical1', 2],
  ];
  const pool = hr.shuffle(catalogue);
  const taken = new Set();
  const take = (pred) => { const r = pool.find((x) => !taken.has(x.id) && pred(x)); if (r) taken.add(r.id); return r; };
  for (const [kind, count] of plan) {
    for (let i = 0; i < count; i++) {
      const rec = kind === 'prevIncomplete' || kind === 'prevNoSale' ? take((x) => x.active && x.fullCost && x.hasSale) : take(() => true);
      if (!rec) throw new Error('history: no recipe for ' + kind);
      const cur = entry(rec, '');
      let hist;
      if (kind === 'changed2') {
        const h0 = older(cur, hr.pick([S[2], S[3]]));
        hist = [h0, older(h0, hr.pick([S[0], S[1]]))];
      } else if (kind === 'identical2') {
        hist = [{ ...cur, period: hr.pick([S[3], S[4]]) }, older(cur, hr.pick([S[1], S[2]]))];
      } else if (kind === 'changed1') {
        hist = [older(cur, hr.pick([S[2], S[3]]))];
      } else if (kind === 'identical1') {
        hist = [{ ...cur, period: S[3] }];
      } else if (kind === 'prevNoSale') {
        const h0 = older(cur, S[2]);
        hist = [{ ...h0, sale: 0, markup: 0 }];
      } else { // prevIncomplete: one material had no receipt yet, so the earlier cost was partial
        const h0 = { ...older(cur, S[2]), pricesFound: cur.pricesFound - 1 };
        h0.cost = round(h0.cost * 0.93, 2);
        h0.markup = markupOf(h0);
        hist = [h0];
      }
      data.history[rec.id] = hist;
    }
  }
  data.history = Object.fromEntries(catalogue.filter((r) => data.history[r.id]).map((r) => [r.id, data.history[r.id]]));

  // --- diagnostics, as the form's Сообщить() would print them during a load ---
  data.messages = [
    `РЕЦЕПТУРИ: таблична частина = Состав; матеріал = Номенклатура; кількість = Количество; рядків = ${data.rows.length}`,
    `Склад рецептур завантажено. Рядків: ${data.rows.length}`,
    `Закупівельні ціни завантажено. Рядків: ${receipts.length}`,
    `ПРОДАЖІ: РасходнаяНакладная.Запасы; товарів із ціною: ${Object.keys(data.sales).length}; поле од.продажу: ЕдиницаИзмерения`,
  ];

  return { data, internals: { specMeta, specRows, receipts, findLastPrice, ids } };
}

// ============================================================================
// Self-check
// ============================================================================

function selfCheck(data, internals) {
  const checks = [];
  const check = (name, ok, detail = '') => checks.push({ name, ok: !!ok, detail });
  const cat = computeCatalogue(data);
  const active = cat.filter((r) => r.active);
  const byId = new Map(cat.map((r) => [r.id, r]));
  const now = GENERATED_AT;
  const { ids, specMeta, specRows } = internals;
  const matKeyById = Object.fromEntries(MATERIALS.map((m) => [ids.material(m.key), m.key]));

  // ---- summary table ----
  const pad = (s, n) => { s = String(s); return s.length > n ? s.slice(0, n - 1) + '…' : s.padEnd(n); };
  const num = (x, d = 2) => (x === 0 || x == null ? '' : x.toFixed(d)).padStart(9);
  console.log('\nФОРТУНА demo — catalogue (tree order, threshold ' + MARGIN_THRESHOLD + ' %)\n');
  console.log(pad('#', 3) + pad('Рецептура', 58) + pad('Папка', 14) + pad('М/Ц', 7) + 'С/в грн/кг'.padStart(10) + 'Продаж'.padStart(9)
    + 'Нац %'.padStart(9) + 'Маржа %'.padStart(9) + '  Проблема');
  cat.forEach((r, i) => {
    const folder = r.categoryPath.split(' / ').pop();
    console.log(pad(i + 1, 3) + pad(r.name, 58) + pad(folder, 14) + pad(r.materials + '/' + r.pricesFound, 7) + num(r.cost).padStart(10)
      + num(r.sale) + num(r.markup) + num(r.margin) + '  ' + r.problem + (r.problem !== 'OK' && !r.active ? ' (неактивна)' : ''));
  });

  // ---- shape & integrity ----
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const allIds = [...Object.keys(data.products), ...Object.keys(data.materials), ...Object.keys(data.characteristics), ...data.specs.map((s) => s.id)];
  check('ids are lower-case UUIDs', allIds.every((x) => UUID.test(x)));
  check('ids are unique', new Set(allIds).size === allIds.length, `${allIds.length} ids`);
  check('format/version/source/generatedAt', data.format === 'fortuna-data' && data.version === 1 && data.source === 'demo'
    && data.generatedAt === GENERATED_AT);
  check('serverCalc absent', !('serverCalc' in data));
  const specIds = new Set(data.specs.map((s) => s.id));
  check('every row references a known spec / material / characteristic', data.rows.every((r) => specIds.has(r.spec)
    && data.materials[r.material] && (r.char === null || data.characteristics[r.char]) && r.qty > 0 && typeof r.unit === 'string'));
  check('every spec references a known product', data.specs.every((s) => data.products[s.product]));
  check('every purchase/sale/history key is known', Object.keys(data.purchasePrices).every((k) => data.materials[k.split('|')[0]])
    && Object.keys(data.sales).every((k) => data.products[k]) && Object.keys(data.history).every((k) => specIds.has(k)));
  check('history: at most two entries, newest first, tagged methodology', Object.values(data.history).every((h) => h.length >= 1
    && h.length <= 2 && (h.length === 1 || h[0].period > h[1].period) && h.every((e) => e.period < now)));
  const numbersClean = JSON.stringify(data).match(/\d\.\d{5,}/g);
  check('no float noise in numbers (≤ 4 decimals)', !numbersClean, numbersClean ? numbersClean.slice(0, 3).join(', ') : '');

  // ---- size and structure ----
  check('catalogue has 60–70 recipes', cat.length >= 60 && cat.length <= 70, `${cat.length}`);
  const draft = data.specs.filter((s) => !byId.has(s.id));
  check('a spec without rows stays out of the catalogue', draft.length === 1, draft.map((s) => s.name).join(', '));
  const perCat = Object.fromEntries(CATEGORY_CODES.map((c) => [c, active.filter((r) => r.categoryCode === c).length]));
  check('all 12 categories have 2–6 active recipes', Object.values(perCat).every((n) => n >= 2 && n <= 6),
    Object.entries(perCat).map(([c, n]) => `${c}=${n}`).join(' '));
  const noCat = active.filter((r) => r.categoryPath === FOLDER_NONE.join(' / '));
  const oldX = noCat.filter((r) => r.spec.category === 'OLD_X');
  check('~6 "Без категорії", one with unknown code OLD_X', noCat.length >= 5 && noCat.length <= 7 && oldX.length === 1, `${noCat.length}`);
  const inactive = cat.filter((r) => !r.active);
  const inactiveWithCode = inactive.filter((r) => r.spec.category);
  check('~8 inactive ("Стара"), some still with a category code', inactive.length >= 7 && inactive.length <= 9
    && inactiveWithCode.length >= 2 && inactive.every((r) => r.spec.status === 'Стара'), `${inactive.length} (with code: ${inactiveWithCode.length})`);
  const specsPerProduct = {};
  for (const r of cat) specsPerProduct[r.productId] = (specsPerProduct[r.productId] || 0) + 1;
  const multi = Object.entries(specsPerProduct).filter(([, n]) => n > 1);
  const bothActive = multi.filter(([p]) => cat.filter((r) => r.productId === p && r.active).length > 1);
  check('products with two specs (one with both active)', multi.length >= 2 && bothActive.length >= 1, `${multi.length} products`);
  check('spec names like "Рецептура 2024 v2"', data.specs.every((s) => /^Рецептура( [^ ]+)? 20\d\d/.test(s.name)));

  // ---- materials, prices, quantities ----
  const matCount = Object.keys(data.materials).length;
  check('~45 materials (raw, spices, packaging), all used', matCount >= 40 && matCount <= 50
    && Object.keys(data.materials).every((m) => data.rows.some((r) => r.material === m)), `${matCount}`);
  const anchors = { flour_vg: 16, potato: 12, pork: 170, chicken: 145, cherry: 88, cottage: 98, bag900: 2.6, box_big: 19 };
  const anchorOk = Object.entries(anchors).map(([k, target]) => {
    const p = data.purchasePrices[ids.material(k) + '|'];
    return [k, p ? p.exVat : null, p && Math.abs(p.exVat - target) / target <= 0.1];
  });
  check('anchor prices (exVat, ±10 %)', anchorOk.every((a) => a[2]), anchorOk.map(([k, v]) => `${k}=${v}`).join(' '));
  check('VAT consistent (withVat = exVat×1.2 or equal for non-VAT/import)', Object.values(data.purchasePrices).every((p) =>
    Math.abs(p.withVat - p.exVat) < 1e-9 || Math.abs(p.withVat - p.exVat * 1.2) < 0.0001));
  const qtyIssues = [];
  for (const s of data.specs) {
    const meta = specMeta.get(s.id);
    const rows = specRows.get(s.id);
    if (!rows) continue;
    const flour = rows.filter((r) => r.mat.startsWith('flour')).reduce((a, r) => a + r.qty, 0);
    const fill = rows.filter((r) => r.role === 'fill').reduce((a, r) => a + r.qty, 0);
    if (DUMPLING_FAMILIES.has(meta.family) && (flour < 350 || flour > 480 || fill < 400 || fill > 600)) {
      qtyIssues.push(`${PRODUCTS[meta.pKey].name}: flour ${flour}, filling ${fill}`);
    }
    if (rows.some((r) => MAT[r.mat].unit === 'шт' && !Number.isInteger(r.qty))) qtyIssues.push(`${s.name}: fractional шт`);
    const raw = rows.filter((r) => r.role !== 'pack').reduce((a, r) => a + r.qty, 0);
    if (raw < 700 || raw > 1100) qtyIssues.push(`${PRODUCTS[meta.pKey].name}: raw total ${raw}`);
  }
  check('quantities per 1000 kg plausible (flour 350–480, filling 400–600, packaging whole шт)', !qtyIssues.length, qtyIssues.join('; '));

  // ---- margin distribution ----
  const withMargin = cat.filter((r) => r.fullCost && r.sale > 0);
  const inBand = withMargin.filter((r) => r.margin >= 15 && r.margin <= 45);
  const low = withMargin.filter((r) => r.margin >= 5 && r.margin < MARGIN_THRESHOLD);
  const loss = withMargin.filter((r) => r.margin < 0);
  const odd = withMargin.filter((r) => (r.margin >= 0 && r.margin < 5) || r.margin > 48);
  check('most margins in 15–45 %', inBand.length / withMargin.length >= 0.75, `${inBand.length} of ${withMargin.length}`);
  check('a few low-margin 5–19 % (НИЗЬКА МАРЖА)', low.length >= 3 && low.length <= 8, low.map((r) => r.margin).join(', '));
  check('3–4 loss-making', loss.length >= 3 && loss.length <= 4 && loss.filter((r) => r.active).length >= 3,
    loss.map((r) => `${r.margin}${r.active ? '' : ' (неактивна)'}`).join(', '));
  check('no margins in 0–5 % or above 48 %', !odd.length, odd.map((r) => r.name + ' ' + r.margin).join('; '));
  const tie = cat.filter((r) => nearTie(r.costRaw, 4) || nearTie(r.cost, 2) || (r.saleRaw != null && nearTie(r.saleRaw, 4))
    || (r.markupRaw != null && nearTie(r.markupRaw, 2)) || (r.marginRaw != null && nearTie(r.marginRaw, 2)));
  check('no .5 rounding ties in cost / sale / markup / margin', !tie.length, tie.map((r) => r.name).join('; '));

  // ---- edge cases ----
  const usedBy = (pred) => active.filter((r) => data.rows.some((row) => row.spec === r.id && pred(row)));
  const noPriceMats = Object.keys(data.materials).filter((m) => !Object.keys(data.purchasePrices).some((k) => k.startsWith(m + '|')));
  check('material without any purchase price (НЕМАЄ ЦІН)', noPriceMats.length >= 1 && usedBy((row) => noPriceMats.includes(row.material)).length >= 1,
    noPriceMats.map((m) => data.materials[m]).join(', '));
  const eurKeys = Object.keys(data.purchasePrices).filter((k) => data.purchasePrices[k].currency === 'EUR');
  check('material priced in EUR', eurKeys.length >= 1 && usedBy((row) => eurKeys.includes(row.material + '|' + (row.char || ''))).length >= 1,
    eurKeys.map((k) => data.materials[k.split('|')[0]]).join(', '));
  const multiMissing = active.filter((r) => r.materials - r.pricesFound >= 2);
  check('one recipe missing two prices (НЕМАЄ ЦІН: 2)', multiMissing.length >= 1, multiMissing.map((r) => r.name).join('; '));
  const eurSales = cat.filter((r) => r.saleInfo && r.saleInfo.status === 'ЦІНА В ІНШІЙ ВАЛЮТІ: EUR');
  check('export sales in EUR (ЦІНА В ІНШІЙ ВАЛЮТІ: EUR)', eurSales.length >= 2 && eurSales.every((r) => r.categoryCode.startsWith('EX_')),
    eurSales.map((r) => r.categoryCode).join(', '));
  const pdv = cat.filter((r) => r.saleInfo && r.saleInfo.status === 'ПЕРЕВІР ПДВ У РОЗХІДНІЙ' && r.active);
  check('ПЕРЕВІР ПДВ У РОЗХІДНІЙ', pdv.length >= 1);
  const noSale = active.filter((r) => !r.saleInfo);
  check('active product without sales (НЕМАЄ ПРОДАЖУ)', noSale.length >= 1, noSale.map((r) => r.name).join('; '));
  const pcs = cat.filter((r) => r.saleInfo && r.saleInfo.unit === 'шт' && r.saleInfo.boxKg === 0 && r.saleInfo.status === 'OK' && r.active);
  check('unit "шт" with boxKg 0 (НЕ ВИЗНАЧЕНО ВАГУ)', pcs.length >= 1 && pcs.every((r) => r.problem === 'НЕ ВИЗНАЧЕНО ВАГУ'));
  const kgSales = Object.values(data.sales).filter((s) => s.unit === 'кг' && s.boxKg === 1);
  check('sales by "кг" (box weight 1)', kgSales.length >= 1);
  check('sale units parse like ИзвлечьВесЯщикаКг', Object.values(data.sales).every((s) => extractBoxKg(s.unit) === s.boxKg));
  check('sale VAT consistent', Object.values(data.sales).every((s) => s.status !== 'OK'
    || Math.abs(s.withVat - s.exVat) < 1e-9 || Math.abs(s.withVat - s.exVat * 1.2) < 0.0001));
  const cot = ids.material('cottage');
  const own = data.purchasePrices[cot + '|' + ids.char('c9')];
  const fall = data.purchasePrices[cot + '|' + ids.char('c5')];
  const base = data.purchasePrices[cot + '|'];
  check('characteristics 5% / 9% used', data.rows.some((r) => r.char === ids.char('c5')) && data.rows.some((r) => r.char === ids.char('c9')));
  check('9% has its own price', own && base && own.doc !== base.doc && own.exVat !== base.exVat, own ? `${own.exVat} vs ${base.exVat}` : '');
  check('5% falls back to the material-only price', fall && base && JSON.stringify(fall) === JSON.stringify(base));
  const staleKeys = Object.keys(data.purchasePrices).filter((k) => daysBefore(data.purchasePrices[k].date, now) > STALE_DAYS);
  const staleRecipes = usedBy((row) => staleKeys.includes(row.material + '|' + (row.char || '')));
  check('purchase dates older than 90 days, used by some recipes', staleKeys.length >= 2 && staleRecipes.length >= 4
    && staleRecipes.length <= active.length / 3, `${staleKeys.map((k) => data.materials[k.split('|')[0]]).join(', ')} → ${staleRecipes.length} recipes`);
  const recommendable = (r) => !data.rows.some((row) => row.spec === r.id && staleKeys.includes(row.material + '|' + (row.char || '')));
  check('loss / low-margin recipes reach the recommendations (fresh prices)',
    loss.filter((r) => r.active && recommendable(r)).length >= 2 && low.filter((r) => r.active && recommendable(r)).length >= 2);
  check('empty document currency counts as UAH', Object.values(data.purchasePrices).some((p) => p.currency === ''));

  // ---- history ----
  const histIds = Object.keys(data.history);
  const kinds = { changed: 0, identicalUsesPrevious: 0, identicalNoPrevious: 0 };
  for (const id of histIds) {
    const r = byId.get(id);
    const idx = prevIndex(r, data.history[id]);
    if (idx === 1) kinds.identicalUsesPrevious++;
    else if (snapshotsDiffer(snapFromRecipe(r), snapFromHistory(data.history[id][0]))) kinds.changed++;
    else kinds.identicalNoPrevious++;
  }
  check('history for ~half of the recipes', histIds.length / cat.length >= 0.4 && histIds.length / cat.length <= 0.6,
    `${histIds.length} of ${cat.length}`);
  check('history: some changed, some identical (previous-previous used)', kinds.changed >= 5 && kinds.identicalUsesPrevious >= 5,
    JSON.stringify(kinds));
  const prevNoSale = histIds.filter((id) => data.history[id][0].sale === 0 && byId.get(id).hasSale);
  const prevPartial = histIds.filter((id) => data.history[id][0].pricesFound < data.history[id][0].materials && byId.get(id).fullCost);
  check('history: earlier snapshot without sale / with partial cost', prevNoSale.length >= 1 && prevPartial.length >= 1);
  check('messages: 3–4 diagnostics', data.messages.length >= 3 && data.messages.length <= 4);

  // ---- problem distribution ----
  const dist = {};
  for (const r of active) if (r.problem !== 'OK') dist[r.problem] = (dist[r.problem] || 0) + 1;
  console.log('\nActive: ' + active.length + ', inactive: ' + inactive.length + ', rows: ' + data.rows.length
    + ', materials: ' + matCount + ', purchase prices: ' + Object.keys(data.purchasePrices).length + ', sales: ' + Object.keys(data.sales).length
    + ', history: ' + histIds.length);
  console.log('Problems among active (control centre): ' + Object.values(dist).reduce((a, b) => a + b, 0) + ' → '
    + Object.entries(dist).sort().map(([k, v]) => `${k}=${v}`).join(', '));
  const avg = withMargin.filter((r) => r.active);
  console.log('Average margin (active, complete): ' + round(avg.reduce((a, r) => a + r.margin, 0) / avg.length, 2) + ' %');

  console.log('\nSelf-check');
  for (const c of checks) console.log(`  ${c.ok ? 'ok  ' : 'FAIL'}  ${c.name}${c.detail ? '  [' + c.detail + ']' : ''}`);
  return { ok: checks.every((c) => c.ok), cat, matKeyById };
}

// ============================================================================
// Cross-check against src/core.js (written by another agent; read-only here)
// ============================================================================

function crossCheckCore(data, cat) {
  if (!existsSync(CORE_JS)) { console.log('\nsrc/core.js not found — core cross-check skipped.'); return; }
  let core;
  try {
    const require = createRequire(import.meta.url);
    delete require.cache[CORE_JS];
    core = require(CORE_JS);
  } catch (e) { console.log('\nsrc/core.js could not be loaded: ' + e.message); return; }
  if (!core || typeof core.buildModel !== 'function') { console.log('\nsrc/core.js has no buildModel — skipped.'); return; }
  try {
    if (typeof core.validateData === 'function') {
      const v = core.validateData(JSON.parse(JSON.stringify(data)));
      console.log(`\ncore.validateData: ok=${v.ok}, errors=${v.errors.length}, warnings=${v.warnings.length}`
        + (v.errors.length ? '\n    ' + v.errors.join('\n    ') : '') + (v.warnings.length ? '\n    ' + v.warnings.slice(0, 8).join('\n    ') : ''));
    }
    const model = core.buildModel(JSON.parse(JSON.stringify(data)), { marginThreshold: MARGIN_THRESHOLD });
    const recipes = model.recipes || [];
    const dist = {};
    for (const r of recipes) if (r.active && r.problem !== 'OK') dist[r.problem] = (dist[r.problem] || 0) + 1;
    console.log(`core.buildModel: ${recipes.length} recipes, counts=${JSON.stringify(model.counts || {})}, compared=${model.comparedCount}`);
    console.log('core problems among active: ' + Object.entries(dist).sort().map(([k, v]) => `${k}=${v}`).join(', '));
    const mismatches = [];
    const order = recipes.map((r) => r.id).join() === cat.map((r) => r.id).join();
    for (const mine of cat) {
      const r = recipes.find((x) => x.id === mine.id);
      if (!r) { mismatches.push(mine.name + ': missing'); continue; }
      for (const f of ['cost', 'sale', 'markup', 'margin', 'problem', 'dataStatus', 'materials', 'pricesFound', 'active', 'categoryPath']) {
        if (r[f] !== mine[f]) mismatches.push(`${mine.name}: ${f} core=${r[f]} gen=${mine[f]}`);
      }
      const hist = data.history[mine.id];
      const idx = prevIndex(mine, hist);
      if (idx != null && r.prev !== undefined) {
        const exp = hist[idx];
        if (!r.prev || r.prev.period !== exp.period) mismatches.push(`${mine.name}: prev period core=${r.prev && r.prev.period} gen=${exp.period}`);
      } else if (idx == null && r.prev) mismatches.push(`${mine.name}: core has prev, generator expects none`);
    }
    console.log(`core vs generator: tree order ${order ? 'identical' : 'DIFFERENT'}; field mismatches: ${mismatches.length}`
      + (mismatches.length ? '\n    ' + mismatches.slice(0, 20).join('\n    ') : ''));
  } catch (e) {
    console.log('core cross-check failed: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e));
  }
}

// ============================================================================
// Output
// ============================================================================

/** JSON with one record per line (rows, prices, sales, history) — compact but diff-friendly. */
function formatJson(data) {
  const lines = ['{'];
  const keys = Object.keys(data);
  keys.forEach((k, i) => {
    const v = data[k];
    const comma2 = i < keys.length - 1 ? ',' : '';
    if (Array.isArray(v) && v.length && typeof v[0] === 'object') {
      lines.push(`  ${JSON.stringify(k)}: [`);
      v.forEach((x, j) => lines.push('    ' + JSON.stringify(x) + (j < v.length - 1 ? ',' : '')));
      lines.push('  ]' + comma2);
    } else if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length) {
      const ek = Object.keys(v);
      lines.push(`  ${JSON.stringify(k)}: {`);
      ek.forEach((e, j) => lines.push(`    ${JSON.stringify(e)}: ${JSON.stringify(v[e])}` + (j < ek.length - 1 ? ',' : '')));
      lines.push('  }' + comma2);
    } else if (Array.isArray(v) && v.length) {
      lines.push(`  ${JSON.stringify(k)}: [`);
      v.forEach((x, j) => lines.push('    ' + JSON.stringify(x) + (j < v.length - 1 ? ',' : '')));
      lines.push('  ]' + comma2);
    } else {
      lines.push(`  ${JSON.stringify(k)}: ${JSON.stringify(v)}${comma2}`);
    }
  });
  lines.push('}');
  return lines.join('\n');
}

const { data, internals } = build();
const result = selfCheck(data, internals);
crossCheckCore(data, result.cat);

const json = formatJson(data);
JSON.parse(json); // must round-trip
if (JSON.stringify(JSON.parse(json)) !== JSON.stringify(data)) throw new Error('formatter changed the data');

if (!result.ok) {
  console.error('\nSELF-CHECK FAILED — nothing written. Tune tools/make-demo.mjs.');
  process.exit(1);
}
if (CHECK_ONLY) {
  console.log('\n--check: all targets met, nothing written.');
} else {
  mkdirSync(dirname(OUT_JS), { recursive: true });
  mkdirSync(dirname(OUT_JSON), { recursive: true });
  const header = '/* ФОРТУНА — демо-дані (формат fortuna-data v1, docs/CONTRACT.md).\n'
    + '   Згенеровано tools/make-demo.mjs — не редагуйте вручну, запустіть: node tools/make-demo.mjs */\n';
  const js = header + '(function () {\n  var data = ' + json.replace(/\n/g, '\n  ') + ';\n'
    + "  if (typeof window !== 'undefined') window.FORTUNA_DEMO = data;\n"
    + "  if (typeof module !== 'undefined' && module.exports) module.exports = data;\n})();\n";
  writeFileSync(OUT_JS, js);
  writeFileSync(OUT_JSON, json + '\n');
  console.log(`\nWritten: ${OUT_JS} (${js.length} chars), ${OUT_JSON} (${json.length + 1} chars).`);
}
