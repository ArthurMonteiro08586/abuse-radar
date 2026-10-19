# -*- coding: utf-8 -*-
# ABUSE-RADAR v2 (2026-10-19)
# Мониторинг ниши AI free-tier/API: TG-каналы + zuiquanapi-каталог (4000+ relay-станций) + GitHub mining.
# Глубокие пробы: keyless API + модели, new-api панели (/api/status: register_enabled/turnstile/epay),
# /api/pricing (free-модели ratio=0), signup-стек/капча, free-credit сигналы. TG-карточки в тред.
# Stdlib-only. State: sqlite radar.db. Запуск: python3 radar_scan.py [--full]
import sys, os, re, json, time, sqlite3, html as htmlmod, random
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import urllib.request, urllib.parse, ssl

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'}
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, 'radar.db')
SEEDS = ['bozdrop', 'no_agi_chat', 'AIUngated', 'freegptmaster', 'freegptmaster_ru', 'free_republic_ai']
MAX_CHANS = 60
TG_TOKEN_FILE = os.path.join(DIR, 'tg_token')
TG_ENV = r'C:\Users\User\AppData\Local\hermes\.env'
TG_CHAT = '7448683285'; TG_THREAD = 455324
TELETHON_CHANS = {'bozdrop': r'C:\Users\User\AppData\Local\hermes\cache\scratch\bozprobe_32_1_7068444489.session',
                  'no_agi_chat': r'C:\Users\User\AppData\Local\hermes\cache\scratch\bozprobe_32_1_7068444489.session'}
TG_API_ID = 2040
TG_API_HASH_FILE = os.path.join(DIR, 'tg_api_hash')
GH_TOKEN_FILE = os.path.join(DIR, 'gh_token')
PROBE_CAP = 30           # доменов-проб за ран (--full: x3)

SKIP_DOMAINS = ('t.me', 'telegram.me', 'telegram.org', 'github.com', 'githubusercontent.com', 'githubassets.com',
                'youtube.com', 'youtu.be', 'twitter.com', 'x.com', 'discord.gg', 'discord.com',
                'google.com', 'googleapis.com', 'gstatic.com', 'play.google.com', 'apps.apple.com',
                'wikipedia.org', 'reddit.com', 'medium.com', 'telegra.ph', 'linkedin.com', 'instagram.com',
                'facebook.com', 'tiktok.com', 'patreon.com', 'boosty.to', 'donationalerts.com', 'twitch.tv',
                'vk.com', 'whatsapp.com', 'cloudflare.com', 'openai.com', 'anthropic.com', 'deepseek.com',
                'schema.org', 'w3.org', 'sentry.io', 'stripe.com', 'posthog.com', 'gravatar.com',
                'apple.com', 'microsoft.com', 'windows.net', 'amazonaws.com', 'vercel.app', 'netlify.app',
                'gitbook.io', 'notion.so', 'baidu.com')

def db():
    c = sqlite3.connect(DB, timeout=60)
    c.execute('PRAGMA busy_timeout=60000')
    c.execute('''CREATE TABLE IF NOT EXISTS messages(chan TEXT, mid INT, date TEXT, text TEXT, PRIMARY KEY(chan,mid))''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels(name TEXT PRIMARY KEY, source TEXT, added INT, last_scan INT, ok INT DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS domains(domain TEXT PRIMARY KEY, first_seen INT, last_probe INT, score INT DEFAULT 0, info TEXT, notified INT DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS findings(ts INT, domain TEXT, score INT, info TEXT, src_chan TEXT, src_mid INT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS queue(domain TEXT PRIMARY KEY, prio INT, src TEXT, added INT, done INT DEFAULT 0)''')
    return c

def http(url, timeout=15, data=None, headers=None):
    h = dict(UA)
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        body = r.read(400000).decode('utf-8', 'replace')
        return r.status, body, r.geturl()
    except urllib.error.HTTPError as e:
        try: body = e.read(200000).decode('utf-8', 'replace')
        except Exception: body = ''
        return e.code, body, url
    except Exception as e:
        return 0, str(e)[:120], url

