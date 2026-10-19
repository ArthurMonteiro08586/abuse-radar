# abuse-radar

Автоматический мониторинг ниши AI free-tier / API-шеринг. Находит сайты с бесплатным доступом к AI по API, собирает карточку проекта (панель/модели/регистрация/капча/бонусы) и алертит в Telegram.

## Источники (v2)

1. **TG-каналы** — публичные `t.me/s/<chan>` preview + Telethon-fallback для JoinChannel-стены (выделенная сессия, файл вне репо). Seed-каналы ниши + atlas-каналы (AI/GPT/LLM/midjourney) + organic discovery из постов (cap 60).
2. **zuiquanapi.com** — каталог 4000+ AI relay-станций (new-api/one-api панели). Парсится каждый ран, новые домены → очередь. Приоритет 1 у станций с free/免费/试用/白嫖 в названии/описании.
3. **GitHub mining** — search API по ключевикам (free ai api, llm api gateway, new-api, chat2api...), README топ-реп → извлечение URL сайтов. Токен в `gh_token` (вне репо), запуск в --full и рандомно в 30% обычных ранов.

## Пробы домена (deep probe)

- `/` → title, meta description, freebie-сигналы (free credits/赠送/试用/welcome bonus), маркеры auth-стека
- `/api/status` → new-api панель: `register_enabled`, `turnstile_check`, `email_verification`, `github_oauth`/`telegram_oauth`/`linuxdo_oauth`, `epay_enabled` (USDT), `quota_for_new_user` (бонус новичку)
- `/api/pricing` → полный прайс панели без auth: кол-во моделей + **free-модели** (model_ratio=0 и model_price=0)
- `/v1/models` (+ фейковый Bearer) → **keyless API** + список моделей
- `/v1/chat/completions` (max_tokens=1) → open chat без ключа
- `/signup|/register|/login` → форма + тип капчи (turnstile/recaptcha/hcaptcha/altcha/captcha.run) + OAuth + known-stack (clerk/supabase/workos/firebase/auth0/nextauth/kinde/stack)
- `/docs|/openapi.json` → документация

## Скоринг

- `+60` keyless /v1/models (API без ключа!)
- `+50` new-api панель, регистрация ОТКРЫТА, без turnstile (авторег без капчи)
- `+40` панель с открытой регой + turnstile (решается сайдкаром) ИЛИ no-captcha signup на сайте
- `+30..40` free-модели в /api/pricing (по количеству)
- `+25` signup с решаемой капчей
- `+15` open chat completions без ключа
- `+12` known auth stack, `+8` GH OAuth / freebie-сигналы, `+5` TG/LinuxDO OAuth, docs, USDT
- `>=30` → finding в БД + TG-карточка (батчи по 3, cap 9 за ран, только новые)

## Очередь и дедуп

sqlite `radar.db`: `queue` (domain, prio, src, done) — TG/github = prio 1-2, zuiquan = prio 1 (free-маркеры) / 2. За ран пробуется 30 доменов (--full: 90), порядок по приоритету. `domains` хранит скор + JSON-инфо; `notified` гарантирует одноразовость алерта.

## Запуск

```bash
python3 radar_scan.py          # обычный ран (30 проб)
python3 radar_scan.py --full   # полный (90 проб, 3 страницы истории, GitHub mining)
```

Python 3.9+, stdlib (+ telethon опционально). Cron: каждые 2 часа → карточки в тред оператора.

## Файлы вне репо (секреты, в .gitignore)

- `tg_token` — токен TG-бота для алертов
- `tg_api_hash` — api_hash для Telethon-fallback
- `gh_token` — GitHub PAT для search API
- `radar.db` — состояние, `*.session` — копия сессии, `*.log`

## Seed-каналы

bozdrop, no_agi_chat, AIUngated, freegptmaster, freegptmaster_ru, free_republic_ai + 22 atlas-канала (chatgptsupremacy, llm_helpers, localllama_ru, omggpt, timenewsai, midjourney_free_* и др.) + органика.
