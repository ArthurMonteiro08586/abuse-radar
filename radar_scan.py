# -*- coding: utf-8 -*-
# ABUSE-RADAR v1 (2026-10-19)
# Мониторинг TG-каналов ниши AI free-tier/abuse -> поиск новых сайтов -> пробы signup/API -> скоринг -> TG-алерт.
# Stdlib-only (VPS-совместим). State: sqlite radar.db. Запуск: python3 radar_scan.py [--full]
import sys, os, re, json, time, sqlite3, hashlib, html as htmlmod
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import urllib.request, urllib.parse, ssl

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'}
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, 'radar.db')
SEEDS = ['bozdrop', 'no_agi_chat', 'AIUngated', 'freegptmaster', 'freegptmaster_ru', 'free_republic_ai']
MAX_CHANS = 40
TG_TOKEN_FILE = os.path.join(DIR, 'tg_token')    # токен гейтвейного бота (не в репо!)
TG_ENV = r'C:\Users\User\AppData\Local\hermes\.env'  # fallback: TELEGRAM_BOT_TOKEN из hermes .env
TG_CHAT = '7448683285'; TG_THREAD = 455324
# Telethon-fallback каналы (JoinChannel-стена на t.me/s/):
TELETHON_CHANS = {'bozdrop': r'C:\Users\User\AppData\Local\hermes\cache\scratch\bozprobe_32_1_7068444489.session',
                  'no_agi_chat': r'C:\Users\User\AppData\Local\hermes\cache\scratch\bozprobe_32_1_7068444489.session'}
TG_API_ID = 2040
TG_API_HASH_FILE = os.path.join(DIR, 'tg_api_hash')  # файл с api_hash (не в репо)

SKIP_DOMAINS = ('t.me', 'telegram.me', 'telegram.org', 'github.com', 'youtube.com', 'youtu.be',
                'twitter.com', 'x.com', 'discord.gg', 'discord.com', 'google.com', 'play.google.com',
                'apps.apple.com', 'wikipedia.org', 'reddit.com', 'medium.com', 'telegra.ph',
                'linkedin.com', 'instagram.com', 'facebook.com', 'tiktok.com', 'patreon.com',
                'boosty.to', 'donationalerts.com', 'twitch.tv', 'vk.com', 'whatsapp.com')

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute('''CREATE TABLE IF NOT EXISTS messages(chan TEXT, mid INT, date TEXT, text TEXT, PRIMARY KEY(chan,mid))''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels(name TEXT PRIMARY KEY, source TEXT, added INT, last_scan INT, ok INT DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS domains(domain TEXT PRIMARY KEY, first_seen INT, last_probe INT, score INT DEFAULT 0, info TEXT, notified INT DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS findings(ts INT, domain TEXT, score INT, info TEXT, src_chan TEXT, src_mid INT)''')
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

def fetch_channel_posts(chan, before=None, pages=2):
    """t.me/s/<chan> public preview; returns list of (mid, date, text)."""
    posts = []
    cur = before
    for _ in range(pages):
        url = 'https://t.me/s/' + chan + (('?before=' + str(cur)) if cur else '')
        st, body, _ = http(url)
        if st != 200 or 'tgme_widget_message_wrap' not in body:
            return posts, st
        for m in re.finditer(r'data-post="(?:s/)?([^"]+)"', body):
            pass
        blocks = re.split(r'tgme_widget_message_wrap', body)[1:]
        for b in blocks:
            pm = re.search(r'data-post="(?:s/)?' + re.escape(chan) + r'/(\d+)"', b)
            if not pm:
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

def extract_urls(text):
    urls = re.findall(r'https?://[^\s<>"\')\]]+', text)
    out = []
    for u in urls:
        u = u.rstrip('.,;:!?')
        try:
            host = urllib.parse.urlparse(u).netloc.lower()
        except Exception:
            continue
        if not host or any(host == s or host.endswith('.' + s) for s in SKIP_DOMAINS): continue
        host = re.sub(r'^www\.', '', host)
        out.append((host, u))
    return out

AUTH_MARKERS = [
    ('clerk', r'clerk\.(?:accounts|dev|com|production)|@clerk'),
    ('supabase', r'supabase\.co|supabase\.in|sb-[a-z]{10,}'),
    ('workos', r'workos|authkit'),
    ('firebase', r'firebase|googleapis\.com/identitytoolkit|identitytoolkit'),
    ('auth0', r'auth0\.com'),
    ('nextauth', r'next-auth|nextauth|api/auth/session'),
    ('kinde', r'kinde\.com'),
    ('stack', r'stack-auth|stackframe'),
    ('newapi', r'new-api|one-api|/api/status|/api/about'),
    ('lobechat', r'lobehub|lobe-chat'),
    ('oauth_github', r'github\.com/login/oauth|GitHub.{0,30}(sign|log)\s?in|oauth/github'),
    ('oauth_google', r'accounts\.google\.com|sign[_ ]?in with google|oauth/google'),
    ('turnstile', r'turnstile|challenges\.cloudflare\.com|0x4[A-Za-z0-9]{20,}'),
    ('recaptcha', r'recaptcha|recaptcha\.net|6L[A-Za-z0-9_-]{20,}'),
    ('hcaptcha', r'hcaptcha\.com|h-captcha'),
    ('altcha', r'altcha'),
    ('captcha_run', r'captcha\.run'),
]

