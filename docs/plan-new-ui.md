# План: новый интерфейс (тёмная тема + сайдбар, вариант 2a)

Документ составлен 2026-08-06. Дизайн-источник: `00-inbox/Video download app mockups/design_handoff_video_downloader_ui/`.

---

## 0. Как пользоваться этим документом

Работу ведёт исполнитель (`coder`, быстрая модель), который **не видел этого обсуждения и не читал макетов**. Всё, что ему нужно, — здесь.

Правила:

1. Этапы выполняются **строго по порядку**, с 1 по 8. Каждый этап — самостоятельное задание в формате «Задача / Что менять / Проверка / Чего НЕ делать».
2. **После каждого этапа — прогон `python tests/smoke_test.py` до зелёного.** Следующий этап не начинается, пока предыдущий красный.
3. После этапов 4, 5, 6 (визуальные) — **остановка и показ пользователю**, прежде чем идти дальше. Это требование процесса проекта, а не формальность: пользователь смотрит вид глазами и утверждает.
4. Если код не совпадает с описанием в плане — **остановиться и сказать**, а не подгонять по смыслу.
5. Числа, цвета, тексты и имена в этом документе — финальные. Не «примерно так», а ровно так.

Разделы 1–8 — справочные (данные, роуты, токены, DOM). Этапы — рабочие.

---

## 1. Источники правды

| Что | Где |
|---|---|
| Финальный дизайн | `00-inbox/.../Video Downloader Mockups.dc.html`, секция `id="t2"`, вариант `2a` |
| Словесный хендофф | `00-inbox/.../README.md` |
| Текущий интерфейс | `templates/index.html` |
| Текущий бэкенд | `app.py` |
| Правила проекта | `CLAUDE.md`, `.claude/skills/video-downloader-workflow/SKILL.md` |

Прототип `.dc.html` открывается не как обычная страница (в нём кастомный раннер и ссылка на отсутствующий `support.js`) — **читать его как разметку**, значения брать из inline-стилей. Файла `preview.html`, упомянутого в README, в архиве нет.

Вариант `2a` — это семь окон подряд в секции `t2`: «Скачать» пусто / прогресс / ошибка / предупреждения, «История» список / пусто, «Настройки». Варианты `1a`, `1b`, `1c` — черновые направления, **их не реализуем**.

---

## 2. Принятые решения

Решения пользователя (спрошены явно, обсуждению не подлежат):

| Вопрос | Решение |
|---|---|
| Кнопка «×» в истории | **Удаляет файл с диска** вместе с записью. Правило «файлы неприкосновенны» переписывается: удаление допустимо только как явное действие пользователя в истории. Уборщик `sweep_once` по-прежнему не трогает диск. |
| Папка загрузок | **Полноценная смена**: путь хранится в настройках, меняется через диалог выбора папки (в приложении) и ручным вводом (в браузере). |
| Тема | **Только тёмная.** Переключатель «Светлая/Тёмная» из макета настроек убирается. |
| Наполнение истории | **Скан папки загрузок** — список строится из реальных файлов; журнал `history.json` дополняет их названием, качеством и ссылкой. |

Решения проектировщика (приняты, чтобы исполнителю не пришлось выбирать):

- **Одна загрузка за раз.** Очередь не вводится: сейчас интерфейс ведёт одну задачу (`currentJobId`), и макет истории с этим совместим — активная строка максимум одна. Параллельные загрузки — отдельная задача, не эта.
- **Автообновление становится настоящим переключателем.** Выключено — при старте проверка не запускается, `/api/update` отдаёт `state: "disabled"`, баннер молчит. Включено обратно — проверка стартует сразу, без перезапуска.
- **`updater.py` не трогаем.** Вся логика включателя живёт в `app.py`. Зона влияния меньше, ломать нечего.
- **Заготовки под светлую тему не делаем**, но все цвета всё равно заводятся CSS-переменными в `:root` — так принято в файле сейчас, и это ничего не стоит.
- **Кастомный титлбар не рисуем** (см. раздел 3).
- **`window.confirm` не используется нигде** — подтверждение удаления рисуется внутри строки истории. Системные модалки в WebView2 ведут себя непредсказуемо, а свой блок и выглядит по макету.

---

## 3. Расхождения с макетом — сознательные

Исполнитель реализует именно то, что ниже, а не то, что в макете. Каждый пункт объяснён, чтобы никто через полгода не «починил» это обратно.

1. **Титлбар окна (полоса с зелёным квадратом, названием и `– □ ×`) не реализуется.** Его рисует Windows: окно pywebview имеет нативную рамку. Чтобы получить макет буквально, окно пришлось бы сделать frameless и написать своё перетаскивание, ресайз и кнопки управления — это несоразмерно задаче и ломается в WebView2. Внутри страницы титлбара нет, сайдбар начинается сразу.

2. **Светлая тема и её переключатель отсутствуют** — решение пользователя. Строка «Тёмная тема» из макета настроек не рисуется вообще (не «неактивной», а её просто нет).

3. **Цвета текста в дополнительных сообщениях об ошибке исправлены.** В макете для сети/диска указаны `#c0392b` и `#8a6d1f` — это цвета из старой светлой темы, на фоне `#14171A` они почти нечитаемы. Берём: ошибка — `#FF6B6B`, предупреждение (мало места) — `#E8B339`, то есть те же токены, что и в остальной тёмной теме.

4. **Экран «Скачать» получает состояние «Готово», которого нет в макете.** Сейчас оно есть в работающем приложении (ссылка «Готово: … — скачать файл»), терять его нельзя. Рисуется симметрично блоку ошибки, только в акцентном зелёном (`rgba(61,220,132,.08)` / `rgba(61,220,132,.25)`), внутри — название и действие: «Показать в папке» в приложении, «Скачать файл» в браузере.

5. **Строка «Стоп» в истории не дублирует отмену.** В макете у активной строки есть «Стоп» — реализуем, но это тот же `/api/cancel/<job_id>`, что и на экране «Скачать».

6. **Плейсхолдеры превью** — не миниатюры видео (yt-dlp кадр не сохраняет), а полосатый паттерн из макета. Так и задумано дизайнером, см. раздел «Assets» в README.

7. **«Обзор» работает только в приложении.** В браузере (`python app.py`) диалога выбора папки не существует — там поле пути становится редактируемым, а кнопка «Обзор» скрыта. Это единственное место, где два режима выглядят по-разному.

---

## 4. Что появляется в проекте

| Файл | Что с ним |
|---|---|
| `app.py` | Новые константы, работа с настройками как со словарём, изменяемая папка загрузок, журнал истории, 4 новых роута, `error_kind` в ошибках |
| `templates/index.html` | Переписывается целиком: тёмная тема, сайдбар, три экрана |
| `desktop.py` | Размер окна, колбэк диалога выбора папки, запуск проверки обновлений с оглядкой на настройку |
| `tests/smoke_test.py` | ~40 новых проверок, правка существующих под `current_download_dir()` |
| `CLAUDE.md` | Правило про удаление файлов, состав, настройки, журнал изменений |

Новых зависимостей нет. `requirements.txt` не меняется.

---

## 5. Формат данных

### 5.1 `settings.json`

Было: `{"target_height": 720}`. Стало:

```json
{
  "target_height": 720,
  "download_dir": null,
  "auto_update": true
}
```

