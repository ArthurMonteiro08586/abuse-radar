# ABUSE-RADAR extra sources — Method Hunter guide §03/§05/§06 expansion
# Источники: reddit JSON (www/old ротация), Pepper-сети RSS (DE/UK/PL/FR/IT/MX),
# rentry.co/discover, dpaste.org/archive. Пишет в radar.db (queue/channels).
# Не трогает radar_scan.py (его правит параллельная сессия) — только импорт хелперов.
# Watchdog-паттерн: stdout ПУСТО если нет новых находок (cron no_agent шлёт только непустой вывод).
import sys, os, re, json, time, random, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from radar_scan import http, enqueue, extract_urls, SKIP_DOMAINS, CJK

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'}
AI_KW = re.compile(r'\b(ai|llm|gpt|chatgpt|claude|gemini|grok|deepseek|qwen|llama|openai|anthropic|cursor|copilot|midjourney|suno|api key|free tier|inference|model)\b', re.I)
JUNK_HOSTS = ('reddit.com', 'redd.it', 'youtube.com', 'youtu.be', 'twitter.com', 'x.com', 'google.', 'bing.com',
              'wikipedia.org', 'github.com', 'githubusercontent', 'discord.gg', 'discord.com', 'medium.com',
              'imgur.com', 'streamable.com', 'redditmedia', 'redditstatic', 'apple.com', 'microsoft.com')

def db():
    c = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'radar.db'), timeout=30)
    c.execute('PRAGMA busy_timeout=30000')
    return c

def ok_host(h):
    h = re.sub(r'^www\.', '', h).lower()
    if not h or CJK.search(h): return None
    if any(j in h for j in JUNK_HOSTS): return None
    if h in SKIP_DOMAINS or any(h.endswith('.' + s) for s in SKIP_DOMAINS): return None
    return h

def enqueue_r(c, dom, prio, src, tries=6):
    # radar_scan.enqueue с ретраями на database-is-locked (cron/соседняя сессия держат БД)
    for i in range(tries):
        try:
            return enqueue(c, dom, prio, src)
        except sqlite3.OperationalError as e:
            if 'locked' not in str(e): raise
            time.sleep(3 + i * 3)
    return 0

# ---------- reddit ----------
REDDIT_SUBS = ['LocalLLaMA', 'OpenAI', 'ChatGPTCoding', 'ClaudeAI', 'singularity',
               'ArtificialInteligence', 'freebies', 'slavelabour', 'aifreemium',
               'SideProject', 'AlphaandBetaUsers', 'InternetIsBeautiful', 'startups', 'SaaS']

def harvest_reddit(c):
    n = 0
    fails = 0
    for sub in REDDIT_SUBS:
        got = False
        for host in ('https://www.reddit.com', 'https://old.reddit.com'):
            st, b, _ = http(host + '/r/' + sub + '/new.json?limit=50', timeout=20, headers=UA)
            if st == 200 and b and b.strip().startswith('{'):
                try:
                    data = json.loads(b)
                except Exception:
                    continue
                for ch in data.get('data', {}).get('children', []):
                    d = ch.get('data', {})
                    title = d.get('title', '')
                    text = (d.get('selftext') or '')[:3000]
                    url = d.get('url', '')
                    if d.get('created_utc', 0) < time.time() - 86400 * 3:
                        continue  # только свежие (3 дня)
                    blob = title + ' ' + text
                    if not AI_KW.search(blob):
                        continue
                    cands = []
                    if url.startswith('http'):
                        cands.append(url)
                    cands += [u for _, u in extract_urls(text)]
                    for u in cands[:6]:
                        try:
                            import urllib.parse as up
                            h = ok_host(up.urlparse(u).netloc)
                        except Exception:
                            continue
                        if h and enqueue_r(c, h, 1 if re.search(r'free|trial|promo|bonus|voucher', title, re.I) else 2, 'reddit:' + sub):
                            n += 1
                got = True
                break
            time.sleep(1.5)
        if not got:
            fails += 1
            if fails >= 3:
                break  # reddit rate-limit — выходим, следующий ран доберёт
        time.sleep(2.5 + random.random() * 2)
    commit_r(c)
    return n