def enqueue(c, dom, prio, src):
    dom = (dom or '').strip().lower()
    if not dom or dom in SKIP_DOMAINS or any(dom.endswith('.' + s) for s in SKIP_DOMAINS): return False
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', dom): return False
    if len(dom) > 90 or not re.match(r'^[a-z0-9.-]+$', dom): return False
    if c.execute('SELECT domain FROM domains WHERE domain=?', (dom,)).fetchone(): return False
    c.execute('INSERT OR IGNORE INTO queue(domain,prio,src,added) VALUES(?,?,?,?)', (dom, prio, src, int(time.time())))
    return True

# ---------- TG channels ----------
def fetch_channel_posts(chan, before=None, pages=2):
    posts = []
    cur = before
    for _ in range(pages):
        url = 'https://t.me/s/' + chan + (('?before=' + str(cur)) if cur else '')
        st, body, _ = http(url)
        if st != 200 or 'tgme_widget_message_wrap' not in body:
            return posts, st
        blocks = re.split(r'tgme_widget_message_wrap', body)[1:]
        for b in blocks:
            pm = re.search(r'data-post="(?:s/)?[^/"]+/(\d+)"', b)
            if not pm: continue
            mid = int(pm.group(1))
            dm = re.search(r'<time[^>]*datetime="([^"]+)"', b)
            date = dm.group(1) if dm else ''
            tm = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
            text = ''
            if tm:
                text = re.sub(r'<br/?>', ' ', tm.group(1))
                text = re.sub(r'<[^>]+>', '', text)
                text = htmlmod.unescape(text)
            lm = re.findall(r"href='(https?://[^']+)'", b) + re.findall(r'href="(https?://[^"]+)"', b)
            text += ' ' + ' '.join(lm)
            posts.append((mid, date, text[:3000]))
        if not posts: break
        oldest = min(p[0] for p in posts)
        if cur and oldest >= cur: break
        cur = oldest
        time.sleep(1.5)
    return posts, 200

def fetch_channel_telethon(chan):
    sess = TELETHON_CHANS.get(chan)
    if not sess or not os.path.exists(sess): return None, 'no session'
    try:
        api_hash = open(TG_API_HASH_FILE).read().strip()
    except Exception:
        return None, 'no api_hash file'
    try:
        import asyncio
        from telethon import TelegramClient
        from telethon.tl.functions.channels import JoinChannelRequest
        async def run():
            out = []
            base = os.path.splitext(sess)[0]
            radar_sess = base + '_radar.session'
            if not os.path.exists(radar_sess):
                import shutil
                shutil.copy2(sess, radar_sess)
            client = TelegramClient(base + '_radar', TG_API_ID, api_hash,
                                    connection_retries=1, request_retries=1)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect(); return None
            try:
                ch = await client.get_entity(chan)
            except Exception:
                ch = None
                try:
                    r = await client(JoinChannelRequest(chan)); ch = r.chats[0]
                except Exception:
                    await client.disconnect(); return None
            msgs = await client.get_messages(ch, limit=40)
            for m in msgs:
                text = (m.text or m.message or '')
                for b in (m.buttons or []):
                    for btn in b:
                        try:
                            if btn.url: text += ' ' + btn.url
                        except Exception: pass
                out.append((m.id, m.date.strftime('%Y-%m-%dT%H:%M:%S') if m.date else '', text[:3000]))
            await client.disconnect()
            return out
        return asyncio.run(asyncio.wait_for(run(), timeout=90)), None
    except Exception as e:
        return None, str(e)[:120]

# ---------- zuiquanapi catalog (~4000 relay stations) ----------
def harvest_zuiquan(c):
    st, body, _ = http('https://www.zuiquanapi.com/', timeout=25)
    if st != 200 or len(body) < 5000:
        print('zuiquan fetch fail', st); return 0
    raw = body.replace(chr(92) + chr(34), chr(34))
    n = 0
    for m in re.finditer(r'"name":"([^"]{2,60})","url":"(https?://[^"]+)"[\s\S]{0,900}?"description":"([^"]{0,400})', raw):
        name, url, desc = m.group(1), m.group(2), m.group(3)
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            continue
        host = re.sub(r'^www\.', '', host)
        dl = (name + ' ' + desc).lower()
        if CJK.search(name + ' ' + desc):
            continue  # китайские станции — skip
        prio = 2
        if any(k in dl for k in ('免费', 'free', '试用', '赠送', '白嫖', '0元')): prio = 1
        if enqueue(c, host, prio, 'zuiquan:' + name[:30]): n += 1
    print('zuiquan enqueued:', n)
    return n