def probe_domain(dom):
    """Returns (score, info dict)."""
    info = {}; score = 0
    base = 'https://' + dom
    st, body, fin = http(base, timeout=12)
    info['root'] = st
    if st == 0 and not body.startswith('<'):
        st2, body2, fin2 = http('http://' + dom, timeout=10)
        if st2: st, body, fin = st2, body2, fin2
        info['root'] = st
    if st >= 400 or st == 0:
        return 0, info
    low = body.lower()
    markers = [name for name, pat in AUTH_MARKERS if re.search(pat, body, re.I)]
    info['markers'] = markers[:8]
    info['title'] = (re.search(r'<title[^>]*>([^<]{3,80})', body, re.I) or [None, ''])[1].strip()[:60]
    # signup paths
    for p in ('/signup', '/register', '/login', '/sign-up', '/auth/sign-up'):
        ps, pb, pf = http(base + p, timeout=12)
        if ps == 200 and pb and len(pb) > 500:
            pl = pb.lower()
            if any(x in pl for x in ('password', 'email', 'sign up', 'register', 'create account', 'логин', 'регистрац')):
                info['signup'] = p
                pmk = [name for name, pat in AUTH_MARKERS if re.search(pat, pb, re.I)]
                info['signup_markers'] = list(set((markers + pmk)))[:10]
                caps = [c for c in ('turnstile', 'recaptcha', 'hcaptcha', 'altcha', 'captcha_run') if c in info['signup_markers']]
                if not caps: score += 40; info['reg'] = 'NO-CAPTCHA signup'
                elif set(caps) & {'turnstile', 'altcha', 'recaptcha'}: score += 25; info['reg'] = 'captcha-solvable signup (' + ','.join(caps) + ')'
                else: score += 12; info['reg'] = 'hard-captcha signup (' + ','.join(caps) + ')'
                if 'oauth_github' in info['signup_markers']: score += 8; info['reg'] += ' +GH-oauth'
                if any(x in info['signup_markers'] for x in ('clerk', 'supabase', 'workos', 'firebase', 'stack', 'kinde')): score += 12; info['reg'] += ' +known-stack'
                break
    # new-api panel
    if 'newapi' in markers or '/api/status' in low:
        as_, ab, _ = http(base + '/api/status', timeout=10)
        if as_ == 200 and ab.strip().startswith(('{', '[')):
            score += 30; info['newapi_panel'] = True
            try:
                j = json.loads(ab)
                info['panel'] = str(j)[:200]
            except Exception: pass
    # keyless API
    for api in ('/v1/models', '/api/v1/models'):
        ms, mb, _ = http(base + api, timeout=12, headers={'Authorization': '***'})
        if ms == 200 and ('data' in mb[:2000] or 'models' in mb[:2000]):
            try:
                j = json.loads(mb)
                ids = [m.get('id') for m in (j.get('data') or [])][:12]
            except Exception:
                ids = []
            score += 50; info['keyless_api'] = api; info['models'] = ids
            break
    # docs
    for d in ('/docs', '/apidocs', '/api-docs', '/openapi.json'):
        ds, dbody, _ = http(base + d, timeout=8)
        if ds == 200 and len(dbody) > 800:
            info['docs'] = d; score += 5; break
    return score, info

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
        print('no tg token'); return
    payload = json.dumps({'chat_id': TG_CHAT, 'message_thread_id': TG_THREAD, 'text': text[:4000]}).encode()
    http('https://api.telegram.org/bot' + tok + '/sendMessage', timeout=20, data=payload,
         headers={'Content-Type': 'application/json'})

def fetch_channel_telethon(chan):
    """Fallback для каналов с JoinChannel-стеной. Возвращает [(mid,date,text)] или (None, err)."""
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