# ---------- Pepper-сети (deal-агрегаторы, гайд §05) ----------
PEPPER_FEEDS = {
    'mydealz.de': 'https://www.mydealz.de/rss/hot',
    'hotukdeals.com': 'https://www.hotukdeals.com/rss/hot',
    'pepper.pl': 'https://www.pepper.pl/rss/hot',
    'dealabs.com': 'https://www.dealabs.com/rss/hot',
    'promodescuentos.com.mx': 'https://www.promodescuentos.com.mx/rss/hot',
    'pepper.it': 'https://www.pepper.it/rss/hot',
    'preisjaeger.at': 'https://www.preisjaeger.at/rss/hot',
}

def harvest_pepper(c):
    import html as H
    n = 0
    for name, feed in PEPPER_FEEDS.items():
        st, b, _ = http(feed, timeout=15, headers=UA)
        if st != 200 or not b or '<item' not in b:
            continue
        items = re.findall(r'<item>(.*?)</item>', b, re.S)
        for it in items[:40]:
            t = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', it, re.S)
            l = re.search(r'<link>(.*?)</link>', it, re.S)
            title = H.unescape(t.group(1).strip()) if t else ''
            link = l.group(1).strip() if l else ''
            if not AI_KW.search(title):
                continue
            try:
                import urllib.parse as up
                h = ok_host(up.urlparse(link).netloc)
            except Exception:
                h = None
            if h and enqueue_r(c, h, 1, 'pepper:' + name):
                n += 1
        time.sleep(1.0)
    commit_r(c)
    return n

# ---------- paste-ленты (гайд §03) ----------
def harvest_pastes(c):
    n = 0
    # paster.sh/archive
    st, b, _ = http('https://paster.sh/archive', timeout=15, headers=UA)
    if st == 200 and b:
        for p in list(dict.fromkeys(re.findall(r'href="https://paster\.sh/([A-Za-z0-9]{6,10})"', b)))[:15]:
            ps, pb, _ = http('https://paster.sh/' + p, timeout=10)
            if ps == 200 and pb and AI_KW.search(pb[:8000]):
                for h, u in extract_urls(pb[:30000]):
                    hh = ok_host(h)
                    if hh and enqueue_r(c, hh, 2, 'paster'):
                        n += 1
            time.sleep(0.7)
    # dpaste.com/public/ — raw = .txt
    st, b, _ = http('https://dpaste.com/public/', timeout=15, headers=UA)
    if st == 200 and b:
        for p in list(dict.fromkeys(re.findall(r'href="/([A-Z0-9]{8,12})/?\"', b)))[:15]:
            ps, pb, _ = http('https://dpaste.com/' + p + '.txt', timeout=10)
            if ps == 200 and pb and AI_KW.search(pb[:8000]):
                for h, u in extract_urls(pb[:30000]):
                    hh = ok_host(h)
                    if hh and enqueue_r(c, hh, 2, 'dpaste'):
                        n += 1
            time.sleep(0.7)
    commit_r(c)
    return n

def commit_r(c, tries=6):
    for i in range(tries):
        try:
            c.commit(); return
        except sqlite3.OperationalError:
            time.sleep(3 + i * 3)

# ---------- HN Show (мелкие стартапы, algolia API) ----------
HN_QUERIES = ['ai api', 'llm api', 'chatgpt alternative', 'openai compatible', 'claude api',
              'free credits ai', 'ai agent', 'gpt wrapper', 'ai tool', 'inference api']