- `download_dir`: `null` — папка по умолчанию (`default_download_dir()`); строка — абсолютный путь, выбранный пользователем.
- `auto_update`: `true` по умолчанию.
- Старый файл с одним `target_height` читается без ошибок: недостающие ключи берутся из умолчаний.
- Испорченный файл (не JSON, не объект, чужие типы) — молча откат к умолчаниям целиком. Настройка не повод не дать скачать видео.

### 5.2 `history.json`

Лежит рядом с `settings.json` (та же папка: `BASE_DIR` из исходников, `%LOCALAPPDATA%\VideoDownloader\` в собранном виде).

```json
{"items": [
  {
    "filename": "3f2a...c1_Wellerman.mp4",
    "dir": "E:\\Projects\\video-downloader-service\\downloads",
    "title": "Wellerman (Sea Shanty)",
    "height": 720,
    "url": "https://youtu.be/xxxx",
    "size": 64127488,
    "finished_at": 1770000000.0
  }
]}
```

Журнал — **не источник списка**, а справочник: он подсказывает название, качество и ссылку для файлов, которые нашлись на диске. Файл, которого нет, в списке не появится, даже если запись осталась. Файл без записи появится — с именем вместо названия.

`HISTORY_LIMIT = 200`: при добавлении 201-й записи самая старая выбрасывается. Речь только про записи журнала — файлы на диске не трогаются.

---

## 6. Роуты

| Метод и путь | Состояние | Что делает |
|---|---|---|
| `GET /` | есть | Страница. Список переменных шаблона — в 8.1 |
| `POST /api/download` | есть | Без изменений снаружи; внутри job теперь хранит `url` и `height` |
| `GET /api/progress/<job_id>` | есть | В ответе добавляются `error_kind` и `current_name` |
| `POST /api/cancel/<job_id>` | есть | Без изменений |
| `GET /api/file/<filename>` | правка | Ищет файл во всех известных каталогах, не только в текущем |
| `POST /api/quality` | есть | Без изменений |
| `GET /api/update` | правка | При выключённом автообновлении отдаёт `state: "disabled"` |
| `POST /api/update/install` | есть | Без изменений |
| `POST /api/open-folder/<filename>` | правка | Ищет файл во всех известных каталогах |
| `GET /api/history` | **новый** | Список для экрана «История» |
| `POST /api/history/delete/<filename>` | **новый** | Удаляет файл с диска и запись из журнала |
| `POST /api/download-dir` | **новый** | Меняет папку загрузок |
| `POST /api/browse-folder` | **новый** | Открывает системный диалог выбора папки (только в приложении) |
| `POST /api/auto-update` | **новый** | Включает/выключает проверку обновлений |

---

## 7. Дизайн-токены → CSS-переменные

Все цвета объявляются в `:root` и дальше используются **только через `var()`**. Хардкод цвета где-либо кроме `:root` — ошибка.

```
--bg-rail:      #0F1B14   /* сайдбар */
--bg-content:   #14171A   /* рабочая область */
--surface:      #1B1F23   /* поля, карточки, строки списка */
--surface-sunk: #101316   /* дорожка тонкого прогресса в истории */
--border:       rgba(255,255,255,.06)
--border-strong:rgba(255,255,255,.12)
--text:         #ECEFEC
--text-dim:     #8B9490
--text-faint:   #65706b
--text-faintest:#55625b
--accent:       #3DDC84   /* было #1F7A4D */
--accent-ink:   #0e2016   /* текст на акцентной заливке */
--accent-soft:  rgba(61,220,132,.15)
--accent-ghost: rgba(61,220,132,.04)
--accent-line:  rgba(61,220,132,.3)
--info:         #2E6FE0   /* прогресс в истории */
--danger:       #FF6B6B
--danger-bg:    rgba(255,107,107,.08)
--danger-line:  rgba(255,107,107,.25)
--warn:         #E8B339
--warn-bg:      rgba(232,179,57,.1)
--warn-line:    rgba(232,179,57,.3)
--ok-bg:        rgba(61,220,132,.08)
--ok-line:      rgba(61,220,132,.25)
--disabled-bg:  #2A2F33
--disabled-text:#6b7570
--r-field: 9px; --r-card: 10px; --r-drop: 14px
```

Типографика: `'Segoe UI', system-ui, sans-serif`. Заголовок экрана 16px/700. Тело 12–13px. Мелкое 10–11px. Лог ошибки — `Consolas, Menlo, monospace` 11px.

Отступы: контент — `padding: 26px`; вертикальный ритм полей — `gap: 14px`; строки списка — `padding: 8px 10px`, `gap: 10px`.

---

## 8. Карта страницы

### 8.1 Переменные шаблона (что отдаёт `index()`)

`quality_options`, `selected_height`, `ffmpeg_available`, `app_version`, `desktop_mode`, `download_dir`, `auto_update`, `max_filesize`.

### 8.2 Дерево DOM

Идентификаторы обязательны — на них опираются проверки и JS.

```
body[data-desktop="true|false"]
  .window
    nav.rail
      button.navitem[data-screen="download"].active > .navpill>.navdot + span «Скачать»
      button.navitem[data-screen="history"]        > .navpill>.navdot + span «История»
      button.navitem[data-screen="settings"]       > .navpill>.navdot + span «Настройки»
    main.content
      section#screen-download.screen.active
        h2.scrhead «Скачать видео по ссылке»
        div#ffmpegBanner.banner.banner-warn          (только если ffmpeg не найден)
        div#updateBanner.banner.banner-accent        (display:none по умолчанию)
          .banner-row > span#updateText + button#updateBtn «Обновить»
          .banner-note#updateNote
        div#dropZone.dropzone
          «Вставьте ссылку или перетащите её сюда» / «YouTube, VK, Twitch и другие»
        div.row
          input#url[type=text][placeholder="https://..."]
          button#btn «Скачать» (disabled, пока поле пустое)
          button#stopBtn.stop «Стоп» (скрыта)
        div.quality-row > label + select#quality (option'ы из quality_options)
        div#progressWrap                            (скрыт)
          .progress-head > span#progressName + span#progressStat
          #progressBar > #progressFill
        div#status                                  (блоки ошибки/успеха)
        div#footHint.foot-hint
      section#screen-history.screen
        h2.scrhead «История и очередь»
        div#historyList
        div#historyEmpty                            (пустое состояние)
      section#screen-settings.screen
        h2.scrhead «Настройки»
        .setting «Качество по умолчанию» > .pills > button.pill[data-height]
        .setting «Папка загрузок» > input#dirPath + button#browseBtn «Обзор»
          div#dirNote.setting-note
        .setting-row «Автообновление» > button#autoUpdateToggle.toggle
        .settings-foot  «ffmpeg найден. Версия X.»
```

Переключение экранов: у `section.screen` — `display:none`, у `.screen.active` — `display:block`. Клик по `.navitem` снимает `.active` со всех и ставит нужным.

### 8.3 Точная разметка двух мест, на которые смотрят проверки

Селект качества (как сейчас, менять формат нельзя — на нём висит существующая проверка):

```html
<option value="{{ height }}"{% if height == selected_height %} selected{% endif %}>{{ label }}</option>
```

Пилюля качества в настройках — порядок атрибутов ровно такой:

```html
<button type="button" class="pill{% if height == selected_height %} active{% endif %}" data-height="{{ height }}">{{ height }}p</button>
```

---

# Этапы

---

## Этап 1. Настройки — из одного числа в словарь

### Задача
`settings.json` начинает хранить не только качество, но и папку загрузок с флагом автообновления. Снаружи ничего не меняется — это фундамент для этапов 2 и 6.

### Что менять — `app.py`

**1.1.** Рядом с `SETTINGS_PATH` добавить константы:

```python
# Журнал загрузок лежит рядом с настройками: в собранном виде это
# %LOCALAPPDATA%, из исходников — папка проекта.
HISTORY_PATH = os.path.join(os.path.dirname(SETTINGS_PATH), "history.json")

# Сколько записей журнала храним. Речь только про записи: файлы на диске
# не удаляются, даже когда запись о них выпала из журнала.
HISTORY_LIMIT = 200

DEFAULT_SETTINGS = {
    "target_height": TARGET_HEIGHT,
    "download_dir": None,
    "auto_update": True,
}
```

**1.2.** Добавить функции (порядок: сразу после `write_saved_height`):

```python
def read_settings():
    """Все настройки одним словарём.

    Отсутствующие и мусорные значения заменяются умолчаниями поштучно:
    испорченный флаг обновлений не должен обнулять выбранное качество.
    """
```

Поведение по пунктам:
- открыть `SETTINGS_PATH`, распарсить JSON; `OSError`/`ValueError` или результат не `dict` → вернуть `dict(DEFAULT_SETTINGS)`;
- `target_height` → через `normalize_height()`;
- `download_dir` → строка непустая после `strip()`, иначе `None`;
- `auto_update` → `bool(...)`, если значение не `bool` — умолчание `True`;
- вернуть словарь ровно с тремя ключами.

```python
def write_settings(**changes):
    """Дописывает переданные ключи, не теряя остальные."""
```
- прочитать через `read_settings()`, обновить переданным, создать каталог, записать;
- `OSError` → `print(f"[настройки] не сохранились: {e}")`, не падать.

**1.3.** Переписать существующие функции как обёртки — **имена сохранить**, на них есть проверки:

```python
def read_saved_height():
    return read_settings()["target_height"]

def write_saved_height(height):
    write_settings(target_height=height)

def read_auto_update():
    return read_settings()["auto_update"]
```

**1.4.** Роут `/api/update` — при выключённом автообновлении не показывать ничего:

```python
@app.route("/api/update")
def update_status():
    # Выключённая проверка — не «нет обновлений», а «не спрашивали»:
    # интерфейс на это состояние просто молчит.
    if not read_auto_update():
        return jsonify({**updater.get_state(), "state": "disabled"})
    return jsonify(updater.get_state())
```

**1.5.** Новый роут (ставить рядом с `/api/quality`):

```python
@app.route("/api/auto-update", methods=["POST"])
def set_auto_update():
```
- `enabled = bool(request.get_json(silent=True).get("enabled"))` (при отсутствии тела — `False`);
- `write_settings(auto_update=enabled)`;
- если включили — `updater.start_check_async()`, чтобы баннер появился без перезапуска;
- ответ `{"auto_update": enabled}`.

**1.6.** В `if __name__ == "__main__":` вызов `updater.start_check_async()` обернуть условием `if read_auto_update():`.

### Проверка
В `tests/smoke_test.py`, в блок «качество запоминается между запусками» (там уже подменяется `SETTINGS_PATH`) добавить:
- старый формат файла `{"target_height": 1080}` читается: `read_settings()["target_height"] == 1080` и `read_settings()["auto_update"] is True`;
- `write_settings(auto_update=False)` не теряет качество: `read_settings()["target_height"] == 1080`;
- испорченный файл: все три ключа равны умолчаниям;
- `POST /api/auto-update {"enabled": false}` → `{"auto_update": false}`, после этого `GET /api/update` отдаёт `state == "disabled"`;
- обратно `{"enabled": true}` → `state != "disabled"`.

Прогон: `python tests/smoke_test.py` — 0 падений.

### Чего НЕ делать
- Не кешировать настройки в модульной переменной: тесты подменяют `SETTINGS_PATH` на лету, кеш их сломает. Файл крошечный, читаем каждый раз.
- Не трогать `updater.py`.
- Не менять формат ответа `/api/quality`.

---

## Этап 2. Папка загрузок становится изменяемой

### Задача
Пользователь может выбрать, куда складывать видео. Файлы, скачанные в прежнюю папку, продолжают отдаваться и открываться в проводнике.

### Что менять — `app.py`

**2.1.** Убрать глобальные строки:

```python
DOWNLOAD_DIR = default_download_dir()
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
```

Вместо них — функция:

```python
def current_download_dir():
    """Куда качаем сейчас: выбор пользователя или папка по умолчанию.

    Папку создаём при каждом обращении: её могли удалить или переименовать
    между запусками, а падать из-за этого приложение не должно.
    """
    saved = read_settings()["download_dir"]
    path = saved if saved else default_download_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = default_download_dir()
        os.makedirs(path, exist_ok=True)
    return path
```

**2.2.** Заменить `DOWNLOAD_DIR` на `current_download_dir()` во всех местах: `cleanup_job_files`, `download_worker` (проверка места и `outtmpl`), `get_file`, `open_folder`, `index`. Глобального имени `DOWNLOAD_DIR` в `app.py` остаться не должно — проверить поиском.

**2.3.** Известные каталоги и безопасный поиск файла:

```python
def known_dirs():
    """Текущая папка загрузок плюс те, где лежат файлы из журнала.

    После смены папки старые файлы никуда не делись — ссылка на них и
    «показать в папке» обязаны продолжать работать.
    """
```
- начать со списка `[current_download_dir()]`;
- добавить `item["dir"]` из `read_history()` — только существующие каталоги, без повторов (сравнение через `os.path.normcase(os.path.abspath(...))`).

```python
def resolve_download_file(filename):
    """Путь к файлу по имени или None.

    Имя всегда сводится к basename: `<path:filename>` в маршруте пропускает
    сегменты вида ../, и без basename можно уйти за пределы папки загрузок.
    """
    safe_name = os.path.basename(filename)
    for directory in known_dirs():
        candidate = os.path.join(directory, safe_name)
        if os.path.isfile(candidate):
            return candidate
    return None
```

**2.4.** `get_file` и `open_folder` перевести на `resolve_download_file()`. В `get_file` вместо `send_from_directory(DOWNLOAD_DIR, ...)` — `send_from_directory(os.path.dirname(path), os.path.basename(path), as_attachment=True)`. Логика 404 та же.

**2.5.** Новый роут:

```python
@app.route("/api/download-dir", methods=["POST"])
def set_download_dir():
```
Порядок проверок — ровно такой, каждая со своим текстом по-русски:
1. активная задача (`status` из `("starting", "downloading", "cancelling")` хоть у одной записи в `jobs` под `jobs_lock`) → **409**, `{"error": "Идёт загрузка — смените папку после её окончания."}`;
2. `path = (data.get("path") or "").strip()`; пусто → **400**, `{"error": "Укажите папку для загрузок."}`;
3. `not os.path.isabs(path)` → **400**, `{"error": "Нужен полный путь к папке, например D:\\Видео."}`;
4. `os.path.exists(path) and not os.path.isdir(path)` → **400**, `{"error": "По этому пути лежит файл, а не папка."}`;
5. `os.makedirs(path, exist_ok=True)` в `try`; `OSError` → **400**, `{"error": "Не удалось создать папку — проверьте путь и права.", "error_detail": f"{type(e).__name__}: {e}"}`;
6. проверка записи: создать в папке файл `.vd_write_test`, записать байт, удалить; `OSError` → **400**, `{"error": "В эту папку нельзя писать — выберите другую."}`;
7. успех: `write_settings(download_dir=path)`, ответ `{"download_dir": path}`.

**2.6.** Диалог выбора папки — по образцу `shutdown_callback`. Рядом с ним:

```python
# Сюда desktop.py кладёт функцию показа системного диалога выбора папки:
# сам Flask окна не имеет, а тянуть webview в app.py нельзя — из
# исходников в браузере его может не быть вовсе.
folder_dialog_callback = None
```

```python
@app.route("/api/browse-folder", methods=["POST"])
def browse_folder():
```
- `folder_dialog_callback is None` → **409**, `{"error": "Выбор папки доступен только в приложении. Впишите путь вручную."}`;
- иначе вызвать колбэк (в `try`), получить путь или `None`;
- `None`/пусто → `{"cancelled": True}`;
- иначе вернуть `{"path": <путь>}` — **саму настройку здесь не сохранять**, фронт отправит путь в `/api/download-dir` и пройдёт все проверки оттуда;
- исключение → **500**, `{"error": "Не удалось открыть диалог выбора папки.", "error_detail": ...}`.

### Что менять — `desktop.py`

**2.7.** После `service.shutdown_callback = window.destroy` добавить:

```python
    # Диалог просит pywebview, а зовут его из потока Flask — окно у нас одно.
    service.folder_dialog_callback = lambda: (
        (window.create_file_dialog(webview.FOLDER_DIALOG) or [None])[0]
    )
```

### Что менять — `tests/smoke_test.py`

**2.8.** Заменить все обращения `svc.DOWNLOAD_DIR` на `svc.current_download_dir()`.

**2.9.** Проверку «из исходников качаем в downloads рядом с app.py» переписать на `svc.default_download_dir() == os.path.join(svc.BASE_DIR, "downloads")` — она про умолчание, а не про текущий выбор.

### Допущения, которые надо проверить запуском

```
ДОПУЩЕНИЕ 1: window.create_file_dialog можно звать из потока Flask, а не только
  из главного потока pywebview.
  Проверить: start-desktop.bat → Настройки → «Обзор». Диалог должен открыться,
             окно не должно зависнуть.
  Если зависает или ничего не происходит: не изобретать обходной путь самому —
  остановиться и сообщить. Вариант решения (принимает проектировщик):
  прокинуть вызов через window.evaluate_js/очередь в главный поток.
```

### Проверка
В `tests/smoke_test.py` новый блок «папка загрузок»:
- временный каталог внутри текущей папки загрузок (`zzqa_dir_probe`), `POST /api/download-dir` c ним → 200 и `current_download_dir()` равен ему;
- скачивание в новую папку работает (прогнать `run_job` на `/small.mp4`, файл лежит именно там);
- **файл из прежней папки всё ещё отдаётся**: `GET /api/file/<старое имя>` → 200 (это главный смысл `known_dirs()`; для проверки положить запись в журнал через `history_add` из этапа 3 либо, если этап 3 ещё не сделан, — временно проверять `resolve_download_file` напрямую);
- относительный путь → 400, путь на существующий файл → 400, пустой → 400;
- смена папки при активной задаче → 409 (поставить в `jobs` фиктивную запись со `status="downloading"`, после проверки убрать);
- `POST /api/browse-folder` при `folder_dialog_callback = None` → 409;
- он же с подставным колбэком, возвращающим путь, → 200 и `{"path": ...}`;
- после блока вернуть настройку обратно (`write_settings(download_dir=None)`) и удалить временный каталог.

Проверка «уборка: записи убираются, файлы остаются» должна остаться зелёной.

### Чего НЕ делать
- Не переносить и не копировать уже скачанные файлы при смене папки. Пользователь этого не просил, а перекладывание чужих гигабайтов — самое опасное, что тут можно сделать.
- Не сохранять путь из `/api/browse-folder` мимо проверок `/api/download-dir`.
- Не импортировать `webview` в `app.py`.
- Не давать `send_from_directory` каталог, полученный из запроса, — только тот, что вернул `resolve_download_file`.

---

## Этап 3. Журнал загрузок и роуты истории

### Задача
Появляется список загрузок: активная, отменённая и всё, что лежит в папке. Строку можно удалить вместе с файлом.

### Что менять — `app.py`

**3.1.** Поля задачи. В `/api/download` при создании записи в `jobs` добавить `"url": url` и `"height": height`, а также `"current_name": None`. В `hook`, в ветке `d["status"] == "downloading"`, дописать в `job`:

```python
"current_name": os.path.basename(d.get("filename") or "") or None,
```

В `public_job()` добавить `"url"`, `"height"`, `"current_name"`, `"error_kind"`.

**3.2.** Вид ошибки. `humanize_error()` возвращает **кортеж `(text, kind)`**. Виды: `"not_found"` (404), `"forbidden"` (403), `"unsupported"` (Unsupported URL), `"drm"`, `"no_formats"`, `"generic"`. Тексты остаются ровно те же, что сейчас — переписывать формулировки нельзя.

В `download_worker`:
- в ветке `DownloadError`: `error, kind = humanize_error(...)`, в `finish_job` добавить `error_kind=kind`;
- отказ по месту на диске → `error_kind="disk"`;
- превышение лимита размера → `error_kind="too_big"`;
- «yt-dlp не сохранил файл» и неожиданное исключение → `error_kind="generic"`.

В создании job добавить ключ `"error_kind": None`.

**3.3.** Журнал:

```python
def read_history():
    """Записи журнала. Испорченный файл — то же, что пустой журнал."""
```
- вернуть список из ключа `items`; при любой ошибке или неверном типе — `[]`.

```python
def write_history(items):
```
- писать `{"items": items[:HISTORY_LIMIT]}`, каталог создавать, `OSError` — `print`, не падать.

```python
def history_add(record):
    """Кладёт запись первой, вытесняя прежнюю запись про тот же файл."""
```

```python
def history_forget(filename):
    """Убирает запись о файле. Файл на диске не трогает."""
```

В `download_worker`, в успешной ветке (рядом с `finish_job(... status="finished" ...)`), добавить запись:

```python
history_add({
    "filename": os.path.basename(filename),
    "dir": os.path.dirname(filename),
    "title": info.get("title") or os.path.basename(filename),
    "height": height,
    "url": url,
    "size": os.path.getsize(filename),
    "finished_at": time.time(),
})
```

**3.4.** Вспомогательные функции для списка:

```python
def display_name(filename):
    """Имя файла без служебного префикса задачи (32 hex и подчёркивание)."""
```
Регулярка `^[0-9a-f]{32}_` — если после среза пусто, вернуть исходное имя.

```python
def human_when(timestamp):
    """'сегодня' / 'вчера' / '03.02.2026' — по местной дате."""
```
Считать по `datetime.date`, а не вычитанием суток: «вчера в 23:50» и «сегодня в 00:10» разделяет дата, а не 24 часа. Понадобится `import datetime` в начале файла.

**3.5.** Роут списка:

```python
@app.route("/api/history")
def history():
```
Собрать `{"items": [...]}`, где каждый элемент — словарь с полем `kind`:

- `kind="active"` — задачи в статусах `starting`/`downloading`/`cancelling`. Поля: `job_id`, `title` (`current_name` → `display_name`, иначе «Загрузка…»), `progress`, `speed`.
- `kind="cancelled"` — задачи в статусе `cancelled`. Поля: `job_id`, `title` (`display_name(current_name)` или «Загрузка остановлена»), `url`, `height`.
- `kind="done"` — файлы. Собираются так:
  1. пройти по всем каталогам из `known_dirs()`;
  2. взять обычные файлы (`os.path.isfile`), пропустить имена, начинающиеся с точки, и расширения `.part`, `.ytdl`, `.tmp`, `.json`;
  3. **пропустить обрывки текущих задач**: имя начинается с `<job_id>_` любой незавершённой задачи;
  4. по каждому файлу собрать: `filename`, `title` (из журнала, иначе `display_name`), `height` (из журнала, иначе `None`), `size`, `size_text` (`human_size`), `finished_at` (из журнала, иначе `os.path.getmtime`), `when` (`human_when`), `url` (из журнала, иначе `None`);
  5. дубликаты по имени файла не плодить (первое вхождение выигрывает);
  6. отсортировать по `finished_at` по убыванию.

Порядок в ответе: сначала `active`, затем `cancelled`, затем `done`.

Задачи в статусе `error` в список **не попадают** — ошибка видна на экране «Скачать».

**3.6.** Роут удаления:

```python
@app.route("/api/history/delete/<path:filename>", methods=["POST"])
def history_delete(filename):
    """Удаляет скачанный файл по явной команде пользователя.

    Единственное место в проекте, где файл пользователя удаляется намеренно:
    всё остальное (уборщик, TTL) чистит только записи в памяти.
    """
```
- `path = resolve_download_file(filename)`; `None` → 404 `{"error": "Файл не найден"}`;
- `os.remove(path)` в `try`; `OSError` → 409 `{"error": "Не удалось удалить файл — возможно, он открыт в другой программе.", "error_detail": f"{type(e).__name__}: {e}"}`;
- `history_forget(os.path.basename(path))`;
- ответ `{"ok": True}`.

### Проверка
Новый блок в `tests/smoke_test.py` — «история». Все временные файлы кладутся с префиксом `zzqa_` и убираются через `created_files`:
- после успешной загрузки через `run_job` в `/api/history` есть запись `kind="done"` с этим именем файла;
- у неё непустые `title`, `size_text`, `when`;
- запись журнала подставляет качество: после загрузки с `quality=480` у элемента `height == 480`;
- файл без записи в журнале (положить руками `zzqa_orphan.mp4`) виден в списке, `title` = имя файла;
- `display_name("0123456789abcdef0123456789abcdef_Кино.mp4") == "Кино.mp4"`;
- `display_name("Кино.mp4") == "Кино.mp4"`;
- обрывок активной задачи не показан: положить в `jobs` запись со `status="downloading"` и `job_id="zzqahist"`, рядом файл `zzqahist_part.mp4` → его нет среди `done`, зато есть строка `kind="active"`;
- `human_when(time.time()) == "сегодня"`, `human_when(time.time() - 86400) == "вчера"`;
- **удаление**: рядом лежат `zzqa_victim.mp4` и `zzqa_bystander.mp4`; `POST /api/history/delete/zzqa_victim.mp4` → 200, первого файла нет, **второй цел и байт в байт тот же**;
- удаление несуществующего → 404;
- удаление с именем `../app.py` → 404 **и `app.py` на месте** (проверка на выход за пределы папки);
- `error_kind` доезжает наружу: заведомо мёртвая ссылка `{base}/film/404/` → `state["error_kind"] == "not_found"`; при задранном `MIN_FREE_DISK_BYTES` → `"disk"`.

Отдельно: существующая проверка «СКАЧАННЫЙ ФАЙЛ ОСТАЛСЯ НА ДИСКЕ» после уборки — обязана остаться зелёной.

### Чего НЕ делать
- Не удалять ничего из папки загрузок нигде, кроме роута `/api/history/delete` и существующей `cleanup_job_files`.
- Не удалять файл при «Повторить» и при отмене чужой задачи.
- Не хранить в журнале пути к файлам, которых не создавали.
- Не менять тексты в `humanize_error` — меняется только тип возвращаемого значения.

---

## Этап 4. Интерфейс: оболочка и экран «Скачать»

**Это первый визуальный этап. По его завершении — остановиться и показать пользователю.**

### Задача
`templates/index.html` переписывается целиком: тёмная тема, сайдбар с тремя пунктами, экран «Скачать» во всех состояниях макета. Экраны «История» и «Настройки» на этом этапе — заголовок и пустой контейнер.

### Что менять — `templates/index.html`

Файл создаётся заново (`Write`), старая разметка не сохраняется. Структура — раздел 8.2, цвета — раздел 7.

**4.1. Каркас.**
- `body[data-desktop="{{ 'true' if desktop_mode else 'false' }}"]`, фон `--bg-content`, `margin:0`.
- `.window`: `display:flex`. В браузере (`body[data-desktop="false"]`) — `max-width:660px; height:600px; margin:24px auto; border-radius:10px; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,.18)`. В приложении (`body[data-desktop="true"]`) — `width:100vw; height:100vh; margin:0; border-radius:0; box-shadow:none`.
- `.rail`: ширина 60px, фон `--bg-rail`, `padding:18px 0`, `gap:22px`, колонка по центру.
- `.navitem`: кнопка без рамки и фона, колонка, `gap:4px`, `cursor:pointer`. Внутри `.navpill` 36×36, радиус 10px; внутри неё `.navdot` 8×8 круг цвета `--text-faintest`; подпись 9px цвета `--text-dim`. У `.navitem.active`: `.navpill` — фон `--accent-soft`, `.navdot` — `--accent`, подпись — `--text`.
- `.content`: `flex:1; padding:26px; overflow-y:auto`, фон `--bg-content`. Скроллбар тонкий: `scrollbar-width:thin` плюс `::-webkit-scrollbar{width:8px}` с ползунком `--surface`.
- `.screen{display:none}` / `.screen.active{display:block}`.

**4.2. Экран «Скачать» — состояния.** Один и тот же DOM, переключаются классы:

| Состояние | Видно | Скрыто |
|---|---|---|
| `idle` | `#dropZone` (только если поле пустое), `#btn` (disabled при пустом поле), `#quality` активен, `#footHint` = «Поддерживаются сайты, где работает yt-dlp.» | `#stopBtn`, `#progressWrap`, `#status` пуст |
| `downloading` | `#stopBtn`, `#progressWrap`, `#url` readonly, `#quality` disabled, `#footHint` = «Можно остановить в любой момент — файл не сохранится.» | `#dropZone`, `#btn` |
| `error` | блок ошибки в `#status`, рамка `#url` — `--danger`, `#btn` активна | `#progressWrap`, `#stopBtn` |
| `finished` | блок успеха в `#status` | `#progressWrap`, `#stopBtn` |