# ---------- GitHub mining ----------
def harvest_github(c):
    try:
        tok = open(GH_TOKEN_FILE).read().strip()
    except Exception:
        print('no gh token'); return 0
    GH = {'Authorization': '***' + tok, 'Accept': 'application/vnd.github+json',
          'User-Agent': 'abuse-radar', 'X-GitHub-Api-Version': '2022-11-28'}
    queries = ['free ai api', 'llm api gateway free', 'new-api', 'chatgpt free api',
               'awesome free ai', 'reverse api']
    n = 0
    for q in queries:
        try:
            url = 'https://api.github.com/search/repositories?q=' + urllib.parse.quote(q) + '&sort=updated&per_page=8'
            st, body, _ = http(url, timeout=20, headers=GH)
            if st != 200:
                print('gh search', st, q[:20]); time.sleep(3); continue
            items = json.loads(body).get('items', [])
            for it in items:
                rurl = it.get('html_url', '')
                st2, readme, _ = http(rurl.replace('github.com/', 'raw.githubusercontent.com/') + '/HEAD/README.md', timeout=15)
                if st2 != 200 or len(readme) < 200: continue
                urls = re.findall(r'https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s<>"\')\]]*)?', readme[:80000])
                for u in urls[:40]:
                    try:
                        host = urllib.parse.urlparse(u).netloc.lower()
                    except Exception:
                        continue
                    host = re.sub(r'^www\.', '', host)
                    if enqueue(c, host, 3, 'github:' + str(it.get('full_name', ''))[:40]): n += 1
            time.sleep(4)
        except Exception as e:
            print('gh err', str(e)[:60])
    print('github enqueued:', n)
    return n

# ---------- URL extraction ----------
def extract_urls(text):
    urls = re.findall(r'https?://[^\s<>"\')\]]+', text)
    out = []
    for u in urls:
        u = u.rstrip('.,;:!?')
        try:
            host = urllib.parse.urlparse(u).netloc.lower()
        except Exception:
            continue
        host = re.sub(r'^www\.', '', host)
        out.append((host, u))
    return out

AUTH_MARKERS = [
    ('clerk', r'clerk\.(?:accounts|dev|com|production)|@clerk'),
    ('supabase', r'supabase\.co|supabase\.in|sb-[a-z]{10,}'),
    ('workos', r'workos|authkit'),
    ('firebase', r'firebase|identitytoolkit'),
    ('auth0', r'auth0\.com'),
    ('nextauth', r'next-auth|nextauth|api/auth/session'),
    ('kinde', r'kinde\.com'),
    ('stack', r'stack-auth|stackframe'),
    ('newapi', r'new-api|one-api|/api/status'),
    ('lobechat', r'lobehub|lobe-chat'),
    ('oauth_github', r'github\.com/login/oauth|oauth/github'),
    ('oauth_google', r'accounts\.google\.com|oauth/google'),
    ('turnstile', r'turnstile|challenges\.cloudflare\.com|0x4[A-Za-z0-9]{20,}'),
    ('recaptcha', r'recaptcha|recaptcha\.net|6L[A-Za-z0-9_-]{20,}'),
    ('hcaptcha', r'hcaptcha\.com|h-captcha'),
    ('altcha', r'altcha'),
    ('captcha_run', r'captcha\.run'),
]
FREEBIE_SIG = re.compile(r'(free credit[s]?|free tier|free trial|welcome bonus|sign[- ]?up bonus|daily (?:free|check[- ]?in)|赠送|免费|试用额度)', re.I)
CJK = re.compile(r'[\u4e00-\u9fff]')

