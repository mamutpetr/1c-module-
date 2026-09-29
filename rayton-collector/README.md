# Збирач даних з контролера Rayton

Кабінет контролера (`http://192.168.0.57/dashboard`) показує лише поточні значення й нічого не зберігає.
`collector.py` цілодобово записує їх у CSV. Так у вас накопичується власна історія, яку потім можна передавати на сайт.

## Звідки беруться дані

Кабінет зроблено на Node-RED (FlowFuse Dashboard 2.0). Значення надходять через Socket.IO
(`/dashboard/socket.io`, лише polling) приблизно раз на секунду:

| Показник (`topic`) | Що це | Одиниці |
|---|---|---|
| `POWER_CONTROL_SOLAR_GENERATION` | генерація СЕС | кВт |
| `POWER_CONTROL_PLANT_CONSUMPTION` | споживання підприємства | кВт |
| `POWER_CONTROL_GRID_CONSUMPTION` | мережа: **+** купуємо, **−** віддаємо | кВт |
| `POWER_CONTROL_ESS_POWER` | АКБ: **+** розряд, **−** заряд | кВт |
| `RT_DATA_ESS_SOC` | заряд АКБ | % |

Контролер рахує споживання як СЕС + мережа + АКБ; на записаних даних рівність виконується точно, звідси й знаки.
Одиниці ми визначили за величинами, а не за документацією.
Окремо надходить графік заряду/розряду АКБ по годинах на сьогодні й завтра. Скрипт зберігає його в `data/schedule.json`.

Лічильників енергії (кВт·год) кабінет не передає. Енергію рахуватимемо з потужності: кВт·год = Σ кВт × Δt.
Якщо контролер почне передавати новий показник, скрипт напише про це в консоль і додасть колонку в CSV.

**Скрипт тільки читає.** Він нічого не надсилає контролеру, тому змінити режим роботи станції не може.

## Запуск (будь-який комп'ютер у мережі контролера)

```bash
pip install -r requirements.txt
python collector.py                       # рядок кожні 5 с у data/РРРР-ММ-ДД.csv
python collector.py --interval 1          # щосекунди
python collector.py --url http://192.168.0.57 --out D:\rayton
```

Приклад `data/2026-09-29.csv`:

```
time,POWER_CONTROL_SOLAR_GENERATION,POWER_CONTROL_PLANT_CONSUMPTION,POWER_CONTROL_GRID_CONSUMPTION,POWER_CONTROL_ESS_POWER,RT_DATA_ESS_SOC
2026-09-29T16:28:40+03:00,34.326,26.67,-0.656,-7,96
```

Час записується з часовим поясом, щоб перехід на зимовий час не плутав дані. Обсяг приблизно 1 МБ на добу при записі кожні 5 с.
Excel відкриває файл через «Дані → З текстового/CSV-файлу».

Скрипт сам перепідключається, якщо зникне мережа або перезавантажиться контролер.
Поки даних немає, рядки не пишуться, щоб старі значення не записалися як нові. Тому в файлі видно реальні пропуски.

## Автозапуск

**Windows:** скрипт запускається разом із комп'ютером, навіть без входу користувача.
Шлях до `pythonw.exe` покаже команда `where pythonw`. Команду нижче виконуйте в cmd від імені адміністратора:

```
schtasks /create /tn "Rayton collector" /sc onstart /ru SYSTEM /tr "\"C:\шлях\до\pythonw.exe\" \"C:\rayton-collector\collector.py\""
```

**Linux / Raspberry Pi:** `/etc/systemd/system/rayton-collector.service`

```ini
[Service]
ExecStart=/usr/bin/python3 /opt/rayton-collector/collector.py
Restart=always
[Install]
WantedBy=multi-user.target
```

Потім виконайте `sudo systemctl enable --now rayton-collector`.

## Перевірка без контролера

`mock_controller.py` надсилає ті самі події з вигаданими значеннями. Він знадобиться, щоб розробляти сайт поза мережею контролера.

```bash
pip install aiohttp
python mock_controller.py                                  # http://127.0.0.1:8080
python collector.py --url http://127.0.0.1:8080 --interval 1
```