**4.3. Дропзона** `#dropZone`: `border:1.5px dashed var(--accent-line); border-radius:var(--r-drop); padding:26px 16px; text-align:center; background:var(--accent-ghost); margin-bottom:14px`. Первая строка 13px `--text` «Вставьте ссылку или перетащите её сюда», вторая 11px `--text-dim` «YouTube, VK, Twitch и другие».

Поведение: клик — фокус в `#url`; `dragover`/`dragleave` — подсветка (рамка `--accent`); `drop` — взять `e.dataTransfer.getData('text')`, положить в `#url`, обновить состояние кнопки, **загрузку не запускать**. Плюс `paste` на `document`: если фокус не в поле — вставить текст в `#url`. Обязательно `e.preventDefault()` на `dragover` и `drop`.

**4.4. Строка ввода.** `#url` — `flex:1`, фон `--surface`, рамка `--border-strong`, радиус `--r-field`, `padding:10px 12px`, 13px, текст `--text`, `placeholder="https://..."`. Кнопка `#btn`: фон `--accent`, текст `--accent-ink`, `font-weight:700`, 13px, `padding:10px 18px`, радиус `--r-field`. В `:disabled` — фон `--disabled-bg`, текст `--disabled-text`, `cursor:not-allowed`. `#btn` изначально disabled; слушатель `input` на `#url` включает её, когда поле непустое.

