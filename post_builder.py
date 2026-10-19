# post_builder.py — собирает ДРАФТ поста в стиле @AlStack из свежих целей радара.
# Формат (аппрув Влада 20.10): 🩸 КАПС-ЗАГОЛОВОК, секции 🩸, буллеты [Name](url) — модели, вердикт рега;
# финал «Репост 🔁» + 👻 иишко. Шлёт ДРАФТ в тред Влада (TG_CHAT/TG_THREAD), в канал — только вручную.
# Запуск: python post_builder.py [--force]  (без force — только если >=3 новых целей)
import sys, os, json, re, time, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import radar_scan as rs

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, 'radar.db')

# мусор, который точно не в пост
BLOCKLIST = {'attacker.com', 'skill.md', 'snyk.io', 'arxiv.org', '404media.co', 'news.ycombinator.com',
             'responsible.ai', 'developer.nvidia.com', 'wundernn.io', 'kaggle.com', 'lesswrong.com',
             'u.habr.com', 'm365.cloud.microsoft', 'aisecuritylab.timepad.ru', 'chatbase.co', 'getmaxim.ai',
             'braintrustdata.com', 'keywordsai.co', 'telemetry.dev', 'reportgpt.app', 'krumzi.com',
             'app.usenaive.ai', 'app.promptwise.com', 'app.runbear.io', 'askclair.ai', 'sidebar-ai.com',
             'cdn.jsdelivr.net', 'api-docs.deepseek.com', 'chat.qwen.ai', 'chat.z.ai', 'minimax.io',
             'platform.reflection.ai', 'stoke.money', 'pulseos.finance', 'wonderhop.io', 'mymirrormd.com',
             'genevarender.com', 'firmendaten.researchly.at', 'reducer.xgoose.org', 'rstation.ai',
             'coreproxy.io', 'spyderproxy.com', 'olympecasinowin-fr.com', 'ndroo.github.io',
             'thingstodoapi.com', 'openrouter.ai', 'tokenrhythm.studio'}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36'}
MODEL_RE = re.compile(r'(gpt-[0-9a-z.\-]+|claude-[0-9a-z.\-]+|gemini-[0-9a-z.\-]+|glm-[0-9a-z.\-]+|kimi-[a-z0-9.\-]+|deepseek-[a-z0-9.\-]+|grok-[0-9a-z.\-]+|qwen[0-9a-z.\-]*|llama-[0-9a-z.\-]+|mistral-[a-z0-9.\-]+|nano-banana[a-z0-9.\-]*)', re.I)


def probe_models(dom):
    """models: (count, sample_list, free_list, how)"""
    for path in ('/api/pricing',):
        try:
            s, b, _ = rs.http('https://' + dom + path, timeout=10, headers=UA)
            if s == 200 and b and b.strip().startswith('{'):
                d = json.loads(b)
                data = d.get('data') or []
                ms = [m.get('model_name', '') for m in data if isinstance(m, dict) and m.get('model_name')]
                if ms:
                    free = [m.get('model_name', '') for m in data if isinstance(m, dict)
                            and str(m.get('model_ratio') or '0') in ('0', '0.0', '')]
                    return len(ms), ms[:12], free[:8], 'pricing'
        except Exception:
            pass
    for path in ('/v1/models', '/api/v1/models'):
        try:
            s, b, _ = rs.http('https://' + dom + path, timeout=10, headers=UA)
            if s == 200 and b and 'data' in b:
                d = json.loads(b)
                ids = [m.get('id', '') for m in d.get('data', []) if isinstance(m, dict) and m.get('id')]
                if ids:
                    free = [i for i in ids if ':free' in i or '-free' in i]
                    return len(ids), ids[:12], free[:8], 'keyless'
        except Exception:
            pass
    try:
        s, b, _ = rs.http('https://' + dom, timeout=12, headers=UA)
        found = [x.lower() for x in MODEL_RE.findall((b or '')[:300000])]
        uq = list(dict.fromkeys(found))
        uq = [u for u in uq if len(u) >= 4 and not re.search(r'\.$|\.(webp|png|svg|js|html|md)|compatible|pricing|tutorial|install|vs-|^qwen$|^qwen\.', u)][:12]
        if uq:
            return len(uq), uq, [], 'homepage'
    except Exception:
        pass
    return 0, [], [], ''


GENERIC_TITLES = {'new api', 'one api', 'orbelis', 'home', 'dashboard', 'login', 'sign in', 'welcome'}

def base_dom(dom):
    parts = dom.split('.')
    while parts and parts[0] in ('www', 'app', 'api', 'platform', 'chat', 'newapi', 'console'):
        parts = parts[1:]
    return '.'.join(parts) or dom


