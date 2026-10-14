# `src/core.js` — розрахунковий модуль ФОРТУНА (API reference)

Calculation engine of the web page: a faithful port of the arithmetic, rules and Ukrainian summary texts of the
BAS/1C form module `bas/original/fortuna-v5-form-module.bsl` (v5.0). No DOM, no imports, ES2019.

```js
// browser: <script src="core.js"> → window.FortunaCore
// node:    const core = require('./src/core.js')
const model = FortunaCore.buildModel(data, { marginThreshold: 20 });
```

`data` is the `fortuna-data` v1 document described in `docs/CONTRACT.md`.

Conventions used everywhere below:

* **ids** are the lowercase UUID strings from the contract. A *characteristic* (`char`) is `null` when empty;
  `null`, `''` and `undefined` are always treated as the same empty value.
* **Money / prices** are numbers in UAH without VAT. Per-kg values (`cost`, `sale`) are rounded to 4 decimals,
  percentages to 2, exactly where the BSL rounds (`Окр`). Typed form columns `Число(18,4)` are mirrored by rounding
  to 4 decimals on assignment.
* **Texts** (`summary`, `message`, …) are the BSL texts, word for word; numbers inside them are formatted like
  1C does: `Строка(Число)` → `fmtNum`, `Формат(x,"ЧДЦ=2")` → `fmt2`. Thousands separator is U+00A0 (no-break space),
  decimal separator is a comma. Literal numbers that are part of the BSL text (e.g. `"Переробка: 50 000 грн/т"`,
  `"ПЕРЕРОБКА (на 1 000 кг)"`) keep their ordinary spaces, as in the BSL.
* **`ok`** in results: `true` when the operation produced a real result; `false` when a validation message was
  returned instead (the message is still in `summary` / `message`).