Кнопка `#stopBtn`: прозрачный фон, рамка `1px solid var(--danger)`, текст `--danger`, `font-weight:600`.

**4.5. Прогресс.** `.progress-head` — flex со `space-between`, 11px: слева `#progressName` цвета `--text-dim`, справа `#progressStat` цвета `--accent`, текст вида `63% · 4.2 МБ/с`. `#progressBar` — высота 8px, радиус 5px, фон `--surface`, `overflow:hidden`; `#progressFill` — фон `--accent`, `box-shadow:0 0 8px rgba(61,220,132,.6)`, `transition:width .2s ease`. Пока процент неизвестен — `#progressStat` показывает только скорость, полоса остаётся на нуле.

Имя файла берётся из `current_name` ответа `/api/progress`; пока его нет — «Загрузка…».

**4.6. Блок ошибки** (строится в JS, как сейчас, через `createElement` — никакого `innerHTML` с текстом ошибки): фон `--danger-bg`, рамка `1px solid var(--danger-line)`, радиус `--r-card`, `padding:10px 12px`. Заголовок 13px `--danger` `font-weight:600` — текст из `error`. Ниже `<details><summary>Подробности</summary>` 11px `--text-dim`, внутри блок с `error_detail`: фон `--surface`, радиус 8px, `Consolas, Menlo, monospace` 11px, `white-space:pre-wrap`, `word-break:break-word`.