def nice_name(dom, title):
    t = (title or '').strip()
    if t and len(t) < 40 and '·' not in t and '|' not in t and t.lower() not in GENERIC_TITLES \
            and not re.search(r'console|sign in|log ?in|overview|status', t, re.I):
        return t
    base = base_dom(dom).split('.')
    return base[0].capitalize() if base else dom


def build(c, force=False):
    c.execute('CREATE TABLE IF NOT EXISTS post_log(domain TEXT PRIMARY KEY, ts INTEGER)')
    logged = set(r[0] for r in c.execute('SELECT domain FROM post_log'))
    rows = c.execute('SELECT domain,score,info FROM domains WHERE score>=30 ORDER BY score DESC LIMIT 120').fetchall()
    panels, keyless, bonus = [], [], []
    seen_base = set()
    for dom, score, ij in rows:
        if dom in logged or dom in BLOCKLIST or any(dom.endswith(x) for x in ('.edu', '.gov')):
            continue
        bd = base_dom(dom)
        if bd in seen_base or bd in logged:
            continue
        seen_base.add(bd)
        try:
            info = json.loads(ij)
        except Exception:
            info = {}
        if info.get('cjk') or (rs.CJK.search(str(info.get('title') or '')) and len(rs.CJK.findall(str(info.get('title')))) >= 3):
            continue
        reg = str(info.get('reg') or '')
        n, sample, free, how = probe_models(dom)
        title = str(info.get('title') or '')
        name = nice_name(dom, title)
        # классификация
        mm = ' — ' + ', '.join(sample[:5]) if sample else ''
        if n and n > len(sample):
            mm = ' (' + str(n) + ' модел' + ('ей' if n >= 5 else ('ь' if n == 1 else 'и')) + ')' + mm
        if free:
            mm += ', free: ' + ', '.join(free[:3])
        line = '- [' + name + '](https://' + dom + ')' + mm
        if info.get('keyless_api') or how == 'keyless':
            keyless.append(line + (', /v1/models открыт без ключа' if how == 'keyless' else ''))
        elif reg.startswith('PANEL') or 'NO-CAPTCHA' in reg or 'solvable' in reg:
            cap = ''
            if 'NO turnstile' in reg or 'NO-CAPTCHA' in reg:
                cap = ', рег БЕЗ капчи'
            elif 'turnstile' in reg:
                cap = ', turnstile (solvable)'
            elif 'recaptcha' in reg:
                cap = ', recaptcha (solvable)'
            if 'GH-oauth' in reg:
                cap += ' +GH OAuth'
            if 'LinuxDO' in reg:
                cap += ' +LinuxDO'
            panels.append(line + cap)
        elif re.search(r'email|mail|gpu|proxy|hosting|infra|memory|compute', dom + ' ' + title, re.I) or info.get('freebie'):
            bonus.append(line)
        else:
            continue
        logged.add(dom)
        time.sleep(0.3)
    total = len(panels) + len(keyless) + len(bonus)
    if total < 3 and not force:
        print('SKIP: only', total, 'fresh targets')
        return 0
    L = ['🩸 **БЕСПЛАТНЫЕ AI-СЕРВИСЫ — УЛОВ РАДАРА: АВТОРЕГ + МОДЕЛИ**', '']
    if panels:
        L += ['🩸 ПАНЕЛИ С ОТКРЫТОЙ РЕГОЙ'] + panels + ['']
    if keyless:
        L += ['🩸 API БЕЗ КЛЮЧА / БЕЗ КАПЧИ'] + keyless + ['']
    if bonus:
        L += ['🩸 БОНУС ДЛЯ ФАРМА'] + bonus + ['']
    L += ['Репост, чтобы больше людей узнало 🔁', '', '👻 [**иишко**](https://t.me/AlStack)']
    txt = '\n'.join(L)
    open(os.path.join(DIR, 'last_draft.md'), 'w', encoding='utf-8').write(txt)
    print('=== DRAFT (' + str(total) + ' targets) ===')
    print(txt)
    if rs.tg_notify('📝 ДРАФТ поста (в канал не кидал, жду «в канал»):\n\n' + txt[:3400]):
        now = int(time.time())
        c.executemany('INSERT OR REPLACE INTO post_log(domain,ts) VALUES(?,?)', [(d, now) for d in logged])
        c.commit()
        print('DRAFT SENT + post_log saved')
    else:
        print('TG SEND FAILED — post_log NOT saved')
    return total


if __name__ == '__main__':
    conn = sqlite3.connect(DB, timeout=40)
    conn.execute('PRAGMA busy_timeout=40000')
    build(conn, force='--force' in sys.argv)
