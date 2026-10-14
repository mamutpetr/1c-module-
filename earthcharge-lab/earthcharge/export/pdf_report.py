"""Звіт PDF (Qt: QTextDocument + QPdfWriter, графіки рендеряться pyqtgraph)."""
from __future__ import annotations

import html
from datetime import datetime

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters  # noqa: F401
from PySide6.QtCore import QMarginsF, QSizeF, QUrl
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

from .. import APP_NAME, APP_SUBTITLE, APP_VERSION
from ..core import materials as M
from ..core.analysis import analyze
from ..core.design import LOAD_MODES
from ..core.economics import LINE_LABELS, compare_cartridges, physics_from_simulation
from ..core.params import GROUP_LABELS, build_params
from ..core.provenance import STATUS_LABELS, Status
from ..core.simulator import LEDGER_LABELS
from ..core.units import format_duration, fmt

PRINT_SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
LEVEL_TXT = {"ok": "✔", "info": "•", "warning": "▲", "critical": "✖"}


def _chart(title: str, unit: str, x, ys: list, names: list, x_label: str = "Час, год"):
    pw = pg.PlotWidget()
    pw.setBackground("w")
    pw.resize(620, 360)
    pi = pw.getPlotItem()
    pi.showGrid(x=True, y=True, alpha=0.2)
    pi.setLabel("left", unit, color="#52514e")
    pi.setLabel("bottom", x_label, color="#52514e")
    for ax in ("left", "bottom"):
        pi.getAxis(ax).setPen(pg.mkPen("#c3c2b7"))
        pi.getAxis(ax).setTextPen(pg.mkPen("#52514e"))
    if len(ys) > 1:
        pi.addLegend(offset=(-10, 10), labelTextColor="#0b0b0b", labelTextSize="10pt")
    for k, (y, n) in enumerate(zip(ys, names)):
        pi.plot(np.asarray(x), np.asarray(y), pen=pg.mkPen(PRINT_SERIES[k % 4], width=2), name=n, connect="finite")
    exp = pg.exporters.ImageExporter(pi)
    exp.parameters()["width"] = 1100
    img = exp.export(toBytes=True)
    pw.deleteLater()
    return img