* Functions never throw on bad user input; they return the BSL validation message.
* Only `applyCategory`, `applyStatus` (mutate `data`) and `setMarginThreshold` / `control` / `search`
  (update `problem`/`priority` of the model's recipes) mutate their arguments.

---

## Constants

| Name | Value |
|---|---|
| `VERSION` | `'1.0.0'` |
| `DEFAULTS` | `{ marginThreshold: 20, targetMargin: 25, extraCost: 0, volumeKg: 1000, impactPercent: 10, staleDays: 90, planKg: 1000, constructorQty: 1, priceMargin: 25, priceStep: 0.05, kwhPerTon: 250, tariffA: 4, tariffB: 8, energyVolumeKg: 1000, batchKg: 1000, processingPerTon: 50000, historyTag: 'v3.3 грн/кг; переробка 50000 грн/т' }` — the initial values of the form attributes (`*_СоздатьРеквизиты`) and the methodology defaults. |
| `INITIAL_TEXTS` | initial texts of the summary fields before any calculation, e.g. `{ scenario: 'Спочатку виберіть рецептуру.', impact: 'Після оновлення даних виберіть матеріал і натисніть «Розрахувати».', compare: 'Виберіть дві специфікації та натисніть «Порівняти».', quality: 'Натисніть «Оновити дані».', advice: 'Рекомендації формуються після завантаження калькуляцій.', plan: …, stock: …, constructor: …, priceList: …, energy: …, assistantQuestion: 'Скільки рецептів?', assistant: …, search: 'Спочатку натисніть «Оновити дані»', details: 'Оберіть рецептуру у верхній таблиці.' }` |
| `CATEGORIES` | ordered array of the 12 channel categories **plus** `NONE`, see below |
| `CATEGORY_BY_CODE` | `{ [code]: category }` |
| `SEARCH_MODES` | `[{ code:'ALL', bsl:'ВСЕ', label:'Всі' }, { code:'ACTIVE', bsl:'АКТИВНЫЕ', label:'Активні' }, { code:'NO_CATEGORY', bsl:'БЕЗ_КАТ', label:'Без категорії' }, { code:'PROBLEMS', bsl:'ПРОБЛЕМЫ', label:'Проблемні' }, { code:'LOW_MARGIN', bsl:'НИЗКАЯ_МАРЖА', label:'Низька маржа' }]` |
| `PROBLEM_TYPES` | `[{ group:'ЗБИТКОВА ПОЗИЦІЯ', priority:1 }, { group:'НЕМАЄ ЦІН', priority:2 }, { group:'НЕМАЄ СКЛАДУ', priority:2 }, { group:'НЕМАЄ ЦІНИ ПРОДАЖУ', priority:2 }, { group:'НЕ ВИЗНАЧЕНО ВАГУ', priority:3 }, { group:'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ', priority:3 }, { group:'НИЗЬКА МАРЖА', priority:4 }, { group:'OK', priority:9 }]` — note `НЕМАЄ ЦІНИ ПРОДАЖУ` is priority **2**, not 3: the BSL tests `СтрНайти(Описание, "НЕМАЄ ЦІН") > 0` first and that text contains «НЕМАЄ ЦІН». Ported as is. |
| `ASSISTANT_COMMANDS` | chips for the assistant: `['рецепти','проблеми','немає цін','найдорожчий','план','енергія','маржа','збиткові','допомога']` |
| `FOLDER_TREE` | static definition of the folder tree (see `buildModel().tree`) |

### Category object

```js
{ code: 'UA_FEDYK', name: 'Федик', group: 'УКРАЇНА', subgroup: 'Привати',
  path: ['ВИКОРИСТОВУЮТЬСЯ', 'УКРАЇНА', 'Привати', 'Федик'],     // folder names from the root
  label: 'Україна / Привати / Федик' }                             // whitelist text of НазначитьКатегориюНаСервере
```

Order and labels: `UA_RUD` Рудь (Україна / Рудь), `UA_SILPO` Сільпо, `UA_METRO` Метро, `UA_FEDYK` Федик,
`UA_OP` ОП, `UA_MIDAS` Мидас (all three `subgroup:'Привати'`), `EX_DOVGAN` Довгань (Експорт / Довгань), `EX_ITALY` Італія,
`EX_ROMANIA` Румунія, `EX_GEYA` Гея Фуд, `EX_CZECH` Чехія, `EX_ISRAEL` Ізраїль, `NONE` Без категорії
(`group:null`, `path:['ВИКОРИСТОВУЮТЬСЯ','Без категорії']`, label `'Без категорії'`).

---

## Numbers, dates, formatting

| Function | Returns | Mirrors |
|---|---|---|
| `round(x, digits = 0)` | number, half away from zero on the **decimal** value (`round(1.005,2) === 1.01`, `round(-2.5) === -3`, `round(2.675,2) === 2.68`); float noise is neutralised (15 significant digits) first; never returns `-0`; non-finite → `0` | `Окр(x, n)` |
| `fmtNum(x)` | `'1 234,5'`, `'0'`, `'-12,25'` (no trailing zeros, U+00A0 groups) | `Строка(Число)` |
| `fmtFixed(x, digits)` | always `digits` decimals, grouped: `fmtFixed(1234.5, 2) === '1 234,50'` | `Формат(x, "ЧДЦ=n")` |
| `fmt2(x)` | `fmtFixed(x, 2)`, e.g. `'50 000,00'`. **Deviation:** 1C prints an empty string for zero; we print `'0,00'`. | `Формат(x, "ЧДЦ=2")` |
| `parseDate(v)` | `Date` (local time) from `'2026-10-14T09:30:00'`, `'2026-10-14'`, a `Date` or ms; `null` if empty/invalid | — |
| `fmtDate(v)` | `'14.10.2026'` (`''` for empty) | — |
| `fmtDateTime(v)` | `'14.10.2026 09:30'` (`''` for empty) | — |

## Primitives

| Function | Returns | Mirrors |
|---|---|---|
| `isUah(currency)` | `true` for empty / `uah` / `грн` / `грив` (case-insensitive, trimmed) | `ЭтоГривнаИлиПусто` |
| `sameChar(a, b)` | characteristic equality, `null`/`''`/`undefined` equal | — |
| `priceKey(material, char)` | `'<mat>|<char>'` or `'<mat>|'` | contract key |
| `findPrice(purchasePrices, material, char)` | the `purchasePrices` entry or `null`. Exact key first; if the characteristic is filled but has no own price → the material-only price (`'<mat>|'`) → otherwise the latest-dated price of any characteristic of that material. Identical to `НайтиПоследнююЦену` on raw data and a no-op on data already resolved by BAS. | `НайтиПоследнююЦену` |
| `extractBoxKg(unit)` | net box weight in kg parsed from the sale unit (`'ящ (4,5 кг)'` → 4.5, `'кг'` → 1, `'шт'` → 0). Used only when `sales[p].boxKg` is missing. | `ИзвлечьВесЯщикаКг` |
| `categoryByCode(code)` | category object or `null` | — |
| `problemType(row, threshold)` | problem string for a catalogue row (`{materials, pricesFound, sale, cost, margin, dataStatus}`): `'НЕМАЄ СКЛАДУ'`, `'НЕМАЄ ЦІН: 2'`, `'НЕ ВИЗНАЧЕНО ВАГУ'`, `'ПЕРЕВІРИТИ ЦІНУ ПРОДАЖУ'`, `'НЕМАЄ ЦІНИ ПРОДАЖУ'`, `'ЗБИТКОВА ПОЗИЦІЯ'`, `'НИЗЬКА МАРЖА'`, `'OK'` (checked in this order) | `UX40_ТипПроблемы` |
| `problemPriority(problem)` | 1 збиткова · 2 немає цін / немає складу / **немає ціни продажу** (BSL substring quirk) · 3 вага / перевірити ціну продажу · 4 низька маржа · 9 OK | `UX40_ПриоритетПроблемы` |
| `problemGroup(problem)` | problem without the counter: `'НЕМАЄ ЦІН: 2'` → `'НЕМАЄ ЦІН'` | — |
| `snapshotsDiffer(a, b)` | `true` if `b` is null or any of `round(sale,2)`, `round(cost,2)`, `round(markup,2)`, `hasSale`, `fullCost`, `hasMarkup`, `materials`, `pricesFound` differ | `СнимкиОтличаются` |
| `historySnapshot(entry)` | contract history entry → snapshot `{period, sale, cost, markup, materials, pricesFound, hasSale, fullCost, hasMarkup}` | `ЗагрузитьИсториюКалькуляций` |

---

## `buildModel(data, opts) → model`

Port of `ЗагрузитьВсеНаСервере` + `UX40_ПостроитьВитринуНаСервере` + `UX40_ОбойтиДерево` + `UX42_ОбновитьПослеЗагрузки`
(cache part). `opts = { marginThreshold = 20 }`. Never throws on a structurally poor document (missing maps are
treated as empty); run `validateData` first to show problems to the user.

```js
model = {
  data,                       // the input document (by reference)
  source, base, user,         // copied from data ('' if absent)
  generatedAt,                // Date or null
  methodology: { batchKg, processingPerTon, historyTag },   // data.methodology with defaults 1000 / 50000
  features,                   // data.features or {}
  messages,                   // data.messages or []
  marginThreshold,            // current threshold (number, 2 decimals)
  products, materials, chars, // id → name maps (data.products / materials / characteristics)
  tree,                       // [folderACTIVE, folderINACTIVE], see below
  recipes,                    // catalogue rows in tree depth-first order (UX40_ОбойтиДерево order)
  byId,                       // { [specId]: recipe }
  cache,                      // UX42_Кэш rows, see below
  counts: { recipes, active, inactive, rows },   // rows = data.rows.length (Состав.Количество())
  comparedCount,              // КоличествоСравнений (recipes that have Було/Стало)
  summary                     // 'ГОТОВО. Рецептур: 64 | ВИКОРИСТОВУЮТЬСЯ: 56 | НЕ ВИКОРИСТОВУЮТЬСЯ: 8 | рядків складу: 612 | порівняно: 30.'
                              // or 'Рецептури не знайдено.' when there are no rows
}
```

**Folder node** (`tree`): `{ key, name, path, code, children: [folder], recipes: [specId], count }` where
`path` is the folder path string (`'ВИКОРИСТОВУЮТЬСЯ / УКРАЇНА / Привати / Федик'`), `code` the category code of a
leaf channel folder (`'UA_FEDYK'`, `'NONE'` for Без категорії, `null` otherwise), `count` = recipes in the subtree.
Keys: `ACTIVE`, `UA`, `UA_RUD`, `UA_SILPO`, `UA_METRO`, `UA_PRIVATE`, `UA_FEDYK`, `UA_OP`, `UA_MIDAS`, `EX`,
`EX_DOVGAN`, `EX_ITALY`, `EX_ROMANIA`, `EX_GEYA`, `EX_CZECH`, `EX_ISRAEL`, `NONE`, `INACTIVE`.
Names and order are exactly those of the BSL tree:
ВИКОРИСТОВУЮТЬСЯ { УКРАЇНА { Рудь, Сільпо, Метро, Привати { Федик, ОП, Мидас } }, ЕКСПОРТ { Довгань, Італія, Румунія, Гея Фуд, Чехія, Ізраїль }, Без категорії }, НЕ ВИКОРИСТОВУЮТЬСЯ.

**Recipe** (catalogue row):

```js
{
  id, specName, productId, productName,
  name,              // productName + ' — ' + specName
  status,            // spec.status as received ('Нова', 'Стара', '')
  categoryRaw,       // trimmed spec.category as received (may be an unknown code such as 'OLD_X')
  categoryCode,      // '' or a valid code (kept also for inactive recipes: BSL never erases it)
  folderKey,         // tree folder key ('UA_RUD' … 'NONE', 'INACTIVE')
  folderPath,        // ['ВИКОРИСТОВУЮТЬСЯ','УКРАЇНА','Рудь']
  categoryPath,      // 'ВИКОРИСТОВУЮТЬСЯ / УКРАЇНА / Рудь'  (the catalogue column «Категорія» = channel key)
  active,            // categoryPath does not contain 'НЕ ВИКОРИСТОВУЮТЬСЯ'
  materials,         // number of composition rows (Материалов)
  pricesFound,       // rows with a found UAH purchase price (ЦенНайдено; exVat = 0 still counts)
  cost,              // грн/кг incl. processing, round 4: (Σ qty×exVat + processingPerTon) / batchKg
  sale,              // грн/кг, round 4 (sale.exVat / boxKg), 0 if not available
  markup,            // Рентабельность/Націнка %, round 2; 0 if not computed
  margin,            // Маржа %, (sale-cost)/sale×100 round 2, only if fullCost && sale > 0, else 0
  fullCost,          // materials > 0 && materials === pricesFound && cost > 0
  hasSale,           // sale > 0
  hasMarkup,         // fullCost && hasSale
  dataStatus,        // tree «Стан даних»: 'OK', 'НЕМАЄ ЦІН: 2', 'OK; НЕМАЄ ПРОДАЖУ',
                     //   'OK; ЦІНА В ІНШІЙ ВАЛЮТІ: EUR', 'НЕМАЄ ЦІН: 1; НЕ ВИЗНАЧЕНО ВАГУ ЯЩИКА: шт', …
  problem,           // UX40_ТипПроблемы with the current threshold
  problemGroup,      // problem without ': N'
  priority,          // UX40_ПриоритетПроблемы
  saleInfo,          // data.sales[productId] or null (box price, unit, boxKg, date, doc, status)
  prev,              // Було/Стало or null, see below
  serverCalc,        // data.serverCalc[id] or null
  parityOk           // null without serverCalc; else round(…,2) of cost, sale, markup all equal
}
```

**`prev`** (Було/Стало, BSL lines 2745–2819): `Було` = `history[id][0]`; if the current figures do not differ from
it (`snapshotsDiffer`) and `history[id][1]` exists, `Було` = `history[id][1]` (so everybody sees the last real change).

```js
{ period,            // Було.period (ISO string)
  fromPrevious,      // true when the fallback to history[id][1] was used
  changed,           // snapshotsDiffer(current, Було)
  sale,  saleDelta,  // Було.sale if Було.hasSale else null; delta = round(sale − Було.sale, 2) only if both have sale
  cost,  costDelta,  // same with fullCost
  markup, markupDelta } // same with hasMarkup; delta in percentage points (в.п.)
```

**Cache row** (`model.cache`, UX42_Кэш, one per composition row in `data.rows` order):
`{ spec, material, char /* null if empty */, qty, price /* exVat or 0 */, priceDate /* ISO string or null */, priceAvailable }`,
`priceAvailable = price found && isUah(currency) && exVat > 0`.

Rows are skipped exactly like the BSL query/loops: no `spec`, no `material`, or `qty` equal to 0 / not a number.
Rows whose spec is missing from `data.specs` are still costed (the spec is treated as active, without category,
named by its id) — `validateData` reports them.

## `setMarginThreshold(model, threshold)` → model

Mutator. Rounds the threshold to 2 decimals, recomputes `problem`, `problemGroup`, `priority` of every recipe.

## `control(model, { marginThreshold }) → result` — `UX40_ПересчитатьКонтрольНаСервере`

If `marginThreshold` is given, calls `setMarginThreshold` first.

```js
{
  problems,   // recipes with active && problem !== 'OK', stable-sorted by priority, then margin ascending
  top,        // first 12 of problems (UX40_ТопСигналов)
  groups,     // [{ group:'НЕМАЄ ЦІН', priority:2, count:5 }] for problems, sorted by priority then group
  channels,   // [{ channel /* categoryPath */, active, count, problems, avgMargin /* number|null */, marginCount }]
              //   in first-appearance order of the catalogue; problems counts active && problem!=='OK';
              //   avgMargin = round(Σmargin / n, 2) over fullCost && sale > 0 rows
  kpi: { total, active, problems, incomplete /* !fullCost */, avgMargin /* number|null */,
         avgMarginText /* '23,45 %' | 'немає даних' */, avgMarginNegative /* Σmargin < 0 */ },
  marginThreshold
}
```

## `search(model, { phrase = '', mode = 'ALL', marginThreshold }) → result` — `UX40_ПрименитьПоискНаСервере`

Uses each recipe's current `problem` (pass `marginThreshold` to recompute first, or call `control` / `setMarginThreshold`).
Phrase: lower-cased, trimmed, substring of `name + ' ' + categoryPath + ' ' + problem` (lower-cased).
`mode` accepts the English codes or the BSL codes (`'ВСЕ'`, `'АКТИВНЫЕ'`, …); an unknown mode filters nothing.
`ACTIVE` = active only; `NO_CATEGORY` = categoryPath contains «без категорії» (i.e. active without category);
`PROBLEMS` = problem ≠ OK (active **and** inactive, as in the BSL); `LOW_MARGIN` = problem `НИЗЬКА МАРЖА`.

```js
{ rows /* recipes */, count, total, mode /* English code */,
  label: 'Знайдено: 12 із 64',
  bslLabel: 'Знайдено: 12 із 64 | Фільтр: ВСЕ' }
```

## `recipeDetails(model, id, prevPrices?) → details | null` — `ЗагрузитьДеталиНаСервере`

`prevPrices` — optional `{ '<mat>|<char>': exVat }` from `GET /spec/{id}/prev`. Returns `null` if the id is
neither a spec of `data.specs` nor a catalogue recipe.

```js
{
  id, recipe /* catalogue row or null */, specName,
  rows: [{                         // composition rows in data.rows order, then the processing row
    material, materialName, char, charName, unit, qty,
    priceWithVat, priceExVat,      // null unless status 'OK'
    prevExVat, priceDelta,         // from prevPrices (only for 'OK' rows); delta = round(exVat − prev, 2); else null
    sum,                           // round(qty × exVat, 4) for 'OK' rows, else null
    priceDate, doc, currency,      // from the purchase price (also for 'ІНША ВАЛЮТА'), else null
    status,                        // 'OK' | 'НЕМАЄ ЦІНИ' | 'ІНША ВАЛЮТА: EUR'
    isProcessing: false
  }, {
    isProcessing: true, material: null, materialName: 'Переробка', char: null, charName: '',
    status: 'ПЕРЕРОБКА (на 1 000 кг)', unit: 'т', qty: 1, priceExVat: 50000, sum: 50000,
    priceWithVat: null, prevExVat: null, priceDelta: null, priceDate: null, doc: null, currency: null
  }],
  totals: { materials, pricesFound, tableRows /* materials + 1 */, materialsSum /* Σ sum */,
            processing /* 50000 */, total /* materialsSum + processing */, perKg /* round(total / batchKg, 4) */ },
  summary   // exact «Итоги»: 'Специфікація: Рецептура 2024 v2 | Матеріалів: 9 | Цін знайдено: 8 | Рядків у таблиці: 10 | Матеріали на 1000 кг: 48 123,40 грн | Переробка: 50 000 грн/т | Разом на 1000 кг: 98 123,40 грн | На 1 кг: 98,12 грн/кг без ПДВ'
}
```

## `priceScenario(model, id, inputs) → result` — `UX40_ВыбратьРецептНаСервере` + `UX40_РассчитатьСценарийНаСервере`

`inputs = { targetMargin = 25, extraCost = 0, volumeKg = 1000, mode = 'calc' }`. Inputs are rounded like the form
attributes (margin 2 decimals, others 4).
`mode:'calc'` (the «Розрахувати» button) checks in this order: no id → `'Виберіть рецептуру у дереві, пошуку або контролі.'`;
margin < 0 or ≥ 100 → `'Цільова маржа повинна бути від 0 до 99,99%.'`; extra < 0 or volume ≤ 0 →
`'Додаткові витрати ≥ 0, обсяг повинен бути > 0 кг.'`; unknown id → `'Специфікацію не знайдено у поточній вітрині.'`;
not fullCost → `'Немає повної перевіреної собівартості. Сценарій недоступний.'`.
`mode:'select'` (selecting a recipe) first gives `'Немає інформації про вибрану специфікацію.'` /
`'Рекомендацію заблоковано: не всі матеріали мають ціну.'`, then the `calc` checks.

```js
{ ok, recipe /* or null */, baseCost, baseSale,          // base values are filled whenever the recipe is known
  targetMargin, extraCost, volumeKg,
  scenarioCost /* baseCost + extraCost */, recommendedPrice /* round(scenarioCost / (1 − m/100), 4); 0 if !ok */,
  revenue /* round(rec × kg, 2) */, batchCost /* round(scenarioCost × kg, 2) */, grossProfit /* round(rev − cost, 2) */,
  markup /* round((rec − scenarioCost)/scenarioCost×100, 2) — extra, not in BSL */, deltaToCurrent /* round(rec − baseSale, 4) or null when no sale */,
  summary }  // 'Собівартість зі змінами: 98,12 грн/кг; виручка: 130 833,33 грн; витрати: 98 123,4 грн; валовий прибуток: 32 709,93 грн.'
```
(numeric fields are `null` when `ok` is false, except the base values.)

## `materialsInUse(model) → [{ id, name, recipes, chars, priceAvailable, price }]`

Distinct materials of the cache sorted by name (`uk` collation): `recipes` = number of distinct specs using it,
`chars` = distinct characteristic ids (`null` for empty), `priceAvailable` = any cache row with an available price,
`price` = first available cache price (or 0). For pickers.

## `materialImpact(model, materialId, percent = 10) → result` — `UX42_РассчитатьВлияниеНаСервере`

```js
{ ok, material, materialName, percent,
  rows: [{ spec, name, qty /* Σ qty per 1000 kg */, price /* last available price */,
           deltaKg /* Σ round(qty×price×pct/100/1000, 4); 0 when status ≠ 'ЦІНА Є' */,
           status /* 'ЦІНА Є' | 'НЕМАЄ ЦІНИ — ВПЛИВ НЕВІДОМИЙ' */ }],      // first-appearance order
  summary }  // 'Залежних рецептур: 7. Зміна ціни: 10% (для обраного матеріалу). Δ у грн/кг на основі 1000 кг виходу; без зміни BAS. Одиниці та еквівалентність характеристик перевіряйте окремо.'
```
Validation: no material → `'Виберіть матеріал з довідника або з нижньої калькуляції.'`; percent < −100 →
`'Зниження ціни не може перевищувати 100%.'` (`ok:false`, `rows: []`).

## `compareRecipes(model, idA, idB) → result` — `UX42_СравнитьНаСервере`

```js
{ ok, a, b /* recipes or null */,
  rows: [{ material, materialName, char, charName, qtyA, qtyB, price,
           diffKg /* round((qtyB − qtyA) × price / 1000, 4); 0 if status ≠ 'OK' */,
           status /* 'OK' | 'НЕМАЄ ЦІНИ' */ }],   // grouped by material+characteristic, first-appearance order
  delta /* round(Σ diffKg, 2) or null when incomplete */, problems,
  summary }  // 'Різниця Б − A: -1,25 грн/кг (негативна = Б дешевша). Переробка 50 грн/кг є в обох рецептах й взаємно скорочується. Ціни без ПДВ; не змінює записи BAS.'
             // or 'Неповне порівняння: 2 матеріалів без ціни. Загальну різницю не розраховано.'
```
Validation: `'Оберіть дві специфікації. Обрану в основному списку можна перенести кнопкою «Обрану → Б».'`,
`'Для порівняння потрібно вибрати РІЗНІ рецептури.'`, `'Для вибраних специфікацій немає складових у поточному завантаженні.'`.

## `dataQuality(model, { staleDays = 90, now }) → result` — `UX42_ПересчитатьКачествоНаСервере`

`staleDays ≤ 0` → 90. `now` (Date | ISO string) defaults to `model.generatedAt`, else the current date.
A cache row is *stale* when its price is available and `priceDate < now − staleDays days`.

```js
{ staleDays, limitDate /* Date */,
  rows: [{ spec, name, missing /* ЦенНет */, stale /* ЦенСтарых */,
           status /* 'НЕМАЄ СКЛАДУ' | 'НЕПОВНІ ЗАКУПІВЕЛЬНІ ЦІНИ' | 'ЗАСТАРІЛІ ЦІНИ' | 'НЕПЕРЕВІРЕНИЙ ПРОДАЖ' | 'ТЕХНІЧНО ПОВНІ ДАНІ' */,
           advice, ok /* status === 'ТЕХНІЧНО ПОВНІ ДАНІ' */ }],          // catalogue order
  recommendations: [{ priority, spec, name, signal, action }],          // sorted by priority, then name
  problems,
  summary,         // 'Перевірено рецептур: 64; є питання до даних: 12; актуальність закупівель: 90 днів.'
  adviceSummary }  // 'Рекомендацій: 15. Спочатку виправляйте дані, потім переглядайте рентабельність.'
```

## `productionPlan(model, planRows, stock) → result` — `NX50_ПересчитатьПланНаСервере`

`planRows = [{ spec, kg }]`, `stock = [{ material, char, qty }]` (scenario stock, not BAS stock).

```js
{ needs: [{ material, materialName, char, charName,
            need /* Σ qty × kg / 1000, round 4 */, price, sum /* round(need × price, 2); 0 without price */,
            stock /* number | null when not set */, deficit /* max(need − stock, 0); 0 when not set */,
            status /* 'OK' | 'НЕМАЄ ЦІНИ', + '; ЗАЛИШОК НЕ ЗАДАНО' */ }],
  totalKg, processing /* round(totalKg × 50, 2) */, knownCost, total /* knownCost + processing, or null if unknown > 0 */,
  unknown, deficitCount, noStockCount, linesUsed, missingSpecs /* plan specs without composition */,
  summary,         // 'План: 2 500 кг; матеріалів: 14; без ціни: 0; вартість відомих матеріалів: 120 345,5 грн; переробка: 125 000 грн. Разом: 245 345,5 грн.'
  stockSummary }   // 'Сценарний дефіцит матеріалів: 2; залишок не задано для: 12. НЕ є фактичним звітом про залишки BAS.'
```

Helpers (validation messages of the plan/stock buttons):
* `canAddToPlan(model, id, kg = 1000) → { ok, message }` — `NX50_ДобавитьВПланНаСервере`:
  `'Виберіть специфікацію та вкажіть партію понад 0 кг.'`, `'Немає складу обраної специфікації у завантажених даних. Натисніть «Оновити».'`.
* `checkStock(material, qty) → { ok, message }` — `NX50_ЗадатьОстатокНаСервере`:
  `'Спочатку виділіть матеріал у таблиці потреби.'`, `"Залишок не може бути від'ємним."`.

## Constructor — `NX50_ЗагрузитьКонструкторНаСервере`, `NX50_ПересчитатьКонструкторНаСервере`

* `constructorLoad(model, id) → result` — rows `{ material, char, qty }` of the spec from the cache, then
  `constructorCalc`. No id → `ok:false`, `summary: 'Виберіть базову специфікацію.'`, `rows: []`.
* `constructorCalc(model, id, rows) → result` — `rows = [{ material, char, qty }]` (quantity per 1000 kg, editable).

```js
{ ok /* complete */, rows: [{ material, materialName, char, charName, qty, price /* first available cache price of material+char or 0 */,
                              sum /* round(qty × price, 2) */, status /* 'OK' | 'КІЛЬКІСТЬ <= 0' | 'НЕМАЄ ЦІНИ В КЕШІ' */ }],
  total, unknown, invalid, newCost /* round((total + 50000)/1000, 4) or null */, baseCost /* or null */, diff /* or null */,
  summary }
// 'Немає матеріалів для розрахунку.' | 'НЕПОВНО: без цін 1; помилок кількості 0. Рекомендації заблоковані.' |
// 'Сценарна собівартість: 98,1234 грн/кг.' | 'Сценарна собівартість: 98,1234 грн/кг; базовий рецепт неповний, порівняння недоступне.' |
// 'Сценарна с/в 98,1234 грн/кг; базова 97,5; різниця 0,62 грн/кг. Переробка 50 грн/кг.'
```
* `canAddConstructorRow(material, qty) → { ok, message }` — `'Виберіть матеріал і додатну кількість.'`.

## `priceList(model, { margin = 25, step = 0.05 }) → result` — `NX50_СформироватьПрайсНаСервере`

Active recipes with fullCost; price = cost / (1 − margin/100) rounded **up** to the step (float-noise guarded:
cost 12.35, margin 0, step 0.05 → 12.35).

```js
{ ok, margin, step,
  rows: [{ spec, name, channel /* categoryPath */, cost, current /* sale */, recommended, diff /* round(rec − current, 4) */,
           status /* 'ПРОЕКТ / НЕ ЗАПИСАНО' | 'НЕМАЄ ПРОДАЖУ' */ }],
  skipped,
  summary }  // 'Проектні ціни: 50; без повної собівартості пропущено: 4; цільова маржа 25% (без ПДВ). Не враховані індивідуальні знижки клієнтів.'
```
Validation: `'Маржа: 0...99,99%; крок округлення > 0 грн.'`.
`priceListTsv(result) → string` — tab-separated text for Excel (header row in Ukrainian, decimal comma, no grouping).

## `energy({ kwhPerTon = 250, tariffA = 4, tariffB = 8, volumeKg = 1000 }) → result` — `NX50_РассчитатьЭнергиюНаСервере`

```js
{ ok, kwh /* round(kwhPerTon × kg / 1000, 3) */, costA, costB /* round(kwh × tariff, 2) */, diff /* round(B − A, 2) */,
  perKg /* round((tariffB − tariffA) × kwhPerTon / 1000, 4) */,
  summary }  // 'Партія 1 000 кг; 250 кВт·год. Тариф А: 1 000 грн; тариф Б: 2 000 грн; різниця Б−А: 1 000 грн (1 грн/кг). Це НЕ заміна фактичної калькуляції.'
```
Validation: `"Потрібні невід'ємні тарифи та споживання, а обсяг > 0."`.

## `assistant(model, question, ctx) → { command, answer }` — `NX50_ОтветитьНаСервере`

`ctx = { problemsCount, planSummary, energySummary }` (all optional: problems default to `control(model)`,
plan to `productionPlan(model, [], []).summary`, energy to `energy({}).summary`).
Rules in BSL order on the lower-cased, trimmed question: empty → `command:'empty'`; `допом` / `що вміє` → `help`;
`рецепт` → `recipes`; `проблем` → `problems`; `немає цін` / `без цін` → `noPrices`; `найдорож` → `mostExpensive`;
`план` → `plan`; `енерг` → `energy`; extra rules (not in BSL): `маржа`/`маржі` → `margin` (average margin of active
recipes, `'Середня маржа активних рецептур: 23,45 %.'`), `збитк` → `loss` (`'Збиткових позицій: 3.'`); otherwise `unknown`.
Answers are the BSL texts.

## `historyChanges(model, { onlyChanged = false }) → { rows, total, changed }`

Recipes that have `prev` (catalogue order); `onlyChanged` keeps `prev.changed` ones. `total` = `model.comparedCount`,
`changed` = number with `prev.changed`. For the «Історія змін» screen.

---

## Data helpers

### `validateData(data) → { ok, errors: [string], warnings: [string] }`

Errors (the document cannot be used): not an object, `format !== 'fortuna-data'`, unsupported `version`,
`specs` / `rows` not arrays. Warnings: rows with unknown spec / without material / with zero or non-numeric quantity,
materials without a name, malformed prices / sales / history, duplicate spec ids, unparsable `generatedAt`, no rows.
All texts in Ukrainian.

### `applyCategory(data, id, code) → { ok, message }` — `НазначитьКатегориюНаСервере` (demo / file mode)

Whitelist check (`'ПОМИЛКА: невідома категорія X'`), `features.categoryAttribute === false` →
`'ПОМИЛКА: створіть реквізит КатегорияКалькуляции у довіднику Спецификации та оновіть конфігурацію (F7).'`.
Sets `spec.category` (`NONE` → `''`) **and** `spec.status = 'Нова'` (a category means the recipe is used).
`'ГОТОВО: Рецептура 2024 v2 → Україна / Рудь'`. Rebuild the model afterwards.

### `applyStatus(data, id, status) → { ok, message }` — `ИзменитьСтатусРецептурыНаСервере`

`status` is `'Нова'` (active) or `'Стара'` (inactive); the category is kept. No id → `'ПОМИЛКА: не вибрано специфікацію.'`.
`'ГОТОВО: Рецептура 2024 v2 -> Стара'`. Rebuild the model afterwards.

---

## Methodology notes

* `processingPerTon` and `batchKg` come from `data.methodology` (defaults 50 000 / 1 000). Where the BSL hard-codes
  `+ 50000` and `/ 1000` the core uses `processingPerTon × batchKg / 1000` and `batchKg`, which is identical for the
  default methodology. Texts keep the BSL literals («50 000 грн/т», «1000 кг», «50 грн/кг»).
* The BSL accumulates the recipe cost in a form-tree column of type `Число(18,4)`; the core rounds the running sum to
  4 decimals in the same way. Detail rows round `qty × price` to 4 decimals (`Сумма`, `Число(18,4)`).
* Sorting is stable everywhere; string sorts use `localeCompare(…, 'uk')`.
