# abuse-radar

Автоматический мониторинг Telegram-каналов ниши AI free-tier / abuse / API-шеринг.
Находит новые сайты из постов, пробует их на авторег-пригодность и keyless API, скорит и алертит в Telegram.

## Как работает

1. **Источники** — публичные TG-каналы (`t.me/s/<chan>` preview, без сессии).
   Для каналов с JoinChannel-стеной — Telethon-fallback (выделенная сессия, файл вне репо).
2. **Organic discovery** — из постов собираются упоминания других `t.me/` каналов → очередь расширяется сама (cap 40).
3. **Дедуп** — sqlite `radar.db`: сообщения по `(chan, mid)`, домены пробуются один раз.
4. **Пробы домена** (stdlib urllib, Chrome UA):
   - `/` → маркеры auth-стека: clerk, supabase, workos, firebase, auth0, nextauth, kinde, stack, new-api, lobehub
   - `/signup|/register|/login` → наличие формы + тип капчи (turnstile/recaptcha/hcaptcha/altcha/captcha.run)
   - `/api/status` → new-api/one-api панель
   - `/v1/models` (+ с фейковым Bearer) → keyless API
   - `/docs|/openapi.json`
5. **Скоринг**:
   - `+50` keyless API (/v1/models без ключа)
   - `+40` signup БЕЗ капчи (jackpot)
   - `+30` new-api панель
   - `+25` signup + решаемая капча (turnstile/altcha/recaptcha)
   - `+12` known-stack (clerk/supabase/workos/firebase/stack/kinde) или hard-captcha
   - `+8` GitHub OAuth, `+5` docs
   - `>=25` → finding + TG-алерт (top-5 новых за ран)
6. **Алерт** — Bot API sendMessage в DM/тред оператора (токен в `tg_token` или env, вне репо).

## Запуск

```bash
python3 radar_scan.py          # обычный ран (20 доменов-проб)
python3 radar_scan.py --full   # полный (60 доменов, 3 страницы истории)
```

Python 3.9+, только stdlib (+ telethon опционально для JoinChannel-каналов).
Cron: каждые 2 часа.

## Файлы вне репо (секреты)

- `tg_token` — токен TG-бота для алертов
- `tg_api_hash` — api_hash для Telethon-fallback
- `radar.db` — состояние
- `*_radar.session` — копия сессии (dedicated, не из активных пулов)

## Seed-каналы

bozdrop, no_agi_chat, AIUngated, freegptmaster, freegptmaster_ru, free_republic_ai
(+ органическое расширение из постов)