Если `error_kind === "disk"` — блок жёлтый: фон `--warn-bg`, рамка `--warn-line`, заголовок `--warn`. Остальные виды — красный.

**4.7. Блок успеха** (расхождение №4 из раздела 3): фон `--ok-bg`, рамка `1px solid var(--ok-line)`, радиус `--r-card`. Текст «Готово: <title>» 13px `--text`. Действие — ссылка/кнопка цвета `--accent`, `font-weight:600`:
- `desktopMode === true` → «Показать в папке», по клику `POST /api/open-folder/<filename>`;
- иначе `<a href="/api/file/<filename>">Скачать файл</a>`.

Разделение обязательное: в WebView2 прямая ссылка на файл молча не работает.

**4.8. Баннеры.** `#ffmpegBanner` рисуется через Jinja `{% if not ffmpeg_available %}`: фон `--warn-bg`, рамка `--warn-line`, текст `--warn` 12px, радиус `--r-card`, `padding:10px 12px`. Текст: «ffmpeg не найден — качество ограничено 720p. Положите ffmpeg.exe в папку bin рядом с app.py.»

`#updateBanner` — фон `rgba(61,220,132,.1)`, рамка `--accent-line`, внутри `.banner-row` (`space-between`): `#updateText` 12px `--text` и `#updateBtn` (фон `--accent`, текст `--accent-ink`, 12px, `font-weight:600`, радиус 8px). Ниже `#updateNote` 11px `--text-dim`.