def harvest_hn(c):
    import urllib.parse as up
    n = 0
    month_ago = int(time.time()) - 86400 * 30
    seen_titles = set()
    for q in HN_QUERIES:
        u = ('https://hn.algolia.com/api/v1/search_by_date?query=' + up.quote(q)
             + '&tags=show_hn&hitsPerPage=30&numericFilters=points>2,created_at_i>' + str(month_ago))
        st, b, _ = http(u, timeout=15, headers=UA)
        if st != 200 or not b:
            continue
        try:
            data = json.loads(b)
        except Exception:
            continue
        for h in data.get('hits', []):
            url = h.get('url')
            title = h.get('title') or ''
            if not url or title in seen_titles:
                continue
            seen_titles.add(title)
            try:
                hh = ok_host(up.urlparse(url).netloc)
            except Exception:
                continue
            if not hh:
                continue
            prio = 1 if re.search(r'free|trial|credits|api|openai|llm|gpt|claude', title, re.I) else 2
            if enqueue_r(c, hh, prio, 'showhn'):
                n += 1
        time.sleep(0.6)
    commit_r(c)
    return n

# ---------- BetaList (Atom: 25 свежих стартапов) ----------
def harvest_betalist(c):
    import urllib.parse as up
    st, b, _ = http('https://feeds.feedburner.com/BetaList', timeout=15, headers=UA)
    if st != 200 or not b:
        return 0
    entries = re.findall(r'<entry>(.*?)</entry>', b, re.S)
    n = 0
    for e in entries[:12]:
        t = re.search(r'<title[^>]*>(.*?)</title>', e, re.S)
        l = re.search(r'<link[^>]*href="([^"]+)"', e)
        title = t.group(1) if t else ''
        page = l.group(1).split('?')[0] if l else ''
        if not page or CJK.search(title):
            continue
        # вторая выборка: страница стартапа -> внешняя ссылка
        ps, pb, _ = http(page, timeout=12, headers=UA)
        if ps != 200 or not pb:
            continue
        cand = re.findall(r'href="(https?://(?!betalist|feedburner|google|twitter|x\.com|facebook|linkedin|instagram)[^"]+)"', pb)
        for u in cand[:4]:
            try:
                hh = ok_host(up.urlparse(u).netloc)
            except Exception:
                continue
            if hh and enqueue_r(c, hh, 1, 'betalist'):
                n += 1
                break
        time.sleep(0.8)
    commit_r(c)
    return n

# ---------- BetaBound (RSS: beta-тесты = бесплатный доступ) ----------
def harvest_betabound(c):
    import urllib.parse as up
    st, b, _ = http('https://betabound.com/feed/', timeout=15, headers=UA)
    if st != 200 or not b:
        return 0
    items = re.findall(r'<item>(.*?)</item>', b, re.S)
    n = 0
    for it in items[:10]:
        l = re.search(r'<link>(.*?)</link>', it, re.S)
        page = l.group(1).strip() if l else ''
        if not page:
            continue
        ps, pb, _ = http(page, timeout=12, headers=UA)
        if ps != 200 or not pb:
            continue
        cand = re.findall(r'href="(https?://(?!betabound|wordpress|wp\.com|gravatar|google|twitter|x\.com|facebook)[^"]+)"', pb)
        # беру первый внешний не-соц ссылку = сайт продукта
        for u in cand[:6]:
            try:
                hh = ok_host(up.urlparse(u).netloc)
            except Exception:
                continue
            if hh and enqueue_r(c, hh, 1, 'betabound'):
                n += 1
                break
        time.sleep(0.8)
    commit_r(c)
    return n

def main():
    c = db()
    before = c.execute('SELECT COUNT(*) FROM queue WHERE done=0').fetchone()[0]
    nr = harvest_reddit(c)
    np_ = harvest_pepper(c)
    npa = harvest_pastes(c)
    nhn = harvest_hn(c)
    nbl = harvest_betalist(c)
    nbb = harvest_betabound(c)
    commit_r(c)
    after = c.execute('SELECT COUNT(*) FROM queue WHERE done=0').fetchone()[0]
    total = nr + np_ + npa + nhn + nbl + nbb
    if total > 0:
        print('EXTRA-SOURCES: +%d (reddit %d, pepper %d, pastes %d, showhn %d, betalist %d, betabound %d) | queue %d->%d'
              % (total, nr, np_, npa, nhn, nbl, nbb, before, after))
    # пусто = cron ничего не шлёт

if __name__ == '__main__':
    main()