def _table(rows, header=None, widths=None) -> str:
    out = ['<table width="100%" cellspacing="0" cellpadding="4" style="border-collapse: collapse;">']
    if header:
        out.append("<tr>" + "".join(f'<th align="left" style="background:#eef1f4;border-bottom:1px solid #c3c2b7;">'
                                    f"{html.escape(str(h))}</th>" for h in header) + "</tr>")
    for k, r in enumerate(rows):
        bg = "#ffffff" if k % 2 == 0 else "#f7f8fa"
        out.append(f'<tr style="background:{bg};">' + "".join(
            f'<td style="border-bottom:1px solid #e1e0d9;">{html.escape(str(c))}</td>' for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def build_report(path: str, ctrl, sim) -> None:
    sc = sim.sc
    d = sc.design
    doc = QTextDocument()
    doc.setDefaultStyleSheet("body { font-family: 'Segoe UI', 'DejaVu Sans', Arial; font-size: 9.5pt; color: #0b0b0b; }"
                             "h1 { font-size: 18pt; } h2 { font-size: 13pt; color: #184f95; margin-top: 14px; }"
                             "p.muted { color: #52514e; }")
    parts = []
    parts.append(f"<h1>{APP_NAME}</h1><p class='muted'>{APP_SUBTITLE} · версія {APP_VERSION} · "
                 f"{datetime.now().strftime('%d.%m.%Y %H:%M')}</p>")
    parts.append(f"<p><b>Варіант:</b> {html.escape(d.name)} &nbsp; <b>Навантаження:</b> "
                 f"{html.escape(LOAD_MODES.get(sim.mode, sim.mode))} &nbsp; <b>Змодельовано:</b> {format_duration(sim.state.t)}</p>")
    ps = build_params(d)
    unc = sum(1 for _, p in ps.items() if p.status in (Status.ASSUMPTION, Status.LITERATURE))
    parts.append(f"<p style='background:#fff6e0;padding:6px;'><b>Оціночна модель.</b> Результати ґрунтуються на "
                 f"{unc} неперевірених параметрах (припущення або літературний діапазон). Це не гарантований прогноз: "
                 f"порівнюйте з дослідами й калібруйте модель.</p>")

    # --- конструкція
    g = d.geometry
    rows = [("Анод", M.ANODES[d.anode].name), ("Катод", M.CATHODES[d.cathode].name),
            ("Тип конструкції", M.CATEGORY_LABELS[M.CATHODES[d.cathode].category]),
            ("Електроліт", M.ELECTROLYTES[d.electrolyte].name), ("Сепаратор", M.SEPARATORS[d.separator].name),
            ("Пластина", f"{fmt(g.plate_length_mm, 1)} × {fmt(g.plate_width_mm, 1)} мм, товщина {fmt(sim.geo.thickness_mm, 2)} мм"),
            ("Робочі сторони анода", str(g.faces)), ("Зазор анод — катод", f"{fmt(g.gap_mm, 1)} мм"),
            ("Електроліт на комірку", f"{fmt(g.electrolyte_volume_ml, 0)} мл"),
            ("З'єднання", f"{sim.geo.n_series} послідовно × {sim.geo.n_parallel} паралельно"),
            ("Перетворювач", (f"{'MPPT' if d.converter.control == 'mppt' else 'простий boost'}, ККД {fmt(d.converter.efficiency_pct, 0)} %, "
                              f"V_min {fmt(d.converter.v_in_min, 2)} В, обмеження {fmt(d.converter.p_out_max_w, 1)} Вт")
             if d.converter.enabled else "вимкнено"),
            ("Суперконденсатор", f"{fmt(d.supercap.capacitance_f, 1)} Ф, {fmt(d.supercap.v_max, 2)} В, запуск USB через "
                                 f"{fmt(d.supercap.start_delay_s, 0)} с" if d.supercap.enabled else "немає"),
            ("Температура середовища", f"{fmt(d.environment.ambient_c, 1)} °C")]
    parts.append("<h2>1. Конструкція</h2>" + _table(rows, ["Параметр", "Значення"]))
    try:
        a = analyze(d)
        parts.append("<h2>2. Розрахункові характеристики</h2>" + _table(a.as_rows(), ["Величина", "Значення"]))
    except Exception as exc:  # noqa: BLE001
        parts.append(f"<p>Аналіз недоступний: {html.escape(str(exc))}</p>")

    # --- результати
    s = sim.summary()
    res_rows = [("Енергія на виводах комірок", f"{fmt(s['e_term_wh'], 2)} Вт·год"),
                ("Енергія на виході (USB-C / навантаження)", f"{fmt(s['e_out_wh'], 2)} Вт·год"),
                ("Середня потужність на виході", f"{fmt(s['p_avg_out_w'], 2)} Вт"),
                ("Маса Mg: початкова / витрачено", f"{fmt(s['mg_initial_g'], 1)} г / {fmt(s['mg_consumed_g'], 2)} г"),
                ("  корисний струм / самокорозія / механічні", f"{fmt(s['mg_useful_g'], 2)} / {fmt(s['mg_corr_g'], 2)} / {fmt(s['mg_chunk_g'], 2)} г"),
                ("Ефективність анода", f"{fmt(s['anode_eff_pct'], 1)} %"),
                ("Ефективність хімія → вихід", f"{fmt(s['sys_eff_pct'], 1)} %"),
                ("Питома енергія на виході", f"{fmt(s['wh_per_g_out'], 2)} Вт·год/г Mg"),
                ("Водень сумарно / пікова концентрація", f"{fmt(s['h2_total_l'], 2)} л / {fmt(s['peak_h2_pct'], 2)} %"),
                ("Пікова температура електроліту", f"{fmt(s['peak_t_el'], 1)} °C"),
                ("Причина завершення", s["finish_reason"] or "триває")]
    if sim.phone:
        res_rows.insert(0, ("Заряд телефона", f"{fmt(s['phone_soc_pct'], 1)} % (ціль {fmt(sc.phone.soc_target_pct, 0)} %)"))
    parts.append("<h2>3. Результати симуляції</h2>" + _table(res_rows, ["Показник", "Значення"]))
    parts.append("<p>" + "<br>".join(f"{LEVEL_TXT.get(lv, '•')} {html.escape(t)}" for lv, t in s["verdicts"]) + "</p>")

    # --- графіки
    r = sim.rec
    t = r.get("t_h")
    usb = sim.mode in ("phone", "usb_power", "mppt")
    charts = [("Напруга", "В", [r.get("v_term"), r.get("v_cell")], ["Батарея комірок", "Комірка"]),
              ("Потужність", "Вт", [r.get("p_term"), r.get("p_usb")] if usb else [r.get("p_term")],
               ["Виводи", "USB-C"] if usb else ["Виводи"]),
              ("Енергія", "Вт·год", [r.get("e_term_wh"), r.get("e_usb_wh")] if usb else [r.get("e_term_wh")],
               ["Виводи", "USB-C"] if usb else ["Виводи"]),
              ("Витрата магнію", "г", [r.get("mg_useful_g"), r.get("mg_corr_g"), r.get("mg_remaining_g")],
               ["Корисний струм", "Самокорозія", "Залишок"]),
              ("Ефективність", "%", [r.get("anode_eff_cum"), r.get("sys_eff")], ["Анод", "Хімія → вихід"])]
    if sim.phone:
        charts.append(("Заряд телефона", "%", [r.get("phone_soc")], ["Заряд"]))
    if sim.cap:
        charts.append(("Енергія суперконденсатора", "Дж", [r.get("cap_j")], ["Енергія"]))
    parts.append("<h2>4. Графіки</h2><table width='100%' cellspacing='6'>")
    for k, (title, unit, ys, names) in enumerate(charts):
        img = _chart(title, unit, t, ys, names)
        name = f"chart{k}.png"
        doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        if k % 2 == 0:
            parts.append("<tr>")
        parts.append(f'<td width="50%"><b>{html.escape(title)}</b><br><img src="{name}" width="330"></td>')
        if k % 2 == 1:
            parts.append("</tr>")
    if len(charts) % 2 == 1:
        parts.append("<td></td></tr>")
    parts.append("</table>")

    # --- енергобаланс
    br = sim.ledger_breakdown()
    ideal = sim.ledger.ideal_j
    rows = [(LEDGER_LABELS.get(k, k), fmt(v / 3600, 3), fmt(100 * v / ideal, 1) if ideal > 0 else "—")
            for k, v in sorted(br.items(), key=lambda kv: -kv[1])]
    rows.append(("Разом: хімічна енергія Mg (3,09 В)", fmt(ideal / 3600, 3), "100,0"))
    worst = max(abs(x) for x in sim.residuals().values())
    parts.append("<h2>5. Енергетичний баланс</h2>" + _table(rows, ["Стаття", "Вт·год", "%"]) +
                 f"<p class='muted'>Найбільший залишок балансових тотожностей: {worst:.1e} Дж.</p>")

    # --- припущення
    rows = []
    for key, p in ps.items():
        if p.status == Status.REFERENCE:
            continue
        rows.append((GROUP_LABELS.get(key.split(".")[0], ""), p.label, f"{p.value:.4g}".replace(".", ","), p.unit,
                     STATUS_LABELS[p.status]))
    parts.append("<h2>6. Неперевірені та змінені параметри моделі</h2>" +
                 _table(rows, ["Група", "Параметр", "Значення", "Одиниці", "Статус"]))

    # --- економіка
    try:
        phys = physics_from_simulation(sim) if sim.mode == "phone" else ctrl.phys_manual
        res = compare_cartridges(phys, ctrl.prices)
        cur = ctrl.prices.currency
        rows = [("Маса Mg у картриджі, г", *[fmt(x.mg_mass_g, 1) for x in res])]
        rows += [(f"{LINE_LABELS[k]}, {cur}", *[fmt(x.lines[k], 2) for x in res]) for k in LINE_LABELS]
        rows += [(f"Собівартість, {cur}", *[fmt(x.cogs, 2) for x in res]),
                 (f"Ціна без ПДВ, {cur}", *[fmt(x.price_net, 2) for x in res]),
                 (f"Роздрібна ціна, {cur}", *[fmt(x.price_retail, 2) for x in res]),
                 ("Валова маржа, %", *[fmt(x.gross_margin_pct, 1) for x in res]),
                 (f"Вартість заряджання для покупця, {cur}", *[fmt(x.cost_per_charge_customer, 2) for x in res])]
        parts.append("<h2>7. Економіка картриджів</h2><p class='muted'>Ціни задані користувачем або є прикладом. "
                     f"Фізичні вхідні дані: {html.escape(phys.source)}.</p>" +
                     _table(rows, ["Показник"] + [f"{x.charges} заряд." for x in res]))
    except Exception as exc:  # noqa: BLE001
        parts.append(f"<p>Економіка недоступна: {html.escape(str(exc))}</p>")

    doc.setHtml("<body>" + "".join(parts) + "</body>")
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)
    writer.setResolution(110)
    writer.setTitle(f"{APP_NAME}: {d.name}")
    writer.setCreator(f"{APP_NAME} {APP_VERSION}")
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    doc.print_(writer)