Оба баннера идут над строкой ввода, друг под другом, `gap:10px`.

**4.9. JS.** Переносится существующий из старого шаблона **без изменения логики**: `formatSpeed`, `pollProgress` (интервал 500 мс), `startDownload`, `stopDownload`, `renderUpdate`, `checkUpdate`, `watchUpdate`, обработчик `change` на `#quality`. Добавляется:
- `showScreen(name)` — переключение `.screen.active` и `.navitem.active`, запоминает `currentScreen`;
- `setFormState(state)` — из таблицы 4.2;
- обработчики дропзоны и `paste`;
- в `renderUpdate` — ветка `state === "disabled"`: баннер скрыт (ведёт себя как `up_to_date`).

Заголовки экранов «История» и «Настройки» на этом этапе рисуются, содержимое — пустые `div` c `id="historyList"`, `id="historyEmpty"`, и контейнер настроек. Их наполнение — этапы 5 и 6.

### Проверка
- Существующие проверки страницы (`id="updateBanner"`, `<option value="1080" selected>`, версия) — зелёные.
- Новые:
  - на странице есть `id="screen-download"`, `id="screen-history"`, `id="screen-settings"`;
  - есть `data-screen="history"` и `data-screen="settings"`;
  - есть `id="dropZone"` и `id="progressFill"`;
  - соответствие баннера ffmpeg реальности: `('id="ffmpegBanner"' in page) == (not svc.ffmpeg_available())`;
  - в браузерном режиме на странице есть `href="/api/file/` **или** ветка `desktopMode` — проверять наличие строки `desktopMode` в скрипте (страница одна на оба режима).
- **Открыть в браузере**: `python app.py`, зайти на `http://127.0.0.1:5000/`, свериться с макетом `2a`: сайдбар слева, тёмный фон, дропзона, неактивная кнопка «Скачать». Покликать: ввод ссылки включает кнопку, переключение экранов работает, реальная загрузка показывает прогресс и завершение. После проверки **сервер погасить** — иначе следующий запуск отдаст устаревшую страницу.

### Чего НЕ делать
- Не менять `app.py` на этом этапе (кроме списка переменных шаблона, если чего-то не хватает).
- Не подключать шрифты, иконочные наборы и библиотеки — ни одной внешней ссылки в шаблоне.
- Не заменять `<select>` качества на кастомный дропдаун.
- Не переносить выбор качества или тему в `localStorage` — окно работает в приватном профиле с новым портом при каждом запуске, хранилище всегда пустое.
- Не собирать HTML ошибки строкой: текст ошибки приходит снаружи и вставляется через `textContent`.

---

## Этап 5. Экран «История»

**Визуальный этап. По завершении — остановиться и показать пользователю.**

### Задача
Экран показывает активную загрузку, отменённую с кнопкой «Повторить» и все скачанные файлы с кнопками «Папка» и «×».

### Что менять — `templates/index.html`

**5.1. Строка списка** `.hrow`: фон `--surface`, рамка `1px solid var(--border)`, радиус `--r-card`, `padding:8px 10px`, `display:flex; align-items:center; gap:10px`.

Внутри:
- `.thumb` — 56×36, радиус 6px, `flex:none`, фон `repeating-linear-gradient(45deg, rgba(61,220,132,.1), rgba(61,220,132,.1) 6px, #1B1F23 6px, #1B1F23 12px)`;
- `.hmain` — `flex:1; min-width:0`; название 12px `--text` с `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`; под ним либо метаданные 10px `--text-faint`, либо тонкая полоса прогресса;
- действия справа: 11px, `font-weight:600`, `cursor:pointer`.

**5.2. Три вида строк.**

*Активная*: превью с более ярким паттерном (`rgba(61,220,132,.15)`), под названием полоса высотой 5px, радиус 3px, фон `--surface-sunk`, заполнение `--info` (синий — отличает очередь от основного действия). Справа процент 10px `--text-dim` и «Стоп» цвета `--danger` → `POST /api/cancel/<job_id>`.

*Отменённая*: вся строка `opacity:.6`, вместо метаданных — «Остановлено пользователем» 10px `--text-faint`, справа «Повторить» цвета `--accent` → `POST /api/download` с `url` и `quality` из этой же записи, затем переход на экран «Скачать» и обычный опрос прогресса.

*Готовая*: метаданные строкой `720p · 61 МБ · сегодня` (если качество неизвестно — `61 МБ · сегодня`), справа «Папка» цвета `--accent` → `POST /api/open-folder/<filename>` и «×» 13px `--text-faint`.

