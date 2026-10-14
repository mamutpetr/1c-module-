/*!
 * ФОРТУНА — розрахунковий модуль (core.js)
 * Port of the BAS/1C form module bas/original/fortuna-v5-form-module.bsl (v5.0):
 * the same formulas, rules and Ukrainian summary texts. No DOM, no imports, ES2019.
 * API reference: docs/CORE.md.  Browser: window.FortunaCore.  Node: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.FortunaCore = api;
  } else if (root && (typeof module !== 'object' || !module || !module.exports)) {
    root.FortunaCore = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var VERSION = '1.0.0';
  var NBSP = ' ';
  var HAS_OWN = Object.prototype.hasOwnProperty;

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  // Initial values of the form attributes (UX40/UX42/NX50_СоздатьРеквизиты) + methodology defaults.
  var DEFAULTS = Object.freeze({
    marginThreshold: 20,      // UX40_ПорогМаржи
    targetMargin: 25,         // UX40_ЦелеваяМаржа
    extraCost: 0,             // UX40_ДопЗатраты
    volumeKg: 1000,           // UX40_ОбъемКг
    impactPercent: 10,        // UX42_Процент
    staleDays: 90,            // UX42_ДнейАктуальности
    planKg: 1000,             // NX50_КгПлана
    constructorQty: 1,        // NX50_НоваяКоличество
    priceMargin: 25,          // NX50_МаржаПрайса
    priceStep: 0.05,          // NX50_ШагЦены
    kwhPerTon: 250,           // NX50_ЭнергияКВтЧТ
    tariffA: 4,               // NX50_ТарифА
    tariffB: 8,               // NX50_ТарифБ
    energyVolumeKg: 1000,     // NX50_ЭнергияОбъемКг
    batchKg: 1000,            // рецептури на 1000 кг
    processingPerTon: 50000,  // переробка 50 000 грн/т
    historyTag: 'v3.3 грн/кг; переробка 50000 грн/т'
  });

  // Texts of the summary fields before any calculation (as set in *_СоздатьРеквизиты).
  var INITIAL_TEXTS = Object.freeze({
    kpi: '—',
    search: 'Спочатку натисніть «Оновити дані»',
    scenario: 'Спочатку виберіть рецептуру.',
    impact: 'Після оновлення даних виберіть матеріал і натисніть «Розрахувати».',
    compare: 'Виберіть дві специфікації та натисніть «Порівняти».',
    quality: 'Натисніть «Оновити дані».',
    advice: 'Рекомендації формуються після завантаження калькуляцій.',
    plan: 'Дані не завантажені. Натисніть «Оновити» у шапці.',
    stock: 'Склад — ручний сценарій, НЕ фактичні залишки BAS.',
    constructorSummary: 'Сценарій рецепта не змінює Спецификации.',
    constructorPricesUpdated: 'Ціни BAS оновлені; натисніть «Перерахувати» для актуалізації сценарію.',
    priceList: 'Прайс лише для перегляду; без запису цін у BAS.',
    energy: 'Енергія — окремий сценарій, не додавати повторно до переробки 50 000 грн/т.',
    assistantQuestion: 'Скільки рецептів?',
    assistant: "Локальний помічник на правилах. Не під'єднаний до AI API.",
    details: 'Оберіть рецептуру у верхній таблиці.'
  });

  // [code, name, group, subgroup, label] — order of the tree / НазначитьКатегориюНаСервере whitelist.
  var CATEGORY_DEFS = [
    ['UA_RUD', 'Рудь', 'УКРАЇНА', null, 'Україна / Рудь'],
    ['UA_SILPO', 'Сільпо', 'УКРАЇНА', null, 'Україна / Сільпо'],
    ['UA_METRO', 'Метро', 'УКРАЇНА', null, 'Україна / Метро'],
    ['UA_FEDYK', 'Федик', 'УКРАЇНА', 'Привати', 'Україна / Привати / Федик'],
    ['UA_OP', 'ОП', 'УКРАЇНА', 'Привати', 'Україна / Привати / ОП'],
    ['UA_MIDAS', 'Мидас', 'УКРАЇНА', 'Привати', 'Україна / Привати / Мидас'],
    ['EX_DOVGAN', 'Довгань', 'ЕКСПОРТ', null, 'Експорт / Довгань'],
    ['EX_ITALY', 'Італія', 'ЕКСПОРТ', null, 'Експорт / Італія'],
    ['EX_ROMANIA', 'Румунія', 'ЕКСПОРТ', null, 'Експорт / Румунія'],
    ['EX_GEYA', 'Гея Фуд', 'ЕКСПОРТ', null, 'Експорт / Гея Фуд'],
    ['EX_CZECH', 'Чехія', 'ЕКСПОРТ', null, 'Експорт / Чехія'],
    ['EX_ISRAEL', 'Ізраїль', 'ЕКСПОРТ', null, 'Експорт / Ізраїль'],
    ['NONE', 'Без категорії', null, null, 'Без категорії']
  ];
  var ROOT_ACTIVE = 'ВИКОРИСТОВУЮТЬСЯ';
  var ROOT_INACTIVE = 'НЕ ВИКОРИСТОВУЮТЬСЯ';

  var CATEGORIES = Object.freeze(CATEGORY_DEFS.map(function (d) {
    var path = [ROOT_ACTIVE];
    if (d[2]) path.push(d[2]);
    if (d[3]) path.push(d[3]);
    path.push(d[1]);
    return Object.freeze({
      code: d[0], name: d[1], group: d[2], subgroup: d[3],
      path: Object.freeze(path), label: d[4]
    });
  }));
  var CATEGORY_BY_CODE = Object.freeze(CATEGORIES.reduce(function (acc, c) {
    acc[c.code] = c;
    return acc;
  }, {}));
  // Codes that have their own folder in ЗагрузитьВсеНаСервере (ВеткиКатегорий): everything except NONE.
  function isChannelCode(code) {
    return code !== 'NONE' && HAS_OWN.call(CATEGORY_BY_CODE, code);
  }

  // Static folder tree of ЗагрузитьВсеНаСервере (names and order are exact).
  function leaf(code) {
    return { key: code, name: CATEGORY_BY_CODE[code].name, code: code, children: [] };
  }
  var FOLDER_TREE = deepFreeze([
    { key: 'ACTIVE', name: ROOT_ACTIVE, code: null, children: [
      { key: 'UA', name: 'УКРАЇНА', code: null, children: [
        leaf('UA_RUD'), leaf('UA_SILPO'), leaf('UA_METRO'),
        { key: 'UA_PRIVATE', name: 'Привати', code: null, children: [
          leaf('UA_FEDYK'), leaf('UA_OP'), leaf('UA_MIDAS')
        ] }
      ] },
      { key: 'EX', name: 'ЕКСПОРТ', code: null, children: [
        leaf('EX_DOVGAN'), leaf('EX_ITALY'), leaf('EX_ROMANIA'),
        leaf('EX_GEYA'), leaf('EX_CZECH'), leaf('EX_ISRAEL')
      ] },
      leaf('NONE')
    ] },
    { key: 'INACTIVE', name: ROOT_INACTIVE, code: null, children: [] }
  ]);

  var SEARCH_MODES = deepFreeze([
    { code: 'ALL', bsl: 'ВСЕ', label: 'Всі' },
    { code: 'ACTIVE', bsl: 'АКТИВНЫЕ', label: 'Активні' },
    { code: 'NO_CATEGORY', bsl: 'БЕЗ_КАТ', label: 'Без категорії' },
    { code: 'PROBLEMS', bsl: 'ПРОБЛЕМЫ', label: 'Проблемні' },
    { code: 'LOW_MARGIN', bsl: 'НИЗКАЯ_МАРЖА', label: 'Низька маржа' }
  ]);

  // Priorities exactly as UX40_ПриоритетПроблемы returns them (see the note on НЕМАЄ ЦІНИ ПРОДАЖУ).
  var PROBLEM_TYPES = deepFreeze([
    { group: 'ЗБИТКОВА ПОЗИЦІЯ', priority: 1 },
    { group: 'НЕМАЄ ЦІН', priority: 2 },
    { group: 'НЕМАЄ СКЛАДУ', priority: 2 },
    { group: 'НЕМАЄ ЦІНИ ПРОДАЖУ', priority: 2 },
    { group: 'НЕ ВИЗНАЧЕНО ВАГУ', priority: 3 },
    { group: 'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ', priority: 3 },
    { group: 'НИЗЬКА МАРЖА', priority: 4 },
    { group: 'OK', priority: 9 }
  ]);

  var ASSISTANT_COMMANDS = Object.freeze([
    'рецепти', 'проблеми', 'немає цін', 'найдорожчий', 'план', 'енергія', 'маржа', 'збиткові', 'допомога'
  ]);

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------

  function deepFreeze(o) {
    if (o && typeof o === 'object' && !Object.isFrozen(o)) {
      Object.keys(o).forEach(function (k) { deepFreeze(o[k]); });
      Object.freeze(o);
    }
    return o;
  }
  function has(o, k) { return o != null && HAS_OWN.call(o, k); }
  function str(v) { return v == null ? '' : String(v); }
  function trim(v) { return str(v).trim(); }                 // СокрЛП
  function lower(v) { return str(v).toLowerCase(); }         // НРег
  function upper(v) { return str(v).toUpperCase(); }         // ВРег
  function isObj(v) { return v != null && typeof v === 'object' && !Array.isArray(v); }
  function obj(v) { return isObj(v) ? v : {}; }
  function arr(v) { return Array.isArray(v) ? v : []; }
  function cmpText(a, b) { return str(a).localeCompare(str(b), 'uk'); }

  // Number from a JSON value or a user-typed string ("12,5", "1 000"); `def` when not a finite number.
  function num(v, def) {
    if (def === undefined) def = 0;
    if (typeof v === 'number') return isFinite(v) ? v : def;
    if (typeof v === 'string') {
      var s = v.replace(/[\s  ]/g, '').replace(',', '.');
      if (s === '') return def;
      var n = Number(s);
      return isFinite(n) ? n : def;
    }
    return def;
  }
  function isFilled(v) { return v != null && v !== ''; }      // ЗначениеЗаполнено for ids
  function idOf(v) { return isFilled(v) ? String(v) : null; }

  // ---------------------------------------------------------------------------
  // Numbers: Окр, Строка(Число), Формат(x, "ЧДЦ=n")
  // ---------------------------------------------------------------------------

  // Remove binary float noise (1C works in decimal): keep 15 significant digits.
  function clean(x) {
    var n = Number(x);
    if (!isFinite(n)) return 0;
    n = Number(n.toPrecision(15));
    return n === 0 ? 0 : n;
  }
  // x × 10^k without binary error, via the exponent of the decimal string.
  function shiftDec(x, k) {
    var p = String(x).split('e');
    return Number(p[0] + 'e' + (Number(p[1] || 0) + k));
  }
  // Окр(x, n): half away from zero on the decimal value.
  function round(x, digits) {
    var d = digits == null ? 0 : Math.trunc(num(digits));
    var n = clean(num(x, 0));
    if (n === 0) return 0;
    var shifted = shiftDec(Math.abs(n), d);
    if (!isFinite(shifted)) return n;
    var r = shiftDec(Math.round(shifted), -d);
    r = n < 0 ? -r : r;
    return r === 0 ? 0 : r;
  }
  function repeat(ch, n) { var s = ''; while (n-- > 0) s += ch; return s; }
  // Non-negative finite number → plain decimal string without exponent.
  function plain(abs) {
    var s = String(abs);
    if (s.indexOf('e') < 0) return s;
    var p = s.split('e');
    var mant = p[0].split('.');
    var digits = mant[0] + (mant[1] || '');
    var point = mant[0].length + Number(p[1]);
    if (point <= 0) return '0.' + repeat('0', -point) + digits;
    if (point >= digits.length) return digits + repeat('0', point - digits.length);
    return digits.slice(0, point) + '.' + digits.slice(point);
  }
  function groupInt(s) { return s.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP); }

  // Строка(Число): "1 234,5", "0", "-12,25".
  function fmtNum(x) {
    var n = clean(num(x, 0));
    if (n === 0) return '0';
    var parts = plain(Math.abs(n)).split('.');
    return (n < 0 ? '-' : '') + groupInt(parts[0]) + (parts[1] ? ',' + parts[1] : '');
  }
  // Формат(x, "ЧДЦ=n"): always n decimals, grouped. (1C prints '' for 0; we print zeros.)
  function fmtFixed(x, digits) {
    var d = Math.max(0, Math.trunc(num(digits)));
    var n = round(x, d);
    var parts = plain(Math.abs(n)).split('.');
    var frac = parts[1] || '';
    while (frac.length < d) frac += '0';
    return (n < 0 ? '-' : '') + groupInt(parts[0]) + (d > 0 ? ',' + frac : '');
  }
  function fmt2(x) { return fmtFixed(x, 2); }
  // Number for TSV/Excel: decimal comma, no grouping.
  function tsvNum(x) { return fmtNum(x).replace(/ /g, ''); }

  // ---------------------------------------------------------------------------
  // Dates. Contract dates are naive local times "2026-10-14T09:30:00" (as ЗаписатьJSON writes them).
  // Comparisons use "naive ms" (components read as UTC) so that DST never shifts day arithmetic.
  // ---------------------------------------------------------------------------

  var ISO_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?/;

  function dateParts(v) {
    if (v == null || v === '') return null;
    var p;
    if (Object.prototype.toString.call(v) === '[object Date]') {
      if (isNaN(v.getTime())) return null;
      p = [v.getFullYear(), v.getMonth() + 1, v.getDate(), v.getHours(), v.getMinutes(), v.getSeconds()];
    } else if (typeof v === 'number') {
      return isFinite(v) ? dateParts(new Date(v)) : null;
    } else {
      var m = ISO_RE.exec(String(v).trim());
      if (!m) return null;
      p = [+m[1], +m[2], +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)];
      if (p[1] < 1 || p[1] > 12 || p[2] < 1 || p[2] > 31 || p[3] > 23 || p[4] > 59 || p[5] > 59) return null;
    }
    // 0001-01-01T00:00:00 is the empty date of 1C.
    if (p[0] === 1 && p[1] === 1 && p[2] === 1 && p[3] === 0 && p[4] === 0 && p[5] === 0) return null;
    return p;
  }
  function parseDate(v) {
    var p = dateParts(v);
    if (!p) return null;
    var d = new Date(p[0], p[1] - 1, p[2], p[3], p[4], p[5]);
    if (p[0] < 100) d.setFullYear(p[0], p[1] - 1, p[2]);
    return d;
  }
  function naiveMs(v) {
    var p = dateParts(v);
    if (!p) return null;
    var d = new Date(Date.UTC(2000, 0, 1, p[3], p[4], p[5]));
    d.setUTCFullYear(p[0], p[1] - 1, p[2]);
    return d.getTime();
  }
  function fromNaiveMs(ms) {
    var u = new Date(ms);
    var d = new Date(2000, 0, 1, u.getUTCHours(), u.getUTCMinutes(), u.getUTCSeconds());
    d.setFullYear(u.getUTCFullYear(), u.getUTCMonth(), u.getUTCDate());
    return d;
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function fmtDate(v) {
    var p = dateParts(v);
    return p ? pad2(p[2]) + '.' + pad2(p[1]) + '.' + p[0] : '';
  }
  function fmtDateTime(v) {
    var p = dateParts(v);
    return p ? fmtDate(v) + ' ' + pad2(p[3]) + ':' + pad2(p[4]) : '';
  }

  // ---------------------------------------------------------------------------
  // Primitives
  // ---------------------------------------------------------------------------

  // ЭтоГривнаИлиПусто
  function isUah(currency) {
    var t = lower(trim(currency));
    if (t === '') return true;
    return t.indexOf('uah') >= 0 || t.indexOf('грн') >= 0 || t.indexOf('грив') >= 0;
  }
  function sameChar(a, b) { return (isFilled(a) ? String(a) : '') === (isFilled(b) ? String(b) : ''); }
  function priceKey(material, ch) { return str(material) + '|' + (isFilled(ch) ? String(ch) : ''); }
  function materialKey(material, ch) { return priceKey(material, ch); }

  // Per-material index of purchasePrices (built once per prices object).
  var priceIndexCache = typeof WeakMap === 'function' ? new WeakMap() : null;
  function priceIndex(prices) {
    var idx = priceIndexCache && priceIndexCache.get(prices);
    if (idx) return idx;
    idx = {};
    Object.keys(prices).forEach(function (key) {
      var bar = key.indexOf('|');
      if (bar < 0) return;
      var mat = key.slice(0, bar);
      (idx[mat] || (idx[mat] = [])).push({ ch: key.slice(bar + 1), price: prices[key] });
    });
    if (priceIndexCache) priceIndexCache.set(prices, idx);
    return idx;
  }
  // НайтиПоследнююЦену over the purchasePrices map.
  function findPrice(prices, material, ch) {
    if (!isObj(prices) || !isFilled(material)) return null;
    var mat = String(material);
    var c = isFilled(ch) ? String(ch) : '';
    if (c && isObj(prices[mat + '|' + c])) return prices[mat + '|' + c];   // own characteristic
    if (isObj(prices[mat + '|'])) return prices[mat + '|'];                // material without characteristic
    var list = priceIndex(prices)[mat];
    if (!list) return null;
    var best = null, bestMs = null;                                         // latest of any characteristic
    list.forEach(function (e) {
      if (!isObj(e.price)) return;
      var ms = naiveMs(e.price.date);
      if (best === null || (ms !== null && (bestMs === null || ms > bestMs))) {
        best = e.price;
        bestMs = ms;
      }
    });
    return best;
  }

  // ИзвлечьВесЯщикаКг: "ящ (2,34 кг)" -> 2.34; "кг" -> 1; unknown formats -> 0.
  function extractBoxKg(unit) {
    var text = lower(trim(unit));
    if (text === '') return 0;
    if (text === 'кг' || text === 'кілограм') return 1;
    var posKg = text.indexOf('кг');
    if (posKg < 0) return 0;
    var posBracket = text.lastIndexOf('(', posKg - 1);
    var numText = posBracket >= 0 ? text.slice(posBracket + 1, posKg) : text.slice(0, posKg);
    numText = numText.trim().replace(/ /g, '').replace(/\./g, ',');
    if (numText === '') return 0;
    var commas = 0;
    for (var i = 0; i < numText.length; i++) {
      var ch = numText.charAt(i);
      if (ch === ',') {
        commas += 1;
        if (commas > 1) return 0;
      } else if ('0123456789'.indexOf(ch) < 0) {
        return 0;
      }
    }
    var kg = Number(numText.replace(',', '.'));
    return isFinite(kg) && kg > 0 && kg <= 1000 ? kg : 0;
  }

  function categoryByCode(code) {
    return has(CATEGORY_BY_CODE, code) ? CATEGORY_BY_CODE[code] : null;
  }

  // UX40_ТипПроблемы. row: {materials, pricesFound, dataStatus, sale, cost, margin}.
  function problemType(row, threshold) {
    row = row || {};
    var materials = num(row.materials), found = num(row.pricesFound);
    var src = upper(row.dataStatus);
    var limit = num(threshold, DEFAULTS.marginThreshold);
    if (materials === 0) return 'НЕМАЄ СКЛАДУ';
    if (materials !== found) return 'НЕМАЄ ЦІН: ' + fmtNum(materials - found);
    if (src.indexOf('ВАГУ') >= 0) return 'НЕ ВИЗНАЧЕНО ВАГУ';
    if (src.indexOf('ВАЛЮТ') >= 0 || src.indexOf('ПДВ') >= 0) return 'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ';
    if (num(row.sale) <= 0) return 'НЕМАЄ ЦІНИ ПРОДАЖУ';
    if (num(row.sale) < num(row.cost)) return 'ЗБИТКОВА ПОЗИЦІЯ';
    if (num(row.margin) < limit) return 'НИЗЬКА МАРЖА';
    return 'OK';
  }
  // UX40_ПриоритетПроблемы (substring test first: "НЕМАЄ ЦІНИ ПРОДАЖУ" contains "НЕМАЄ ЦІН" → 2).
  function problemPriority(problem) {
    var p = str(problem);
    if (p === 'ЗБИТКОВА ПОЗИЦІЯ') return 1;
    if (p.indexOf('НЕМАЄ ЦІН') >= 0 || p === 'НЕМАЄ СКЛАДУ') return 2;
    if (p === 'НЕ ВИЗНАЧЕНО ВАГУ' || p === 'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ' || p === 'НЕМАЄ ЦІНИ ПРОДАЖУ') return 3;
    if (p === 'НИЗЬКА МАРЖА') return 4;
    return 9;
  }
  function problemGroup(problem) { return str(problem).replace(/:[\s \d,-]*$/, ''); }

  // СнимкиОтличаются
  function snapshotsDiffer(a, b) {
    if (!b) return true;
    a = a || {};
    return round(a.sale, 2) !== round(b.sale, 2)
      || round(a.cost, 2) !== round(b.cost, 2)
      || round(a.markup, 2) !== round(b.markup, 2)
      || !!a.hasSale !== !!b.hasSale
      || !!a.fullCost !== !!b.fullCost
      || !!a.hasMarkup !== !!b.hasMarkup
      || num(a.materials) !== num(b.materials)
      || num(a.pricesFound) !== num(b.pricesFound);
  }
  // A history register entry → snapshot with flags (ЗагрузитьИсториюКалькуляций).
  function historySnapshot(e) {
    e = obj(e);
    var s = {
      period: e.period == null ? null : String(e.period),
      sale: num(e.sale), cost: num(e.cost), markup: num(e.markup),
      materials: num(e.materials), pricesFound: num(e.pricesFound)
    };
    s.hasSale = s.sale > 0;
    s.fullCost = s.materials > 0 && s.materials === s.pricesFound && s.cost > 0;
    s.hasMarkup = s.hasSale && s.fullCost;
    return s;
  }
  function currentSnapshot(r) {
    return {
      period: null, sale: r.sale, cost: r.cost, markup: r.markup, materials: r.materials,
      pricesFound: r.pricesFound, hasSale: r.hasSale, fullCost: r.fullCost, hasMarkup: r.hasMarkup
    };
  }

  // ---------------------------------------------------------------------------
  // buildModel — ЗагрузитьВсеНаСервере + UX40_ПостроитьВитринуНаСервере + UX40_ОбойтиДерево + UX42 cache
  // ---------------------------------------------------------------------------

  function methodologyOf(data) {
    var m = obj(data && data.methodology);
    var batchKg = num(m.batchKg, DEFAULTS.batchKg);
    if (!(batchKg > 0)) batchKg = DEFAULTS.batchKg;
    var processingPerTon = num(m.processingPerTon, DEFAULTS.processingPerTon);
    return {
      batchKg: batchKg,
      processingPerTon: processingPerTon,
      processingPerBatch: round(processingPerTon * batchKg / 1000, 4),
      historyTag: m.historyTag ? String(m.historyTag) : DEFAULTS.historyTag
    };
  }

  // A composition row the BSL would see: spec + material filled, quantity <> 0 (query filter).
  function isUsableRow(row) {
    return isObj(row) && isFilled(row.spec) && isFilled(row.material) && num(row.qty, 0) !== 0;
  }

  function indexSpecs(specs) {
    var idx = {};
    arr(specs).forEach(function (s) {
      if (isObj(s) && isFilled(s.id) && !has(idx, String(s.id))) idx[String(s.id)] = s;
    });
    return idx;
  }

  function createTree() {
    var byKey = {};
    function copy(def, parentPath) {
      var pathArr = parentPath.concat([def.name]);
      var node = {
        key: def.key, name: def.name, code: def.code, path: pathArr.join(' / '),
        pathArr: pathArr, children: [], recipes: [], count: 0
      };
      byKey[def.key] = node;
      node.children = def.children.map(function (c) { return copy(c, pathArr); });
      return node;
    }
    return { roots: FOLDER_TREE.map(function (d) { return copy(d, []); }), byKey: byKey };
  }

  // ОпределитьВеткуСпецификации: "стар" in the status → НЕ ВИКОРИСТОВУЮТЬСЯ.
  function isOldStatus(status) { return lower(trim(status)).indexOf('стар') >= 0; }

  function boxKgOf(sale) {
    return typeof sale.boxKg === 'number' && isFinite(sale.boxKg) ? sale.boxKg : extractBoxKg(sale.unit);
  }

  function historyList(entries) {
    var list = arr(entries).filter(isObj).map(historySnapshot);
    // Contract: newest first. Re-sort defensively when both periods are parseable (stable).
    return list.map(function (s, i) { return { s: s, i: i, ms: naiveMs(s.period) }; })
      .sort(function (a, b) {
        if (a.ms !== null && b.ms !== null && a.ms !== b.ms) return b.ms - a.ms;
        return a.i - b.i;
      })
      .map(function (x) { return x.s; });
  }

  function buildModel(data, opts) {
    data = isObj(data) ? data : {};
    opts = opts || {};
    var meth = methodologyOf(data);
    var specs = indexSpecs(data.specs);
    var products = obj(data.products), materials = obj(data.materials), chars = obj(data.characteristics);
    var prices = obj(data.purchasePrices), sales = obj(data.sales);
    var history = obj(data.history), serverCalc = obj(data.serverCalc);
    var rows = arr(data.rows);
    var tree = createTree();
    var byId = {}, created = [], sums = {};
    var countNew = 0, countOld = 0;

    // 1. Rows → recipes in their branch; Σ qty × price for UAH prices (exVat = 0 still counts as found).
    rows.forEach(function (row) {
      if (!isUsableRow(row)) return;
      var id = String(row.spec);
      var r = byId[id];
      if (!r) {
        var spec = has(specs, id) ? specs[id] : null;
        var status = spec ? str(spec.status) : '';
        var catRaw = spec ? trim(spec.category) : '';
        var code = isChannelCode(catRaw) ? catRaw : '';
        var old = isOldStatus(status);
        var folder = tree.byKey[old ? 'INACTIVE' : (code || 'NONE')];
        if (old) countOld += 1; else countNew += 1;
        var productId = spec ? idOf(spec.product) : null;
        var productName = productId ? str(products[productId]) : '';
        var specName = spec && isFilled(spec.name) ? String(spec.name) : id;
        r = {
          id: id, specName: specName, productId: productId, productName: productName,
          name: productName + ' — ' + specName,
          status: status, categoryRaw: catRaw, categoryCode: code,
          folderKey: folder.key, folderPath: folder.pathArr.slice(), categoryPath: folder.path,
          active: upper(folder.path).indexOf(ROOT_INACTIVE) < 0,
          materials: 0, pricesFound: 0, cost: 0, sale: 0, markup: 0, margin: 0,
          fullCost: false, hasSale: false, hasMarkup: false,
          dataStatus: '', problem: '', problemGroup: '', priority: 9,
          saleInfo: null, prev: null, serverCalc: null, parityOk: null
        };
        folder.recipes.push(id);
        byId[id] = r;
        sums[id] = 0;
        created.push(r);
      }
      r.materials += 1;
      var price = findPrice(prices, row.material, row.char);
      if (!price || !isUah(price.currency)) return;
      r.pricesFound += 1;
      // The tree column Себестоимость is Число(18,4): the running sum is stored with 4 decimals.
      sums[id] = round(sums[id] + num(row.qty) * num(price.exVat), 4);
    });

    // 2. Cost per kg incl. processing, status, sale per kg, markup (BSL lines 2670-2743).
    created.forEach(function (r) {
      r.cost = round((sums[r.id] + meth.processingPerBatch) / meth.batchKg, 4);
      var st = r.materials === r.pricesFound ? 'OK' : 'НЕМАЄ ЦІН: ' + fmtNum(r.materials - r.pricesFound);
      var sale = r.productId && isObj(sales[r.productId]) ? sales[r.productId] : null;
      r.saleInfo = sale;
      if (!sale) {
        st += '; НЕМАЄ ПРОДАЖУ';
      } else {
        var saleStatus = sale.status == null ? 'OK' : str(sale.status);
        if (saleStatus !== 'OK') {
          st += '; ' + saleStatus;
        } else {
          var box = boxKgOf(sale);
          if (!(box > 0)) {
            st += '; НЕ ВИЗНАЧЕНО ВАГУ ЯЩИКА: ' + str(sale.unit);
          } else {
            r.sale = round(num(sale.exVat) / box, 4);
            if (r.materials === r.pricesFound && r.materials !== 0 && r.cost > 0) {
              r.markup = round((r.sale - r.cost) / r.cost * 100, 2);
            }
          }
        }
      }
      r.dataStatus = st;
      r.fullCost = r.materials > 0 && r.materials === r.pricesFound && r.cost > 0;
      r.hasSale = r.sale > 0;
      r.hasMarkup = r.fullCost && r.hasSale;
    });

    // 3. Було / Стало (BSL lines 2745-2819).
    var compared = 0;
    created.forEach(function (r) {
      var cur = currentSnapshot(r);
      var hist = historyList(history[r.id]);
      var was = hist.length ? hist[0] : null;
      var fromPrevious = false;
      if (was && !snapshotsDiffer(cur, was) && hist.length > 1) {
        was = hist[1];
        fromPrevious = true;
      }
      if (!was) return;
      compared += 1;
      r.prev = {
        period: was.period,
        fromPrevious: fromPrevious,
        changed: snapshotsDiffer(cur, was),
        sale: was.hasSale ? was.sale : null,
        saleDelta: was.hasSale && cur.hasSale ? round(r.sale - was.sale, 2) : null,
        cost: was.fullCost ? was.cost : null,
        costDelta: was.fullCost && cur.fullCost ? round(r.cost - was.cost, 2) : null,
        markup: was.hasMarkup ? was.markup : null,
        markupDelta: was.hasMarkup && cur.hasMarkup ? round(r.markup - was.markup, 2) : null
      };
    });

    // 4. Server parity (HTTP service only).
    created.forEach(function (r) {
      var sc = isObj(serverCalc[r.id]) ? serverCalc[r.id] : null;
      r.serverCalc = sc;
      if (sc) {
        r.parityOk = round(sc.cost, 2) === round(r.cost, 2)
          && round(sc.sale, 2) === round(r.sale, 2)
          && round(sc.markup, 2) === round(r.markup, 2);
      }
    });

    // 5. Catalogue in tree depth-first order (UX40_ОбойтиДерево): sub-folders first, then the folder's recipes.
    var catalogue = [];
    function walk(node) {
      var count = 0;
      node.children.forEach(function (c) { count += walk(c); });
      node.recipes.forEach(function (id) { catalogue.push(byId[id]); });
      node.count = count + node.recipes.length;
      return node.count;
    }
    tree.roots.forEach(walk);
    catalogue.forEach(function (r) {
      if (r.fullCost && r.sale > 0) r.margin = round((r.sale - r.cost) / r.sale * 100, 2);
    });

    // 6. UX42_Кэш (UX42_ОбновитьПослеЗагрузки): price available = found && UAH && exVat > 0.
    var cache = [];
    rows.forEach(function (row) {
      if (!isUsableRow(row)) return;
      var p = findPrice(prices, row.material, row.char);
      var available = !!p && isUah(p.currency) && num(p.exVat) > 0;
      cache.push({
        spec: String(row.spec), material: String(row.material), char: idOf(row.char),
        qty: round(num(row.qty), 4),
        price: available ? round(num(p.exVat), 4) : 0,
        priceDate: available && isFilled(p.date) ? String(p.date) : null,
        priceAvailable: available
      });
    });

    var model = {
      data: data,
      source: str(data.source), base: str(data.base), user: str(data.user),
      generatedAt: parseDate(data.generatedAt),
      methodology: meth,
      features: obj(data.features),
      messages: arr(data.messages).map(str),
      marginThreshold: DEFAULTS.marginThreshold,
      specs: specs, products: products, materials: materials, chars: chars,
      tree: tree.roots.map(stripTreeNode),
      recipes: catalogue,
      byId: byId,
      cache: cache,
      counts: { recipes: created.length, active: countNew, inactive: countOld, rows: rows.length },
      comparedCount: compared,
      summary: rows.length === 0 ? 'Рецептури не знайдено.'
        : 'ГОТОВО. Рецептур: ' + fmtNum(created.length)
          + ' | ВИКОРИСТОВУЮТЬСЯ: ' + fmtNum(countNew)
          + ' | НЕ ВИКОРИСТОВУЮТЬСЯ: ' + fmtNum(countOld)
          + ' | рядків складу: ' + fmtNum(rows.length)
          + ' | порівняно: ' + fmtNum(compared) + '.'
    };
    setMarginThreshold(model, opts.marginThreshold);
    return model;
  }
  function stripTreeNode(n) {
    return {
      key: n.key, name: n.name, code: n.code, path: n.path,
      children: n.children.map(stripTreeNode), recipes: n.recipes, count: n.count
    };
  }

  // Threshold change → UX40_ТипПроблемы / UX40_ПриоритетПроблемы for every catalogue row.
  function setMarginThreshold(model, threshold) {
    var t = round(num(threshold, model.marginThreshold == null ? DEFAULTS.marginThreshold : model.marginThreshold), 2);
    model.marginThreshold = t;
    model.recipes.forEach(function (r) {
      r.problem = problemType(r, t);
      r.problemGroup = problemGroup(r.problem);
      r.priority = problemPriority(r.problem);
    });
    return model;
  }
  function maybeThreshold(model, opts) {
    if (opts && opts.marginThreshold != null && opts.marginThreshold !== '') {
      setMarginThreshold(model, opts.marginThreshold);
    }
  }

  // ---------------------------------------------------------------------------
  // UX40_ПересчитатьКонтрольНаСервере
  // ---------------------------------------------------------------------------

  function control(model, opts) {
    maybeThreshold(model, opts);
    var problems = [], channels = [], chIndex = {};
    var sumMargin = 0, cntMargin = 0, active = 0, incomplete = 0;
    model.recipes.forEach(function (r) {
      var withMargin = r.fullCost && r.sale > 0;
      var isProblem = r.active && r.problem !== 'OK';
      if (r.active) active += 1;
      if (!r.fullCost) incomplete += 1;
      if (r.active && withMargin) {
        cntMargin += 1;
        sumMargin += r.margin;
      }
      if (isProblem) problems.push(r);
      var ch = has(chIndex, r.categoryPath) ? chIndex[r.categoryPath] : null;
      if (!ch) {
        ch = chIndex[r.categoryPath] = {
          channel: r.categoryPath, active: r.active, count: 0, problems: 0,
          avgMargin: null, marginCount: 0, _sum: 0
        };
        channels.push(ch);
      }
      ch.count += 1;
      if (isProblem) ch.problems += 1;
      if (withMargin) {
        ch._sum += r.margin;
        ch.marginCount += 1;
      }
    });
    problems.sort(function (a, b) { return a.priority - b.priority || a.margin - b.margin; });
    channels.forEach(function (ch) {
      if (ch.marginCount > 0) ch.avgMargin = round(ch._sum / ch.marginCount, 2);
      delete ch._sum;
    });
    var groupIndex = {}, groups = [];
    problems.forEach(function (r) {
      var g = groupIndex[r.problemGroup];
      if (!g) {
        g = groupIndex[r.problemGroup] = { group: r.problemGroup, priority: r.priority, count: 0 };
        groups.push(g);
      }
      g.count += 1;
    });
    groups.sort(function (a, b) { return a.priority - b.priority || cmpText(a.group, b.group); });
    var avg = cntMargin > 0 ? round(sumMargin / cntMargin, 2) : null;
    return {
      problems: problems,
      top: problems.slice(0, 12),
      groups: groups,
      channels: channels,
      kpi: {
        total: model.recipes.length,
        active: active,
        problems: problems.length,
        incomplete: incomplete,
        avgMargin: avg,
        avgMarginText: avg === null ? 'немає даних' : fmtNum(avg) + ' %',
        avgMarginNegative: cntMargin > 0 && clean(sumMargin) < 0
      },
      marginThreshold: model.marginThreshold
    };
  }

  // ---------------------------------------------------------------------------
  // UX40_ПрименитьПоискНаСервере
  // ---------------------------------------------------------------------------

  function normalizeMode(mode) {
    var m = str(mode);
    for (var i = 0; i < SEARCH_MODES.length; i++) {
      if (SEARCH_MODES[i].code === m || SEARCH_MODES[i].bsl === m) return SEARCH_MODES[i];
    }
    return SEARCH_MODES[0];
  }

  function search(model, opts) {
    opts = opts || {};
    maybeThreshold(model, opts);
    var phrase = lower(trim(opts.phrase));
    var mode = normalizeMode(opts.mode);
    var rows = model.recipes.filter(function (r) {
      if (phrase && lower(r.name + ' ' + r.categoryPath + ' ' + r.problem).indexOf(phrase) < 0) return false;
      switch (mode.code) {
        case 'ACTIVE': return r.active;
        case 'NO_CATEGORY': return lower(r.categoryPath).indexOf('без категорії') >= 0;
        case 'PROBLEMS': return r.problem !== 'OK';
        case 'LOW_MARGIN': return r.problem === 'НИЗЬКА МАРЖА';
        default: return true;
      }
    });
    var label = 'Знайдено: ' + fmtNum(rows.length) + ' із ' + fmtNum(model.recipes.length);
    return {
      rows: rows, count: rows.length, total: model.recipes.length, mode: mode.code,
      label: label, bslLabel: label + ' | Фільтр: ' + mode.bsl
    };
  }

  // ---------------------------------------------------------------------------
  // ЗагрузитьДеталиНаСервере
  // ---------------------------------------------------------------------------

  function nameOf(map, id) {
    if (!isFilled(id)) return '';
    var n = map ? map[String(id)] : undefined;
    return isFilled(n) ? String(n) : String(id);
  }

  function recipeDetails(model, id, prevPrices) {
    if (!isFilled(id)) return null;
    id = String(id);
    var spec = has(model.specs, id) ? model.specs[id] : null;
    var recipe = has(model.byId, id) ? model.byId[id] : null;
    if (!spec && !recipe) return null;
    var meth = model.methodology;
    var prices = obj(model.data && model.data.purchasePrices);
    var prev = isObj(prevPrices) && Object.keys(prevPrices).length > 0 ? prevPrices : null;
    var specName = spec && isFilled(spec.name) ? String(spec.name) : (recipe ? recipe.specName : id);
    var rows = [], total = 0, found = 0, count = 0;

    arr(model.data && model.data.rows).forEach(function (row) {
      if (!isUsableRow(row) || String(row.spec) !== id) return;
      count += 1;
      var ch = idOf(row.char);
      var out = {
        material: String(row.material), materialName: nameOf(model.materials, row.material),
        char: ch, charName: ch ? nameOf(model.chars, ch) : '',
        unit: str(row.unit), qty: round(num(row.qty), 4),
        priceWithVat: null, priceExVat: null, prevExVat: null, priceDelta: null, sum: null,
        priceDate: null, doc: null, currency: null, status: '', isProcessing: false
      };
      rows.push(out);
      var p = findPrice(prices, row.material, row.char);
      if (!p) {
        out.status = 'НЕМАЄ ЦІНИ';
        return;
      }
      out.priceDate = isFilled(p.date) ? String(p.date) : null;
      out.doc = p.doc == null ? null : str(p.doc);
      out.currency = p.currency == null ? null : str(p.currency);
      if (!isUah(p.currency)) {
        out.status = 'ІНША ВАЛЮТА: ' + str(p.currency);
        return;
      }
      out.priceWithVat = round(num(p.withVat), 4);
      out.priceExVat = round(num(p.exVat), 4);
      if (prev) {
        var key = priceKey(row.material, row.char);
        if (has(prev, key) && prev[key] != null) {
          var was = num(prev[key]);
          out.prevExVat = round(was, 4);
          out.priceDelta = round(num(p.exVat) - was, 2);
        }
      }
      out.sum = round(out.qty * out.priceExVat, 4);   // Сумма: Число(18,4)
      out.status = 'OK';
      total = round(total + out.sum, 4);
      found += 1;
    });

    // Processing row: shown separately, NOT added to the materials sum (already in the per-kg cost).
    rows.push({
      material: null, materialName: 'Переробка', char: null, charName: '',
      unit: 'т', qty: round(meth.batchKg / 1000, 4),
      priceWithVat: null, priceExVat: meth.processingPerTon, prevExVat: null, priceDelta: null,
      sum: meth.processingPerBatch, priceDate: null, doc: null, currency: null,
      status: 'ПЕРЕРОБКА (на 1 000 кг)', isProcessing: true
    });

    var grand = total + meth.processingPerBatch;
    return {
      id: id, recipe: recipe, specName: specName,
      rows: rows,
      totals: {
        materials: count, pricesFound: found, tableRows: count + 1,
        materialsSum: total, processing: meth.processingPerBatch,
        total: round(grand, 4), perKg: round(grand / meth.batchKg, 4)
      },
      summary: 'Специфікація: ' + specName
        + ' | Матеріалів: ' + fmtNum(count)
        + ' | Цін знайдено: ' + fmtNum(found)
        + ' | Рядків у таблиці: ' + fmtNum(count + 1)
        + ' | Матеріали на 1000 кг: ' + fmt2(total)
        + ' грн | Переробка: 50 000 грн/т'
        + ' | Разом на 1000 кг: ' + fmt2(grand)
        + ' грн | На 1 кг: ' + fmt2(grand / meth.batchKg)
        + ' грн/кг без ПДВ'
    };
  }

  // ---------------------------------------------------------------------------
  // UX40_ВыбратьРецептНаСервере + UX40_РассчитатьСценарийНаСервере
  // ---------------------------------------------------------------------------

  function priceScenario(model, id, inputs) {
    inputs = inputs || {};
    var targetMargin = round(num(inputs.targetMargin, DEFAULTS.targetMargin), 2); // ЧислоПроц(10,2)
    var extraCost = round(num(inputs.extraCost, DEFAULTS.extraCost), 4);         // ЧислоЦена(18,4)
    var volumeKg = round(num(inputs.volumeKg, DEFAULTS.volumeKg), 4);
    var select = inputs.mode === 'select';
    var recipe = isFilled(id) && has(model.byId, String(id)) ? model.byId[String(id)] : null;
    var res = {
      ok: false, recipe: recipe,
      baseCost: recipe ? recipe.cost : null, baseSale: recipe ? recipe.sale : null,
      targetMargin: targetMargin, extraCost: extraCost, volumeKg: volumeKg,
      scenarioCost: null, recommendedPrice: null, revenue: null, batchCost: null, grossProfit: null,
      markup: null, deltaToCurrent: null, summary: ''
    };
    function fail(text) {
      res.recommendedPrice = 0;
      res.summary = text;
      return res;
    }
    if (!isFilled(id)) {
      res.summary = select ? INITIAL_TEXTS.scenario : 'Виберіть рецептуру у дереві, пошуку або контролі.';
      return res;
    }
    if (select) {
      if (!recipe) {
        res.summary = 'Немає інформації про вибрану специфікацію.';
        return res;
      }
      if (!recipe.fullCost) return fail('Рекомендацію заблоковано: не всі матеріали мають ціну.');
    }
    if (targetMargin < 0 || targetMargin >= 100) return fail('Цільова маржа повинна бути від 0 до 99,99%.');
    if (extraCost < 0 || volumeKg <= 0) return fail('Додаткові витрати ≥ 0, обсяг повинен бути > 0 кг.');
    if (!recipe) return fail('Специфікацію не знайдено у поточній вітрині.');
    if (!recipe.fullCost) return fail('Немає повної перевіреної собівартості. Сценарій недоступний.');

    var scenarioCost = clean(recipe.cost + extraCost);
    var recommended = round(scenarioCost / (1 - targetMargin / 100), 4);
    var revenue = round(recommended * volumeKg, 2);
    var batchCost = round(scenarioCost * volumeKg, 2);
    var gross = round(revenue - batchCost, 2);
    res.ok = true;
    res.scenarioCost = scenarioCost;
    res.recommendedPrice = recommended;
    res.revenue = revenue;
    res.batchCost = batchCost;
    res.grossProfit = gross;
    res.markup = scenarioCost > 0 ? round((recommended - scenarioCost) / scenarioCost * 100, 2) : null;
    res.deltaToCurrent = recipe.sale > 0 ? round(recommended - recipe.sale, 4) : null;
    res.summary = 'Собівартість зі змінами: ' + fmtNum(round(scenarioCost, 2))
      + ' грн/кг; виручка: ' + fmtNum(revenue)
      + ' грн; витрати: ' + fmtNum(batchCost)
      + ' грн; валовий прибуток: ' + fmtNum(gross) + ' грн.';
    return res;
  }

  // ---------------------------------------------------------------------------
  // UX42: materials in use, impact, compare, quality
  // ---------------------------------------------------------------------------

  function materialsInUse(model) {
    var index = {}, list = [];
    model.cache.forEach(function (c) {
      var m = index[c.material];
      if (!m) {
        m = index[c.material] = {
          id: c.material, name: nameOf(model.materials, c.material), recipes: 0, chars: [],
          priceAvailable: false, price: 0, _specs: {}, _chars: {}
        };
        list.push(m);
      }
      if (!m._specs[c.spec]) {
        m._specs[c.spec] = true;
        m.recipes += 1;
      }
      var ck = c.char || '';
      if (!m._chars[ck]) {
        m._chars[ck] = true;
        m.chars.push(c.char);
      }
      if (c.priceAvailable && !m.priceAvailable) {
        m.priceAvailable = true;
        m.price = c.price;
      }
    });
    list.forEach(function (m) {
      delete m._specs;
      delete m._chars;
    });
    return list.sort(function (a, b) { return cmpText(a.name, b.name); });
  }

  function recipeTitle(model, specId) {
    if (has(model.byId, specId)) return model.byId[specId].name;
    if (has(model.specs, specId) && isFilled(model.specs[specId].name)) return String(model.specs[specId].name);
    return specId;
  }

  // UX42_РассчитатьВлияниеНаСервере
  function materialImpact(model, materialId, percent) {
    var pct = round(num(percent, DEFAULTS.impactPercent), 4);
    var res = {
      ok: false, material: idOf(materialId), materialName: isFilled(materialId) ? nameOf(model.materials, materialId) : '',
      percent: pct, rows: [], summary: ''
    };
    if (!isFilled(materialId)) {
      res.summary = 'Виберіть матеріал з довідника або з нижньої калькуляції.';
      return res;
    }
    if (pct < -100) {
      res.summary = 'Зниження ціни не може перевищувати 100%.';
      return res;
    }
    var mat = String(materialId), bySpec = {};
    var batchKg = model.methodology.batchKg;
    model.cache.forEach(function (c) {
      if (c.material !== mat) return;
      var out = bySpec[c.spec];
      if (!out) {
        out = bySpec[c.spec] = {
          spec: c.spec, name: recipeTitle(model, c.spec), qty: 0, price: 0, deltaKg: 0, status: 'ЦІНА Є'
        };
        res.rows.push(out);
      }
      out.qty = round(out.qty + c.qty, 4);
      if (!c.priceAvailable) {
        out.status = 'НЕМАЄ ЦІНИ — ВПЛИВ НЕВІДОМИЙ';
      } else {
        out.price = c.price;
        out.deltaKg = round(out.deltaKg + round(c.qty * c.price * pct / 100 / batchKg, 4), 4);
      }
    });
    res.rows.forEach(function (r) {
      if (r.status !== 'ЦІНА Є') r.deltaKg = 0;   // a partial result is not shown as final
    });
    res.ok = true;
    res.summary = 'Залежних рецептур: ' + fmtNum(res.rows.length)
      + '. Зміна ціни: ' + fmtNum(pct) + '% (для обраного матеріалу).'
      + ' Δ у грн/кг на основі 1000 кг виходу; без зміни BAS.'
      + ' Одиниці та еквівалентність характеристик перевіряйте окремо.';
    return res;
  }

  // UX42_СравнитьНаСервере
  function compareRecipes(model, idA, idB) {
    var a = isFilled(idA) ? String(idA) : null, b = isFilled(idB) ? String(idB) : null;
    var res = {
      ok: false, a: a && has(model.byId, a) ? model.byId[a] : null, b: b && has(model.byId, b) ? model.byId[b] : null,
      rows: [], delta: null, problems: 0, summary: ''
    };
    if (!a || !b) {
      res.summary = 'Оберіть дві специфікації. Обрану в основному списку можна перенести кнопкою «Обрану → Б».';
      return res;
    }
    if (a === b) {
      res.summary = 'Для порівняння потрібно вибрати РІЗНІ рецептури.';
      return res;
    }
    var index = {};
    model.cache.forEach(function (c) {
      if (c.spec !== a && c.spec !== b) return;
      var key = materialKey(c.material, c.char);
      var out = index[key];
      if (!out) {
        out = index[key] = {
          material: c.material, materialName: nameOf(model.materials, c.material),
          char: c.char, charName: c.char ? nameOf(model.chars, c.char) : '',
          qtyA: 0, qtyB: 0, price: 0, diffKg: 0, status: 'OK'
        };
        res.rows.push(out);
      }
      if (c.spec === a) out.qtyA = round(out.qtyA + c.qty, 4);
      else out.qtyB = round(out.qtyB + c.qty, 4);
      if (!c.priceAvailable) out.status = 'НЕМАЄ ЦІНИ';
      else out.price = c.price;
    });
    if (res.rows.length === 0) {
      res.summary = 'Для вибраних специфікацій немає складових у поточному завантаженні.';
      return res;
    }
    var delta = 0, problems = 0, batchKg = model.methodology.batchKg;
    res.rows.forEach(function (r) {
      if (r.status === 'OK') {
        r.diffKg = round((r.qtyB - r.qtyA) * r.price / batchKg, 4);
        delta += r.diffKg;
      } else {
        r.diffKg = 0;
        problems += 1;
      }
    });
    res.problems = problems;
    if (problems > 0) {
      res.summary = 'Неповне порівняння: ' + fmtNum(problems)
        + ' матеріалів без ціни. Загальну різницю не розраховано.';
    } else {
      res.ok = true;
      res.delta = round(delta, 2);
      res.summary = 'Різниця Б − A: ' + fmtNum(res.delta)
        + ' грн/кг (негативна = Б дешевша). Переробка 50 грн/кг є в обох рецептах'
        + ' й взаємно скорочується. Ціни без ПДВ; не змінює записи BAS.';
    }
    return res;
  }

  // UX42_ПересчитатьКачествоНаСервере
  function dataQuality(model, opts) {
    opts = opts || {};
    var days = round(num(opts.staleDays, DEFAULTS.staleDays), 0);   // ТипЦелое
    if (days <= 0) days = DEFAULTS.staleDays;
    var nowMs = opts.now != null && opts.now !== '' ? naiveMs(opts.now) : null;
    if (nowMs === null) nowMs = naiveMs(model.generatedAt || new Date());
    var limitMs = nowMs - days * 86400000;
    var rows = [], index = {}, recommendations = [];
    model.recipes.forEach(function (r) {
      var q = { spec: r.id, name: r.name, missing: 0, stale: 0, status: '', advice: '', ok: false };
      rows.push(q);
      index[r.id] = q;
    });
    model.cache.forEach(function (c) {
      var q = index[c.spec];
      if (!q) return;
      if (!c.priceAvailable) {
        q.missing += 1;
      } else {
        var ms = naiveMs(c.priceDate);     // an empty date is older than any limit
        if (ms === null || ms < limitMs) q.stale += 1;
      }
    });
    function advise(priority, r, signal, action) {
      recommendations.push({ priority: priority, spec: r.id, name: r.name, signal: signal, action: action });
    }
    var problems = 0;
    rows.forEach(function (q) {
      var r = model.byId[q.spec];
      if (r.materials === 0) {
        q.status = 'НЕМАЄ СКЛАДУ';
        q.advice = 'Перевірити склад специфікації в BAS: не знайдено жодного матеріалу.';
        advise(1, r, q.status, q.advice);
      } else if (q.missing > 0) {
        q.status = 'НЕПОВНІ ЗАКУПІВЕЛЬНІ ЦІНИ';
        q.advice = 'Перевірити останні надходження: ' + fmtNum(q.missing) + ' матеріалів без ціни/гривні.';
        advise(1, r, q.status, q.advice);
      } else if (q.stale > 0) {
        q.status = 'ЗАСТАРІЛІ ЦІНИ';
        q.advice = 'Оновити/перевірити закупівельні ціни ' + fmtNum(q.stale) + ' матеріалів.';
        advise(2, r, q.status, q.advice);
      } else if (r.problem === 'НЕМАЄ ЦІНИ ПРОДАЖУ' || r.problem === 'НЕ ВИЗНАЧЕНО ВАГУ'
        || r.problem === 'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ') {
        q.status = 'НЕПЕРЕВІРЕНИЙ ПРОДАЖ';
        q.advice = 'Перевірити розхідну, ПДВ та вагу нетто упаковки.';
        advise(2, r, r.problem, q.advice);
      } else {
        q.status = 'ТЕХНІЧНО ПОВНІ ДАНІ';
        q.advice = 'Перевірені на повноту/свіжість; це НЕ підтвердження фактичної собівартості.';
        q.ok = true;
      }
      if (!q.ok) problems += 1;
      // Loss / low margin only with complete and fresh purchase prices.
      if (r.materials > 0 && q.missing === 0 && q.stale === 0) {
        if (r.problem === 'ЗБИТКОВА ПОЗИЦІЯ') {
          advise(1, r, 'ЗБИТКОВІСТЬ (РОЗРАХУНКОВА)',
            'Перевірити ціну, знижки та собівартість; змоделювати нову продажну ціну.');
        } else if (r.problem === 'НИЗЬКА МАРЖА') {
          advise(3, r, 'НИЗЬКА МАРЖА', 'Відкрити ціновий сценарій і розрахувати рекомендовану ціну.');
        }
      }
    });
    recommendations.sort(function (x, y) { return x.priority - y.priority || cmpText(x.name, y.name); });
    return {
      staleDays: days,
      limitDate: fromNaiveMs(limitMs),
      rows: rows,
      recommendations: recommendations,
      problems: problems,
      summary: 'Перевірено рецептур: ' + fmtNum(rows.length)
        + '; є питання до даних: ' + fmtNum(problems)
        + '; актуальність закупівель: ' + fmtNum(days) + ' днів.',
      adviceSummary: 'Рекомендацій: ' + fmtNum(recommendations.length)
        + '. Спочатку виправляйте дані, потім переглядайте рентабельність.'
    };
  }

  // ---------------------------------------------------------------------------
  // NX50: production plan, stock, constructor, price list, energy, assistant
  // ---------------------------------------------------------------------------

  // NX50_ПересчитатьПланНаСервере
  function productionPlan(model, planRows, stock) {
    var meth = model.methodology;
    var needs = [], needIndex = {}, totalKg = 0, linesUsed = 0, missingSpecs = [];
    var bySpec = {};
    model.cache.forEach(function (c) { (bySpec[c.spec] || (bySpec[c.spec] = [])).push(c); });
    arr(planRows).forEach(function (p) {
      if (!isObj(p)) return;
      var kg = round(num(p.kg), 4);
      if (kg <= 0 || !isFilled(p.spec)) return;
      var spec = String(p.spec);
      totalKg = round(totalKg + kg, 4);
      var lines = bySpec[spec] || [];
      if (!lines.length && missingSpecs.indexOf(spec) < 0) missingSpecs.push(spec);
      lines.forEach(function (c) {
        var key = materialKey(c.material, c.char);
        var n = needIndex[key];
        if (!n) {
          n = needIndex[key] = {
            material: c.material, materialName: nameOf(model.materials, c.material),
            char: c.char, charName: c.char ? nameOf(model.chars, c.char) : '',
            need: 0, price: c.priceAvailable ? c.price : 0, sum: 0, stock: null, deficit: 0,
            status: c.priceAvailable ? 'OK' : 'НЕМАЄ ЦІНИ'
          };
          needs.push(n);
        }
        n.need = round(n.need + c.qty * kg / 1000, 4);
        if (!c.priceAvailable) n.status = 'НЕМАЄ ЦІНИ';
        linesUsed += 1;
      });
    });
    var stockIndex = {};
    arr(stock).forEach(function (s) {
      if (!isObj(s) || !isFilled(s.material)) return;
      var key = materialKey(s.material, s.char);
      if (!has(stockIndex, key)) stockIndex[key] = round(num(s.qty), 4);   // NX50_НайтиСтроку: first match
    });
    var known = 0, unknown = 0, deficitCount = 0, noStock = 0;
    needs.forEach(function (n) {
      var key = materialKey(n.material, n.char);
      if (has(stockIndex, key)) {
        n.stock = stockIndex[key];
        n.deficit = n.need > n.stock ? round(n.need - n.stock, 4) : 0;
        if (n.deficit > 0) deficitCount += 1;
      } else {
        noStock += 1;   // 0 here does NOT mean zero in stock — there is simply no data
        n.status += '; ЗАЛИШОК НЕ ЗАДАНО';
      }
      if (n.status.indexOf('НЕМАЄ ЦІНИ') >= 0) {
        unknown += 1;
      } else {
        n.sum = round(n.need * n.price, 2);
        known += n.sum;
      }
    });
    known = round(known, 2);
    var processing = round(totalKg * meth.processingPerTon / 1000, 2);
    var total = unknown > 0 ? null : round(known + processing, 2);
    return {
      needs: needs, totalKg: totalKg, processing: processing, knownCost: known, total: total,
      unknown: unknown, deficitCount: deficitCount, noStockCount: noStock, linesUsed: linesUsed,
      missingSpecs: missingSpecs,
      summary: 'План: ' + fmtNum(round(totalKg, 2)) + ' кг; матеріалів: ' + fmtNum(needs.length)
        + '; без ціни: ' + fmtNum(unknown)
        + '; вартість відомих матеріалів: ' + fmtNum(known) + ' грн; переробка: '
        + fmtNum(processing) + ' грн.'
        + (unknown > 0 ? ' Загальна вартість НЕ визначена (неповні ціни).'
          : ' Разом: ' + fmtNum(total) + ' грн.'),
      stockSummary: 'Сценарний дефіцит матеріалів: ' + fmtNum(deficitCount)
        + '; залишок не задано для: ' + fmtNum(noStock)
        + '. НЕ є фактичним звітом про залишки BAS.'
    };
  }

  // NX50_ДобавитьВПланНаСервере (validation part)
  function canAddToPlan(model, id, kg) {
    var k = kg === undefined ? DEFAULTS.planKg : num(kg, 0);
    if (!isFilled(id) || k <= 0) return { ok: false, message: 'Виберіть специфікацію та вкажіть партію понад 0 кг.' };
    var spec = String(id);
    var known = model.cache.some(function (c) { return c.spec === spec; });
    if (!known) {
      return { ok: false, message: 'Немає складу обраної специфікації у завантажених даних. Натисніть «Оновити».' };
    }
    return { ok: true, message: '' };
  }

  // NX50_ЗадатьОстатокНаСервере (validation part)
  function checkStock(material, qty) {
    if (!isFilled(material)) return { ok: false, message: 'Спочатку виділіть матеріал у таблиці потреби.' };
    if (num(qty, 0) < 0) return { ok: false, message: "Залишок не може бути від'ємним." };
    return { ok: true, message: '' };
  }

  // NX50_ПолучитьЦенуИзКеша
  function cachePrice(model, material, ch) {
    for (var i = 0; i < model.cache.length; i++) {
      var c = model.cache[i];
      if (c.material === str(material) && sameChar(c.char, ch) && c.priceAvailable && c.price > 0) return c.price;
    }
    return 0;
  }

  // NX50_ЗагрузитьКонструкторНаСервере
  function constructorLoad(model, id) {
    if (!isFilled(id)) {
      return {
        ok: false, rows: [], total: 0, unknown: 0, invalid: 0, newCost: null, baseCost: null, diff: null,
        summary: 'Виберіть базову специфікацію.'
      };
    }
    var spec = String(id);
    var rows = model.cache.filter(function (c) { return c.spec === spec; })
      .map(function (c) { return { material: c.material, char: c.char, qty: c.qty }; });
    return constructorCalc(model, spec, rows);
  }

  // NX50_ПересчитатьКонструкторНаСервере
  function constructorCalc(model, id, rows) {
    var meth = model.methodology;
    var base = isFilled(id) && has(model.byId, String(id)) ? model.byId[String(id)] : null;
    var total = 0, unknown = 0, invalid = 0;
    var out = arr(rows).filter(isObj).map(function (r) {
      var ch = idOf(r.char);
      var qty = round(num(r.qty), 4);
      var price = cachePrice(model, r.material, ch);
      var row = {
        material: idOf(r.material), materialName: nameOf(model.materials, r.material),
        char: ch, charName: ch ? nameOf(model.chars, ch) : '',
        qty: qty, price: price, sum: 0, status: ''
      };
      if (qty <= 0) {
        row.status = 'КІЛЬКІСТЬ <= 0';
        invalid += 1;
      } else if (price <= 0) {
        row.status = 'НЕМАЄ ЦІНИ В КЕШІ';
        unknown += 1;
      } else {
        row.sum = round(qty * price, 2);
        total += row.sum;
        row.status = 'OK';
      }
      return row;
    });
    total = round(total, 2);
    var res = {
      ok: false, rows: out, total: total, unknown: unknown, invalid: invalid,
      newCost: null, baseCost: base ? base.cost : null, diff: null, summary: ''
    };
    if (out.length === 0) {
      res.summary = 'Немає матеріалів для розрахунку.';
    } else if (unknown > 0 || invalid > 0) {
      res.summary = 'НЕПОВНО: без цін ' + fmtNum(unknown) + '; помилок кількості ' + fmtNum(invalid)
        + '. Рекомендації заблоковані.';
    } else {
      res.ok = true;
      res.newCost = round((total + meth.processingPerBatch) / meth.batchKg, 4);
      if (!base) {
        res.summary = 'Сценарна собівартість: ' + fmtNum(res.newCost) + ' грн/кг.';
      } else if (!base.fullCost) {
        res.summary = 'Сценарна собівартість: ' + fmtNum(res.newCost)
          + ' грн/кг; базовий рецепт неповний, порівняння недоступне.';
      } else {
        res.diff = round(res.newCost - base.cost, 2);
        res.summary = 'Сценарна с/в ' + fmtNum(res.newCost) + ' грн/кг; базова '
          + fmtNum(base.cost) + '; різниця ' + fmtNum(res.diff) + ' грн/кг. Переробка 50 грн/кг.';
      }
    }
    return res;
  }

  // NX50_ДобавитьМатериалНаСервере (validation part)
  function canAddConstructorRow(material, qty) {
    if (!isFilled(material) || num(qty, 0) <= 0) return { ok: false, message: 'Виберіть матеріал і додатну кількість.' };
    return { ok: true, message: '' };
  }

  // КоличествоШагов = Цел(x / Шаг); +1 if КоличествоШагов × Шаг < x; result Окр(…, 4).
  // 1C computes in decimal: float noise is neutralised by comparing at 9 decimals.
  function ceilToStep(value, step) {
    var x = num(value), s = num(step);
    if (!(s > 0)) return round(x, 4);
    var steps = Math.floor(round(x / s, 9));
    if (round(steps * s, 9) < round(x, 9)) steps += 1;
    return round(steps * s, 4);
  }

  // NX50_СформироватьПрайсНаСервере
  function priceList(model, opts) {
    opts = opts || {};
    var margin = round(num(opts.margin, DEFAULTS.priceMargin), 4);
    var step = round(num(opts.step, DEFAULTS.priceStep), 4);
    var res = { ok: false, margin: margin, step: step, rows: [], skipped: 0, summary: '' };
    if (margin < 0 || margin >= 100 || step <= 0) {
      res.summary = 'Маржа: 0...99,99%; крок округлення > 0 грн.';
      return res;
    }
    model.recipes.forEach(function (r) {
      if (!r.active) return;
      if (!r.fullCost) {
        res.skipped += 1;
        return;
      }
      var recommended = ceilToStep(r.cost / (1 - margin / 100), step);
      res.rows.push({
        spec: r.id, name: r.name, channel: r.categoryPath, cost: r.cost, current: r.sale,
        recommended: recommended, diff: round(recommended - r.sale, 4),
        status: r.sale > 0 ? 'ПРОЕКТ / НЕ ЗАПИСАНО' : 'НЕМАЄ ПРОДАЖУ'
      });
    });
    res.ok = true;
    res.summary = 'Проектні ціни: ' + fmtNum(res.rows.length)
      + '; без повної собівартості пропущено: ' + fmtNum(res.skipped)
      + '; цільова маржа ' + fmtNum(margin) + '% (без ПДВ). Не враховані індивідуальні знижки клієнтів.';
    return res;
  }

  function tsvCell(v) { return str(v).replace(/[\t\r\n]+/g, ' '); }
  function priceListTsv(result) {
    var lines = [['Продукція', 'Група / канал', 'С/в грн/кг', 'Поточна', 'Рекомендована', 'Зміна', 'Перевірка'].join('\t')];
    arr(result && result.rows).forEach(function (r) {
      lines.push([tsvCell(r.name), tsvCell(r.channel), tsvNum(r.cost), tsvNum(r.current),
        tsvNum(r.recommended), tsvNum(r.diff), tsvCell(r.status)].join('\t'));
    });
    return lines.join('\n');
  }

  // NX50_РассчитатьЭнергиюНаСервере
  function energy(opts) {
    opts = opts || {};
    var perTon = round(num(opts.kwhPerTon, DEFAULTS.kwhPerTon), 4);
    var a = round(num(opts.tariffA, DEFAULTS.tariffA), 4);
    var b = round(num(opts.tariffB, DEFAULTS.tariffB), 4);
    var kg = round(num(opts.volumeKg, DEFAULTS.energyVolumeKg), 4);
    var res = {
      ok: false, kwhPerTon: perTon, tariffA: a, tariffB: b, volumeKg: kg,
      kwh: null, costA: null, costB: null, diff: null, perKg: null, summary: ''
    };
    if (perTon < 0 || a < 0 || b < 0 || kg <= 0) {
      res.summary = "Потрібні невід'ємні тарифи та споживання, а обсяг > 0.";
      return res;
    }
    res.ok = true;
    res.kwh = round(perTon * kg / 1000, 3);
    res.costA = round(res.kwh * a, 2);
    res.costB = round(res.kwh * b, 2);
    res.diff = round(res.costB - res.costA, 2);
    res.perKg = round((b - a) * perTon / 1000, 4);
    res.summary = 'Партія ' + fmtNum(kg) + ' кг; ' + fmtNum(res.kwh)
      + ' кВт·год. Тариф А: ' + fmtNum(res.costA) + ' грн; тариф Б: '
      + fmtNum(res.costB) + ' грн; різниця Б−А: '
      + fmtNum(res.diff) + ' грн ('
      + fmtNum(res.perKg) + ' грн/кг). Це НЕ заміна фактичної калькуляції.';
    return res;
  }

  // NX50_ОтветитьНаСервере (+2 extra rules derived from the same data: маржа, збитк)
  function assistant(model, question, ctx) {
    ctx = ctx || {};
    var q = lower(trim(question));
    function reply(command, answer) { return { command: command, answer: answer }; }
    function contains(s) { return q.indexOf(s) >= 0; }
    if (q === '') return reply('empty', 'Напишіть: рецепти, проблеми, немає цін, найдорожчий, план, енергія, допомога.');
    if (contains('допом') || contains('що вміє')) {
      return reply('help', 'Команди: рецепти; проблеми; немає цін; найдорожчий; план; енергія. Локальні правила, без API та генеративного AI.');
    }
    if (contains('рецепт')) return reply('recipes', 'У завантаженому каталозі рецептів: ' + fmtNum(model.recipes.length) + '.');
    if (contains('проблем')) {
      var count = ctx.problemsCount != null ? num(ctx.problemsCount) : control(model).problems.length;
      return reply('problems', 'Позицій у центрі контролю: ' + fmtNum(count) + '. Перейдіть у розділ «Контроль».');
    }
    if (contains('немає цін') || contains('без цін')) {
      var n = model.recipes.filter(function (r) { return r.materials > r.pricesFound; }).length;
      return reply('noPrices', 'Рецептур із відсутніми цінами матеріалів: ' + fmtNum(n) + '.');
    }
    if (contains('найдорож')) {
      var leader = null;
      model.recipes.forEach(function (r) {
        if (r.fullCost && (leader === null || r.cost > leader.cost)) leader = r;
      });
      if (!leader) return reply('mostExpensive', 'Немає повністю розрахованих рецептів.');
      return reply('mostExpensive', 'Найбільша калькуляційна собівартість: ' + leader.name
        + ' — ' + fmtNum(leader.cost) + ' грн/кг.');
    }
    if (contains('план')) {
      return reply('plan', ctx.planSummary ? str(ctx.planSummary) : productionPlan(model, [], []).summary);
    }
    if (contains('енерг')) {
      return reply('energy', ctx.energySummary ? str(ctx.energySummary) : energy({}).summary);
    }
    if (contains('маржа') || contains('маржі')) {
      return reply('margin', 'Середня маржа активних рецептур: ' + control(model).kpi.avgMarginText + '.');
    }
    if (contains('збитк')) {
      var losses = control(model).problems.filter(function (r) { return r.problem === 'ЗБИТКОВА ПОЗИЦІЯ'; }).length;
      return reply('loss', 'Збиткових позицій серед активних рецептур: ' + fmtNum(losses) + '.');
    }
    return reply('unknown', 'Не розпізнав запит. Це локальний командний помічник без нейромережі. Напишіть «допомога».');
  }

  // «Історія змін»: recipes with Було/Стало.
  function historyChanges(model, opts) {
    opts = opts || {};
    var withPrev = model.recipes.filter(function (r) { return !!r.prev; });
    var changed = withPrev.filter(function (r) { return r.prev.changed; });
    return {
      rows: opts.onlyChanged ? changed : withPrev,
      total: model.comparedCount,
      changed: changed.length
    };
  }

  // ---------------------------------------------------------------------------
  // Data helpers: validation and local writes (demo / file mode)
  // ---------------------------------------------------------------------------

  function validateData(data) {
    var errors = [], warnings = [];
    function warnCount(n, text) { if (n > 0) warnings.push(text + fmtNum(n) + '.'); }
    if (!isObj(data)) {
      errors.push("Дані не є об'єктом JSON.");
      return { ok: false, errors: errors, warnings: warnings };
    }
    if (data.format !== 'fortuna-data') errors.push('Невідомий формат даних: очікується «fortuna-data».');
    if (data.version == null) errors.push('Не вказано версію формату (version).');
    else if (data.version !== 1) errors.push('Версія формату ' + str(data.version) + ' не підтримується (очікується 1).');
    if (!Array.isArray(data.specs)) errors.push('Відсутній або некоректний список специфікацій (specs).');
    if (!Array.isArray(data.rows)) errors.push('Відсутній або некоректний список рядків складу (rows).');
    ['products', 'materials', 'characteristics'].forEach(function (k) {
      if (data[k] != null && !isObj(data[k])) errors.push('Поле ' + k + ' має бути об\'єктом.');
    });
    if (errors.length) return { ok: false, errors: errors, warnings: warnings };

    if (data.generatedAt != null && data.generatedAt !== '' && !parseDate(data.generatedAt)) {
      warnings.push('Не вдалося розпізнати дату формування даних (generatedAt).');
    }
    var specIds = {}, dupSpecs = 0, badSpecs = 0, noProduct = 0;
    data.specs.forEach(function (s) {
      if (!isObj(s) || !isFilled(s.id)) {
        badSpecs += 1;
        return;
      }
      var id = String(s.id);
      if (specIds[id]) dupSpecs += 1;
      specIds[id] = true;
      if (!isFilled(s.product)) noProduct += 1;
    });
    warnCount(badSpecs, 'Специфікацій без id: ');
    warnCount(dupSpecs, 'Специфікацій із повторним id: ');
    warnCount(noProduct, 'Специфікацій без товару: ');

    var materials = obj(data.materials), products = obj(data.products);
    var unknownSpec = 0, noMaterial = 0, badQty = 0, noName = {}, usable = 0;
    data.rows.forEach(function (row) {
      if (!isObj(row) || !isFilled(row.spec) || !isFilled(row.material)) {
        noMaterial += 1;
        return;
      }
      if (num(row.qty, 0) === 0) {
        badQty += 1;
        return;
      }
      usable += 1;
      if (!specIds[String(row.spec)]) unknownSpec += 1;
      if (!isFilled(materials[String(row.material)])) noName[String(row.material)] = true;
    });
    if (data.rows.length === 0) warnings.push('Немає жодного рядка складу — каталог рецептур буде порожнім.');
    warnCount(noMaterial, 'Рядків складу без специфікації або матеріалу (пропущено): ');
    warnCount(badQty, 'Рядків складу з нульовою або некоректною кількістю (пропущено): ');
    warnCount(unknownSpec, 'Рядків складу з невідомою специфікацією: ');
    warnCount(Object.keys(noName).length, 'Матеріалів без назви: ');
    var noProductName = 0;
    data.specs.forEach(function (s) {
      if (isObj(s) && isFilled(s.product) && !isFilled(products[String(s.product)])) noProductName += 1;
    });
    warnCount(noProductName, 'Специфікацій, товар яких без назви: ');

    var badPrices = 0;
    Object.keys(obj(data.purchasePrices)).forEach(function (k) {
      var p = data.purchasePrices[k];
      if (k.indexOf('|') < 0 || !isObj(p) || typeof p.exVat !== 'number' || !isFinite(p.exVat)) badPrices += 1;
    });
    if (data.purchasePrices != null && !isObj(data.purchasePrices)) warnings.push('Поле purchasePrices має бути об\'єктом.');
    warnCount(badPrices, 'Некоректних закупівельних цін: ');

    var badSales = 0;
    Object.keys(obj(data.sales)).forEach(function (k) {
      var s = data.sales[k];
      if (!isObj(s) || (s.status === 'OK' || s.status == null) && (typeof s.exVat !== 'number' || !isFinite(s.exVat))) badSales += 1;
    });
    if (data.sales != null && !isObj(data.sales)) warnings.push('Поле sales має бути об\'єктом.');
    warnCount(badSales, 'Некоректних записів продажу: ');

    var badHistory = 0;
    Object.keys(obj(data.history)).forEach(function (k) {
      var h = data.history[k];
      if (!Array.isArray(h)) {
        badHistory += 1;
        return;
      }
      h.forEach(function (e) {
        if (!isObj(e) || typeof e.cost !== 'number' || typeof e.materials !== 'number') badHistory += 1;
      });
    });
    warnCount(badHistory, 'Некоректних записів історії калькуляцій: ');
    if (usable === 0 && data.rows.length > 0) warnings.push('Жоден рядок складу не придатний для розрахунку.');
    return { ok: true, errors: errors, warnings: warnings };
  }

  function findSpec(data, id) {
    if (!isObj(data) || !isFilled(id)) return null;
    var list = arr(data.specs);
    for (var i = 0; i < list.length; i++) {
      if (isObj(list[i]) && String(list[i].id) === String(id)) return list[i];
    }
    return null;
  }

  // НазначитьКатегориюНаСервере — for demo / file mode (in live mode the HTTP service does it).
  function applyCategory(data, id, code) {
    var c = str(code);
    if (!has(CATEGORY_BY_CODE, c)) return { ok: false, message: 'ПОМИЛКА: невідома категорія ' + c };
    var features = obj(data && data.features);
    if (features.categoryAttribute === false) {
      return { ok: false, message: 'ПОМИЛКА: створіть реквізит КатегорияКалькуляции у довіднику Спецификации та оновіть конфігурацію (F7).' };
    }
    var spec = findSpec(data, id);
    if (!spec) return { ok: false, message: 'ПОМИЛКА ПЕРЕМІЩЕННЯ: специфікацію не знайдено.' };
    if (features.statusAttribute === false) {
      return { ok: false, message: 'ПОМИЛКА ПЕРЕМІЩЕННЯ: у довіднику Спецификации немає реквізиту СтатусРецептуры.' };
    }
    spec.category = c === 'NONE' ? '' : c;
    spec.status = 'Нова';   // a new category means the recipe is used
    return { ok: true, message: 'ГОТОВО: ' + str(spec.name) + ' → ' + CATEGORY_BY_CODE[c].label };
  }

  // ИзменитьСтатусРецептурыНаСервере — for demo / file mode.
  function applyStatus(data, id, status) {
    if (!isFilled(id)) return { ok: false, message: 'ПОМИЛКА: не вибрано специфікацію.' };
    var s = trim(status);
    if (!s) return { ok: false, message: 'ПОМИЛКА ЗМІНИ СТАТУСУ: не вказано статус.' };
    var spec = findSpec(data, id);
    if (!spec) return { ok: false, message: 'ПОМИЛКА ЗМІНИ СТАТУСУ: специфікацію не знайдено.' };
    if (obj(data.features).statusAttribute === false) {
      return { ok: false, message: 'ПОМИЛКА ЗМІНИ СТАТУСУ: у довіднику Спецификации немає реквізиту СтатусРецептуры.' };
    }
    spec.status = s;
    return { ok: true, message: 'ГОТОВО: ' + str(spec.name) + ' -> ' + s };
  }

  return {
    VERSION: VERSION,
    DEFAULTS: DEFAULTS,
    INITIAL_TEXTS: INITIAL_TEXTS,
    CATEGORIES: CATEGORIES,
    CATEGORY_BY_CODE: CATEGORY_BY_CODE,
    FOLDER_TREE: FOLDER_TREE,
    SEARCH_MODES: SEARCH_MODES,
    PROBLEM_TYPES: PROBLEM_TYPES,
    ASSISTANT_COMMANDS: ASSISTANT_COMMANDS,
    // numbers, dates
    round: round, fmtNum: fmtNum, fmtFixed: fmtFixed, fmt2: fmt2,
    parseDate: parseDate, fmtDate: fmtDate, fmtDateTime: fmtDateTime,
    // primitives
    isUah: isUah, sameChar: sameChar, priceKey: priceKey, findPrice: findPrice, extractBoxKg: extractBoxKg,
    categoryByCode: categoryByCode, problemType: problemType, problemPriority: problemPriority,
    problemGroup: problemGroup, snapshotsDiffer: snapshotsDiffer, historySnapshot: historySnapshot,
    // model and screens
    buildModel: buildModel, setMarginThreshold: setMarginThreshold, control: control, search: search,
    recipeDetails: recipeDetails, priceScenario: priceScenario,
    materialsInUse: materialsInUse, materialImpact: materialImpact, compareRecipes: compareRecipes,
    dataQuality: dataQuality,
    productionPlan: productionPlan, canAddToPlan: canAddToPlan, checkStock: checkStock,
    constructorLoad: constructorLoad, constructorCalc: constructorCalc, canAddConstructorRow: canAddConstructorRow,
    priceList: priceList, priceListTsv: priceListTsv, ceilToStep: ceilToStep, energy: energy, assistant: assistant,
    historyChanges: historyChanges,
    // data helpers
    validateData: validateData, applyCategory: applyCategory, applyStatus: applyStatus
  };
});