def autoreg_verdict(info):
    """Вердикт: можно ли авторег и как. Возвращает строку для карточки."""
    p = info.get('panel') or {}
    reg_open = p.get('reg') in (True, 'true', 1)
    keyless = info.get('keyless_api')
    reg = info.get('reg', '')
    caps = info.get('signup_markers', [])
    if keyless and info.get('open_chat'):
        return '✅ АВТОРЕГ НЕ НУЖЕН — API открыт без ключа, юзай сразу'
    if reg_open and not p.get('turnstile'):
        v = '✅ АВТОРЕГ ДА — email+pass без капчи'
        if p.get('github_oauth'): v += ' + GH-pool'
        q = str(p.get('quota') or '')
        try:
            if q and float(q) > 0: v += ' + бонус $' + ('%.2f' % (float(q) / 500000)).rstrip('0').rstrip('.')
        except Exception: pass
        return v
    if reg_open and p.get('turnstile'):
        v = '✅ АВТОРЕГ ДА — turnstile решает sidecar :8877'
        if p.get('github_oauth'): v += ', или GH OAuth (пул 1962 акка)'
        if p.get('telegram_oauth'): v += ', TG-oauth (пул сессий)'
        return v
    if 'NO-CAPTCHA signup' in reg:
        stack = [x for x in caps if x in ('clerk', 'supabase', 'workos', 'firebase', 'stack', 'kinde', 'auth0', 'nextauth')]
        if stack:
            return '✅ АВТОРЕГ ДА — ' + stack[0] + ' протокол (есть готовые реги), email без капчи'
        if 'oauth_github' in caps:
            return '✅ АВТОРЕГ ДА — GH OAuth (пул 1962 акка), без капчи'
        return '🟡 АВТОРЕГ ВЕРОЯТНО — signup без капчи, надо реверсить форму (Next.js/server actions)'
    if 'captcha-solvable' in reg:
        cc = 'turnstile' if 'turnstile' in reg else ('recaptcha' if 'recaptcha' in reg else 'altcha')
        return '🟡 АВТОРЕГ МОЖНО — ' + cc + ' решаем (sidecar/2captcha), email-рега'
    if 'hard-captcha' in reg:
        return '❌ АВТОРЕГ НЕТ — hcaptcha/captcha.run (не решаем нашим стеком)'
    if p and not reg_open:
        return '❌ АВТОРЕГ НЕТ — рега закрыта (invite/ждём открытия)'
    if keyless:
        return '🟡 API keyless на /v1/models, chat может требовать ключ — проверить'
    return '❓ нет signup/API — ручной разбор'