**5.3. Удаление по «×» — в два шага, без `window.confirm`.** Первый клик заменяет правую часть строки на «Удалить файл? **Да** / Отмена»: «Да» цвета `--danger`, «Отмена» цвета `--text-dim`. «Да» → `POST /api/history/delete/<filename>`, при успехе строка убирается из списка; при 409 — под строкой показывается текст ошибки из ответа. «Отмена» возвращает обычный вид. Пятисекундного авто-отката не нужно.

Формулировка обязана быть честной: файл действительно удаляется с диска.

**5.4. Пустое состояние** `#historyEmpty` — по центру области: квадрат 44×44, радиус 12px, рамка `2px solid #2A2F33`, внутри круг 14×14 цвета `#2A2F33`; ниже «Пока ничего не скачано» 13px `--text`; ниже «Ваши загрузки появятся здесь» 11px `--text-faint`. Показывается, когда `items` пуст.

**5.5. Загрузка данных.** `loadHistory()` — `GET /api/history`, перерисовка списка. Вызывается:
- при переходе на экран «История»;
- по таймеру раз в 1000 мс, **только пока экран «История» открыт**; таймер гасится при уходе с экрана (`clearInterval`, переменная `historyTimer`);
- один раз после завершения загрузки (`status === "finished"` в `pollProgress`), чтобы список был свежим, когда пользователь туда зайдёт.

Ошибка запроса — не пустой экран: в списке остаётся прежнее содержимое, в консоль ничего не пишем, пользователю показываем строку «Не удалось получить список загрузок» 11px `--text-dim`.

Все строки собираются через `createElement`/`textContent` — имена файлов приходят с диска и в разметку строкой не склеиваются.

### Проверка
Проверки бэкенда уже написаны на этапе 3. Здесь — только страница:
- на странице есть `id="historyList"` и `id="historyEmpty"`;
- **в браузере**: скачать что-нибудь маленькое, зайти на «Историю» — строка появилась с размером и датой; «Папка» открывает проводник; «×» спрашивает подтверждение, «Отмена» возвращает строку, «Да» убирает строку и файл; во время загрузки на экране «История» видна активная строка с процентом, «Стоп» её отменяет, появляется «Повторить», и она действительно перезапускает загрузку.
- Сервер после проверки погасить.

### Чего НЕ делать
- Не добавлять поиск, фильтры, сортировку и группировку по датам — в финальном макете `2a` их нет (поле поиска есть только в черновике `1b`).
- Не удалять файл без подтверждения.
- Не показывать в истории задачи со статусом `error`.
- Не опрашивать `/api/history` постоянно — только при открытом экране.

---

## Этап 6. Экран «Настройки»

**Визуальный этап. По завершении — остановиться и показать пользователю.**

### Задача
Качество по умолчанию пилюлями, папка загрузок с кнопкой «Обзор», переключатель автообновления, подпись с ffmpeg и версией.

### Что менять — `templates/index.html`

**6.1. Качество.** Заголовок поля 11px `--text-dim` «Качество по умолчанию». Пилюли — разметка из раздела 8.3, `display:flex; gap:6px`. Активная: фон `--accent-soft`, текст `--accent`, рамка `1px solid rgba(61,220,132,.4)`, `font-weight:600`. Неактивная: фон `--surface`, рамка `1px solid rgba(255,255,255,.08)`, текст `--text-dim`. Обе — `padding:8px 14px`, радиус 8px, 12px.

Клик по пилюле → `POST /api/quality` со значением `data-height` → одна общая функция `applyQuality(height)`, которая переставляет `.active` **и** синхронизирует `#quality` на экране «Скачать». Обратно: `change` на `#quality` тоже зовёт `applyQuality`. Два места, одно состояние — рассинхрона быть не должно.

**6.2. Папка загрузок.** Заголовок 11px `--text-dim`. Строка: `#dirPath` (`flex:1`, стиль поля, 12px, значение `{{ download_dir }}`) и `#browseBtn` «Обзор» (фон `--surface`, рамка `1px solid rgba(255,255,255,.15)`, текст `--text`, 12px).

- В приложении (`desktop_mode`): `#dirPath` — `readonly`; «Обзор» → `POST /api/browse-folder` → полученный путь отправить в `POST /api/download-dir` → при успехе обновить значение поля.
- В браузере: `#browseBtn` скрыта, `#dirPath` редактируемое; сохранение по `Enter` и по `blur` → `POST /api/download-dir`.
- Ошибка (400/409) — текст из `error` в `#dirNote` цвета `--danger` 11px; успех — `#dirNote` очищается. Значение поля при ошибке возвращается к прежнему пути.

**6.3. Автообновление.** Строка `space-between`: слева «Автообновление» 12px `--text`, справа `#autoUpdateToggle` — `button.toggle` 36×20, радиус 12px, внутри кружок 16×16 радиус 50%. Включено: фон `--accent`, кружок `--accent-ink` справа (`right:2px`). Выключено: фон `--disabled-bg`, кружок `--text-faint` слева (`left:2px`). Начальное состояние — из `{{ auto_update }}`. Клик → `POST /api/auto-update {"enabled": <новое>}`, вид меняется по ответу сервера, а не по клику.

Атрибут `aria-pressed` ставить по состоянию — это единственная разметочная зацепка для проверки.

**6.4. Подпись низом.** `border-top:1px solid rgba(255,255,255,.08); padding-top:12px`, 11px `--text-faint`: «ffmpeg найден. Версия {{ app_version }}.» либо «ffmpeg не найден. Версия {{ app_version }}.» — по `ffmpeg_available`. Если `max_filesize` задан, добавить предложением «Лимит на файл — {{ max_filesize }}.»

**6.5. Строку «Тёмная тема» не рисовать** — решение пользователя, тема одна.

### Проверка
- На странице есть `class="pill active" data-height="720"` при умолчании (в блоке с подменённым `SETTINGS_PATH` — после `POST /api/quality {"quality": 1080}` активной становится пилюля 1080: `class="pill active" data-height="1080"`);
- одновременно `<option value="1080" selected>` — селект и пилюли показывают одно и то же;
- на странице есть `id="autoUpdateToggle"` и `id="dirPath"`;
- значение `#dirPath` совпадает с `current_download_dir()`;
- при `write_settings(auto_update=False)` страница отдаёт тумблер с `aria-pressed="false"`.
- **В браузере**: переключить качество пилюлей → вернуться на «Скачать», селект показывает то же; вписать в поле папки несуществующий относительный путь → под полем красная понятная ошибка; вписать нормальный путь → сохранилось; выключить автообновление → баннер обновления не появляется.
- Сервер погасить.

### Чего НЕ делать
- Не добавлять настройки, которых нет в макете (лимит размера, TTL, прокси, язык).
- Не менять папку загрузок без обращения к `/api/download-dir` — вся валидация живёт на сервере.
- Не делать переключатель темы.

---

## Этап 7. Окно приложения

### Задача
Размер окна приводится к макету, приложение проверяется в собранном виде.

### Что менять — `desktop.py`

**7.1.**

```python
WINDOW_WIDTH = 660
WINDOW_HEIGHT = 600
WINDOW_MIN_SIZE = (600, 520)
```

Обоснование: в макете окно 640px шириной (сайдбар 60 + контент), рабочая область 480px по высоте; плюс рамка и титлбар Windows и запас на список истории.

**7.2.** Проверку обновлений при старте запускать с оглядкой на настройку:

```python
    if service.read_auto_update():
        updater.start_check_async()
```