def main():
    full = '--full' in sys.argv
    c = db()
    now = int(time.time())
    # seed channels
    for s in SEEDS:
        c.execute('INSERT OR IGNORE INTO channels(name,source,added) VALUES(?,?,?)', (s, 'seed', now))
    chans = [r[0] for r in c.execute('SELECT name FROM channels WHERE ok=1 ORDER BY added LIMIT ?', (MAX_CHANS,))]
    new_domains = []
    alerts = []
    for chan in chans:
        seen_max = c.execute('SELECT MAX(mid) FROM messages WHERE chan=?', (chan,)).fetchone()[0] or 0
        posts, st = fetch_channel_posts(chan, pages=3 if full else 2)
        if (st != 200 or not posts) and chan in TELETHON_CHANS:
            tposts, terr = fetch_channel_telethon(chan)
            if tposts:
                posts = tposts; st = 200
                print(chan, 'telethon fallback OK:', len(posts))
            else:
                print(chan, 'telethon fallback FAIL:', terr)
        if st != 200:
            print(chan, 'FETCH FAIL', st); c.execute('UPDATE channels SET last_scan=? WHERE name=?', (now, chan)); continue
        new_posts = [p for p in posts if p[0] > seen_max]
        if seen_max == 0: new_posts = posts  # первый скан — берём всё
        ins = 0
        for mid, date, text in new_posts:
            try:
                c.execute('INSERT OR IGNORE INTO messages(chan,mid,date,text) VALUES(?,?,?,?)', (chan, mid, date, text))
                ins += 1
            except Exception: pass
            for dom, u in extract_urls(text):
                r = c.execute('SELECT domain FROM domains WHERE domain=?', (dom,)).fetchone()
                if not r:
                    c.execute('INSERT OR IGNORE INTO domains(domain,first_seen) VALUES(?,?)', (dom, now))
                    new_domains.append((dom, chan, mid))
            # organic channel discovery
            for m in re.findall(r't\.me/([A-Za-z][A-Za-z0-9_]{4,35})', text):
                ml = m.lower()
                if ml in SKIP_DOMAINS or ml in chans or ml.startswith(('s/', 'add', 'share', 'proxy', 'socks', 'iv?')): continue
                if re.search(r'(bot$|stickers|emoji|theme)', ml): continue
                cnt = c.execute('SELECT COUNT(*) FROM channels').fetchone()[0]
                if cnt < MAX_CHANS:
                    c.execute('INSERT OR IGNORE INTO channels(name,source,added) VALUES(?,?,?)', (m, 'organic:' + chan, now))
        c.execute('UPDATE channels SET last_scan=? WHERE name=?', (now, chan))
        print(chan, 'posts_new:', ins, 'total_seen:', len(posts))
        time.sleep(2)
    # probe new domains (cap per run)
    cap = 60 if full else 20
    for dom, chan, mid in new_domains[:cap]:
        try:
            score, info = probe_domain(dom)
        except Exception as e:
            score, info = 0, {'err': str(e)[:80]}
        c.execute('UPDATE domains SET last_probe=?, score=?, info=? WHERE domain=?', (int(time.time()), score, json.dumps(info, ensure_ascii=False)[:900], dom))
        if score >= 25:
            c.execute('INSERT INTO findings(ts,domain,score,info,src_chan,src_mid) VALUES(?,?,?,?,?,?)',
                      (int(time.time()), dom, score, json.dumps(info, ensure_ascii=False)[:900], chan, mid))
            alerts.append((score, dom, info, chan))
        print(' probe', dom, '->', score, str(info)[:100])
        time.sleep(1)
    c.commit()
    # alert (top-5 новых)
    already = set(r[0] for r in c.execute('SELECT domain FROM domains WHERE notified=1'))
    fresh = [a for a in sorted(alerts, reverse=True) if a[1] not in already][:5]
    if fresh:
        lines = ['ABUSE-RADAR: новые цели']
        for score, dom, info, chan in fresh:
            lines.append('')
            lines.append('%s  [%d] (via @%s)' % (dom, score, chan))
            if info.get('reg'): lines.append('  reg: ' + info['reg'])
            if info.get('keyless_api'): lines.append('  KEYLESS API: ' + str(info.get('models'))[:160])
            if info.get('newapi_panel'): lines.append('  new-api panel: ' + str(info.get('panel'))[:120])
            if info.get('signup'): lines.append('  signup: ' + info['signup'] + ' | ' + ','.join(info.get('signup_markers', [])[:6]))
            if info.get('title'): lines.append('  title: ' + info['title'])
        tg_notify('\n'.join(lines))
        for _, dom, _, _ in fresh:
            c.execute('UPDATE domains SET notified=1 WHERE domain=?', (dom,))
        c.commit()
        print('ALERTED:', len(fresh))
    else:
        print('nothing new to alert')
    print('stats: domains', c.execute('SELECT COUNT(*) FROM domains').fetchone()[0],
          '| msgs', c.execute('SELECT COUNT(*) FROM messages').fetchone()[0],
          '| chans', c.execute('SELECT COUNT(*) FROM channels').fetchone()[0],
          '| findings', c.execute('SELECT COUNT(*) FROM findings').fetchone()[0])

if __name__ == '__main__':
    main()