def deep_probe(dom):
    """Возвращает (score, info). Фокус: бесплатный доступ к AI по API."""
    info = {}; score = 0
    base = 'https://' + dom
    st, body, fin = http(base, timeout=12)
    info['root'] = st
    if st == 0:
        st2, body2, _ = http('http://' + dom, timeout=10)
        if st2: st, body = st2, body2
        info['root'] = st
    if st == 0 or st >= 500:
        return 0, info
    tm = re.search(r'<title[^>]*>([^<]{3,100})', body, re.I)
    info['title'] = htmlmod.unescape(tm.group(1)).strip()[:70] if tm else ''
    dm = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,200})', body, re.I) \
         or re.search(r'<meta[^>]+content=["\']([^"\']{10,200})["\'][^>]+name=["\']description', body, re.I)
    info['desc'] = htmlmod.unescape(dm.group(1)).strip()[:150] if dm else ''
    if len(CJK.findall(info.get('title', '') + ' ' + info.get('desc', ''))) >= 3:
        return -1, {'cjk': True, 'title': info.get('title', '')[:50]}
    fb = FREEBIE_SIG.findall(body)
    if fb: info['freebie'] = list(dict.fromkeys([x.lower() for x in fb]))[:4]
    low = body.lower()
    # 1) new-api панель
    panel = 'newapi' in low or 'one-api' in low or '/api/status' in low
    as_, ab, _ = http(base + '/api/status', timeout=10)
    if as_ == 200 and ab.strip().startswith('{'):
        try:
            j = json.loads(ab)
            d = j.get('data') if isinstance(j.get('data'), dict) else j
            if isinstance(d, dict) and ('system_name' in d or 'version' in d or 'register_enabled' in d):
                panel = True
                info['panel'] = {'sys': str(d.get('system_name', ''))[:30], 'ver': str(d.get('version', ''))[:12],
                                 'reg': d.get('register_enabled'), 'email_verif': d.get('email_verification_enabled'),
                                 'turnstile': d.get('turnstile_check'), 'epay': d.get('epay_enabled'),
                                 'github_oauth': d.get('github_oauth'), 'linuxdo_oauth': d.get('linuxdo_oauth'),
                                 'telegram_oauth': d.get('telegram_oauth'), 'password_login': d.get('password_login_enabled'),
                                 'quota': str(d.get('quota_for_new_user', ''))[:12]}
        except Exception:
            pass
    if panel:
        p = info.get('panel', {})
        reg_open = p.get('reg') in (True, 'true', 1)
        if reg_open:
            if not p.get('turnstile'): score += 50; info['reg'] = 'PANEL reg open, NO turnstile'
            else: score += 40; info['reg'] = 'PANEL reg open + turnstile (solvable)'
            if p.get('github_oauth'): score += 8; info['reg'] += ' +GH-oauth'
            if p.get('telegram_oauth'): score += 5; info['reg'] += ' +TG-oauth'
            if p.get('linuxdo_oauth'): score += 5; info['reg'] += ' +LinuxDO-oauth'
        elif p:
            score += 10; info['reg'] = 'PANEL reg closed'
        if p.get('epay'): score += 5; info['usdt'] = True
        ps, pb, _ = http(base + '/api/pricing', timeout=15)
        if ps == 200 and pb.strip().startswith('{'):
            try:
                pj = json.loads(pb)
                plist = pj.get('data', [])
                if isinstance(plist, list) and plist:
                    free = [m.get('model_name') for m in plist
                            if isinstance(m, dict) and m.get('model_ratio') in (0, 0.0, None) and m.get('model_price') in (0, 0.0, None) and m.get('model_name')]
                    info['models_total'] = len(plist)
                    if free:
                        info['free_models'] = free[:12]
                        score += 30 + min(len(free), 10)
            except Exception: pass
    # 2) keyless /v1/models
    keyless = False
    for api in ('/v1/models', '/api/v1/models'):
        for hdr in ({'Authorization': '***'}, {}):
            ms, mb, _ = http(base + api, timeout=12, headers=hdr)
            if ms == 200 and ('"data"' in mb[:3000] or mb.strip().startswith('[')):
                ids = []
                try:
                    j = json.loads(mb)
                    arr = j.get('data') if isinstance(j, dict) else j
                    ids = [m.get('id') or m.get('model_name') for m in arr if isinstance(m, dict)]
                except Exception:
                    pass
                keyless = True
                info['keyless_api'] = api
                info['models'] = ids[:15]
                info['models_n'] = len(ids)
                score += 60
                break
        if keyless: break
    # 3) open chat без ключа
    if keyless and info.get('models'):
        try:
            payload = json.dumps({'model': info['models'][0],
                                  'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 1}).encode()
            cs, cb, _ = http(base + info['keyless_api'].replace('/models', '/chat/completions'), timeout=20,
                             data=payload, headers={'Content-Type': 'application/json'})
            if cs == 200 and ('choices' in cb or 'content' in cb):
                score += 15; info['open_chat'] = True
        except Exception: pass
    # 4) signup-страница (если не панель)
    if not panel:
        markers = [name for name, pat in AUTH_MARKERS if re.search(pat, body, re.I)]
        info['markers'] = markers[:8]
        for p in ('/signup', '/register', '/login', '/sign-up', '/auth/sign-up'):
            ps2, pb2, pf = http(base + p, timeout=12)
            if ps2 == 200 and pb2 and len(pb2) > 500:
                pl = pb2.lower()
                if any(x in pl for x in ('password', 'email', 'sign up', 'register', 'create account')):
                    info['signup'] = p
                    smk = list(set(markers + [name for name, pat in AUTH_MARKERS if re.search(pat, pb2, re.I)]))
                    info['signup_markers'] = smk[:10]
                    caps = [x for x in ('turnstile', 'recaptcha', 'hcaptcha', 'altcha', 'captcha_run') if x in smk]
                    if not caps: score += 40; info['reg'] = 'NO-CAPTCHA signup'
                    elif set(caps) & {'turnstile', 'altcha', 'recaptcha'}: score += 25; info['reg'] = 'captcha-solvable signup (' + ','.join(caps) + ')'
                    else: score += 12; info['reg'] = 'hard-captcha signup (' + ','.join(caps) + ')'
                    if 'oauth_github' in smk: score += 8; info['reg'] += ' +GH-oauth'
                    if any(x in smk for x in ('clerk', 'supabase', 'workos', 'firebase', 'stack', 'kinde')): score += 12; info['reg'] += ' +known-stack'
                    break
    # 5) docs
    for d in ('/docs', '/apidocs', '/api-docs', '/openapi.json'):
        ds, db2, _ = http(base + d, timeout=8)
        if ds == 200 and len(db2) > 800:
            info['docs'] = d; score += 5; break
    if info.get('freebie'): score += 8
    return score, info

# ---------- TG ----------
def tg_notify(text):
    tok = None
    try:
        tok = open(TG_TOKEN_FILE).read().strip()
    except Exception:
        pass
    if not tok:
        try:
            for line in open(TG_ENV, encoding='utf-8'):
                m = re.match(r'\s*TELEGRAM_BOT_TOKEN\s*=\s*(.+)', line)
                if m: tok = m.group(1).strip().strip('"\''); break
        except Exception: pass
    if not tok:
        print('no tg token'); return False
    payload = json.dumps({'chat_id': TG_CHAT, 'message_thread_id': TG_THREAD, 'text': text[:4000]}).encode()
    st, resp, _ = http('https://api.telegram.org/bot' + tok + '/sendMessage', timeout=20, data=payload,
                       headers={'Content-Type': 'application/json'})
    if st != 200: print('tg send fail', st, resp[:120])
    return st == 200

def card(dom, score, info, src):
    L = ['🎯 ' + dom + '  [' + str(score) + ']  via ' + src]
    L.append(autoreg_verdict(info))
    if info.get('title') or info.get('desc'):
        L.append('📋 ' + (info.get('title') or '') + (' — ' + info['desc'] if info.get('desc') else ''))
    p = info.get('panel')
    if p:
        L.append('🔧 new-api: ' + str(p.get('sys') or '?') + ' v' + str(p.get('ver') or '?') +
                 ' | reg:' + ('OPEN' if p.get('reg') in (True, 'true', 1) else 'closed') +
                 ' | turnstile:' + ('YES' if p.get('turnstile') else 'no') +
                 (' | GH-oauth' if p.get('github_oauth') else '') + (' | TG-oauth' if p.get('telegram_oauth') else '') +
                 (' | LinuxDO' if p.get('linuxdo_oauth') else '') + (' | USDT' if p.get('epay') else ''))
        q = str(p.get('quota') or '')
        if q and q not in ('0', 'None'):
            try: L.append('💰 бонус новичку: $' + ('%.2f' % (float(q) / 500000)).rstrip('0').rstrip('.'))
            except Exception: pass
    if info.get('keyless_api'):
        L.append('🔑 KEYLESS ' + info['keyless_api'] + ' (' + str(info.get('models_n', '?')) + ' моделей)' +
                 (' | OPEN CHAT без ключа!' if info.get('open_chat') else ''))
        if info.get('models'): L.append('   ' + ', '.join(str(x) for x in info['models'][:10]))
    if info.get('free_models'):
        L.append('🆓 free-модели (' + str(info.get('models_total', '?')) + ' всего в прайсе): ' + ', '.join(info['free_models'][:8]))
    if info.get('reg') and not p:
        L.append('📝 рег: ' + info['reg'] + (' | ' + ','.join(info.get('signup_markers', [])[:5]) if info.get('signup_markers') else ''))
    if info.get('freebie'):
        L.append('🎁 freebie: ' + ', '.join(info['freebie'][:3]))
    if info.get('docs'): L.append('📄 docs: ' + info['docs'])
    return '\n'.join(L)

def main():
    full = '--full' in sys.argv
    c = db()
    now = int(time.time())
    for s in SEEDS:
        c.execute('INSERT OR IGNORE INTO channels(name,source,added) VALUES(?,?,?)', (s, 'seed', now))
    c.commit()
    # --- источники в очередь ---
    try: harvest_zuiquan(c)
    except Exception as e: print('zuiquan err', str(e)[:80])
    c.commit()
    if full or random.random() < 0.3:
        try: harvest_github(c)
        except Exception as e: print('github err', str(e)[:80])
        c.commit()
    # --- каналы ---
    chans = [r[0] for r in c.execute('SELECT name FROM channels WHERE ok=1 ORDER BY added LIMIT ?', (MAX_CHANS,))]
    for chan in chans:
        seen_max = c.execute('SELECT MAX(mid) FROM messages WHERE chan=?', (chan,)).fetchone()[0] or 0
        posts, st = fetch_channel_posts(chan, pages=3 if full else 2)
        if (st != 200 or not posts) and chan in TELETHON_CHANS:
            tposts, terr = fetch_channel_telethon(chan)
            if tposts:
                posts = tposts; st = 200
                print(chan, 'telethon OK:', len(posts))
            else:
                print(chan, 'telethon FAIL:', terr)
        if st != 200 or not posts:
            print(chan, 'FETCH FAIL', st); c.execute('UPDATE channels SET last_scan=? WHERE name=?', (now, chan)); continue
        new_posts = posts if seen_max == 0 else [p for p in posts if p[0] > seen_max]
        ins = 0
        for mid, date, text in new_posts:
            c.execute('INSERT OR IGNORE INTO messages(chan,mid,date,text) VALUES(?,?,?,?)', (chan, mid, date, text))
            ins += 1
            for dom, u in extract_urls(text):
                enqueue(c, dom, 1, 'tg:@' + chan)
            for m in re.findall(r't\.me/([A-Za-z][A-Za-z0-9_]{4,35})', text):
                ml = m.lower()
                if ml in SKIP_DOMAINS or ml in chans or ml.startswith(('s', 'add', 'share', 'proxy', 'socks', 'iv')): continue
                if re.search(r'(bot$|stickers|emoji|theme)', ml): continue
                if c.execute('SELECT COUNT(*) FROM channels').fetchone()[0] < MAX_CHANS:
                    c.execute('INSERT OR IGNORE INTO channels(name,source,added) VALUES(?,?,?)', (m, 'organic:' + chan, now))
        c.execute('UPDATE channels SET last_scan=? WHERE name=?', (now, chan))
        print(chan, 'new:', ins, 'seen:', len(posts))
        time.sleep(1.5)
    c.commit()
    # --- пробы из очереди ---
    cap = PROBE_CAP * 3 if full else PROBE_CAP
    rows = c.execute('SELECT domain,prio,src FROM queue WHERE done=0 ORDER BY prio ASC, added ASC LIMIT ?', (cap,)).fetchall()
    alerts = []
    already = set(r[0] for r in c.execute('SELECT domain FROM domains WHERE notified=1'))
    for dom, prio, src in rows:
        c.execute('UPDATE queue SET done=1 WHERE domain=?', (dom,))
        try:
            score, info = deep_probe(dom)
        except Exception as e:
            score, info = 0, {'err': str(e)[:80]}
        c.execute('''INSERT INTO domains(domain,first_seen,last_probe,score,info) VALUES(?,?,?,?,?)
                     ON CONFLICT(domain) DO UPDATE SET last_probe=excluded.last_probe, score=excluded.score, info=excluded.info''',
                  (dom, now, int(time.time()), score, json.dumps(info, ensure_ascii=False)[:1400]))
        if score >= 30:
            c.execute('INSERT INTO findings(ts,domain,score,info,src_chan,src_mid) VALUES(?,?,?,?,?,?)',
                      (int(time.time()), dom, score, json.dumps(info, ensure_ascii=False)[:1400], src, 0))
            verd = autoreg_verdict(info)
            if dom not in already and verd[:1] in ('✅', '🟡'):
                alerts.append((score, dom, info, src))
                already.add(dom)
        print(' probe', dom, '->', score, (info.get('reg') or info.get('keyless_api') or ''), str(info.get('title') or '')[:40])
        c.commit()
        time.sleep(0.7)
    # --- алерты: карточки батчами по 3 ---
    fresh = sorted(alerts, key=lambda a: -a[0])[:9]
    for i in range(0, len(fresh), 3):
        batch = fresh[i:i + 3]
        txt = '📡 ABUSE-RADAR v2 — ' + str(len(alerts)) + ' новых целей за ран\n\n'
        txt += '\n\n'.join(card(dom, score, info, src) for score, dom, info, src in batch)
        if tg_notify(txt):
            for _, dom, _, _ in batch:
                c.execute('UPDATE domains SET notified=1 WHERE domain=?', (dom,))
        c.commit()
        time.sleep(3)
    print('ALERTED:', len(fresh), 'of', len(alerts))
    print('stats: domains', c.execute('SELECT COUNT(*) FROM domains').fetchone()[0],
          '| queue_left', c.execute('SELECT COUNT(*) FROM queue WHERE done=0').fetchone()[0],
          '| msgs', c.execute('SELECT COUNT(*) FROM messages').fetchone()[0],
          '| chans', c.execute('SELECT COUNT(*) FROM channels').fetchone()[0],
          '| findings', c.execute('SELECT COUNT(*) FROM findings').fetchone()[0])

if __name__ == '__main__':
    main()