### Проверка
- `python -m py_compile desktop.py`;
- `python tests/smoke_test.py` — 0 падений;
- **запустить `start-desktop.bat`** и пройти сценарии, которых проверки не покрывают в принципе:
  - окно открывается, ничего не обрезано, история скроллится;
  - скачать ролик → «Показать в папке» действительно открывает проводник с выделенным файлом (в браузере это работает иначе, здесь — единственная реальная проверка);
  - «Обзор» в настройках открывает системный диалог (допущение 1 из этапа 2);
  - перетаскивание ссылки в окно и `Ctrl+V` (допущение ниже);
  - выпадающий список качества читается на тёмном фоне.

### Допущения, которые надо проверить запуском

```
ДОПУЩЕНИЕ 2: WebView2 отдаёт странице события dragover/drop с текстом ссылки,
  перетащенной из браузера.
  Проверить: start-desktop.bat, перетащить ссылку из Chrome в окно — она должна
             оказаться в поле ввода.
  Если не работает: убрать из дропзоны слова «или перетащите её сюда», оставив
  «Вставьте ссылку» и работающий Ctrl+V. Это правка одной строки текста —
  сделать её и сказать в отчёте, а не выдумывать обходной путь.

ДОПУЩЕНИЕ 3: системный выпадающий список <select> в тёмной теме выглядит
  приемлемо (список рисует Windows, а не страница).
  Проверить: там же, открыть «Качество».
  Если список белый и выбивается: НИЧЕГО не переделывать самому — сказать
  в отчёте, решение примет проектировщик.
```

### Чего НЕ делать
- Не делать окно frameless и не рисовать свой титлбар.
- Не менять `video-downloader.spec` и `installer/video-downloader.iss` — состав дистрибутива не изменился, новых файлов в сборку не добавилось.
- Не запускать `build.bat` (для него нужен `bin\ffmpeg.exe` и Inno Setup, их может не быть).

---

## Этап 8. Документация и финальная сверка

### Что менять — `CLAUDE.md`

**8.1. Правило про файлы** — заменить формулировку в разделе «Правила работы с проектом»:

> **Скачанные файлы удаляются только по явной команде пользователя** — кнопкой «×» в истории (`/api/history/delete`). Всё остальное их не трогает: уборщик `sweep_once` чистит только записи в памяти, `cleanup_job_files` — только обрывки своей сорвавшейся задачи. В `.iss` не должно появиться `[UninstallDelete]`.

**8.2. Раздел «Состав»** — дописать: `history.json` (журнал загрузок), новые роуты, экраны интерфейса.

**8.3. Раздел «Что где настраивается»** — дописать `HISTORY_PATH`, `HISTORY_LIMIT`, `DEFAULT_SETTINGS`, и что `settings.json` теперь хранит три ключа.

**8.4. Раздел «Грабли»** — дописать то, что подтвердится на этапе 7 (перетаскивание в WebView2, диалог выбора папки из потока Flask). Только подтверждённое запуском — догадки в этот раздел не идут.

**8.5. Журнал изменений** — новый пункт: что изменилось для пользователя (три экрана вместо одной карточки, тёмная тема, история загрузок с удалением, выбор папки, выключаемое автообновление) и почему, плюс итог по проверкам («было 87, стало N»).

### Финальная сверка
1. `python -m py_compile app.py desktop.py updater.py app_version.py tests/smoke_test.py`
2. `python tests/smoke_test.py` → код возврата 0, `N/N проверок пройдено`
3. Блок «уборка: записи убираются, файлы остаются» — зелёный
4. `git status --short` — изменены только `app.py`, `templates/index.html`, `desktop.py`, `tests/smoke_test.py`, `CLAUDE.md`, `docs/plan-new-ui.md`. Ничего в `downloads/` не пропало
5. Отчёт: что сделано, что проверено в браузере, что проверено в десктопном режиме, какие допущения подтвердились, что осталось

---

## Сводный список новых проверок

Ориентир — около 40 проверок сверх нынешних 87.

**Настройки (этап 1):** старый формат читается · частичная запись не теряет соседние ключи · испорченный файл даёт умолчания · `auto_update` переключается роутом · при выключенном `/api/update` отдаёт `disabled` · при включённом не отдаёт.

**Папка (этап 2):** смена принимается · загрузка идёт в новую папку · файл из прежней папки продолжает отдаваться · относительный путь отклонён · путь на файл отклонён · пустой путь отклонён · смена во время загрузки — 409 · `browse-folder` без колбэка — 409 · с колбэком — путь.

**История (этап 3):** скачанное появляется в списке · качество из журнала · файл без записи виден по имени · `display_name` срезает префикс и не портит обычные имена · обрывок активной задачи скрыт · активная строка присутствует · `human_when` даёт «сегодня»/«вчера» · удаление убирает файл · **соседний файл цел** · удаление несуществующего — 404 · `../app.py` — 404 и файл на месте · `error_kind` доезжает для 404 и для нехватки места.

**Страница (этапы 4–6):** три секции экранов · пункты навигации · дропзона · полоса прогресса · баннер ffmpeg соответствует наличию ffmpeg · активная пилюля совпадает с выбранным качеством · селект и пилюли согласованы · тумблер отражает настройку · поле папки показывает текущий путь.

Каждую новую проверку обязательно проверить на «краснеет ли»: временно вернуть старое поведение, убедиться, что упала, вернуть правку. Проверка, зелёная в обоих случаях, не защищает ни от чего.

---

## Ловушки

- **Порт 5000.** После проверки в браузере остаётся висеть python-процесс, и следующий запуск отдаёт устаревшую страницу — выглядит как «правка не сработала». Гасить сервер после каждой проверки. Команды разбора — в `CLAUDE.md`, раздел «Грабли».
- **Кеш шаблонов Jinja.** При `debug=False` шаблон читается один раз. `python app.py` идёт с `debug=True`, десктопный запуск — нет: там правка в шаблоне видна только после перезапуска.
- **`svc.DOWNLOAD_DIR` в тестах.** После этапа 2 такого имени нет — забытое обращение падает с `AttributeError`, а не тихо.
- **Смена папки во время загрузки** запрещена намеренно: yt-dlp уже пишет по старому пути, и на середине его не переставить.
- **`os.remove` на файле, открытом в плеере,** на Windows бросает `PermissionError` — это 409 с человеческим текстом, а не 500.
- **`<path:filename>` в маршруте пропускает `../`** — `os.path.basename()` обязателен в каждом роуте, который принимает имя файла: `/api/file`, `/api/open-folder`, `/api/history/delete`.
- **Проверки гоняются только из исходников.** `FROZEN = False`, окна нет, ffmpeg системный. Зелёный прогон не доказывает, что то же работает в exe — отсюда обязательный проход по `start-desktop.bat` на этапе 7.

---

## Замечено попутно (в план работ не входит)

- `00-inbox/` не упомянут в `.gitignore` — архив с макетами (и распакованная папка) попадут в коммит, если их не исключить. Решение за пользователем.
- В `downloads/` лежат файлы с именами вида `._..mp4` и `._._._..mp4` — следы `restrictfilenames` на роликах, где заголовок состоит из символов, которые вычищаются целиком. В новом списке истории они будут выглядеть как строки почти без названия. Чинится подстановкой `%(id)s`, когда заголовок пуст, — отдельная задача.
- Роут `/api/progress/<job_id>` отдаёт 404 после того, как уборщик убрал запись; интерфейс на это реагирует как на ошибку. Сейчас незаметно (TTL 2 часа), но с историей вероятность вырастет.
