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
               'ArtificialInteligence', 'freebies', 'slavelabour', 'aifreemium']

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

def main():
    c = db()
    before = c.execute('SELECT COUNT(*) FROM queue WHERE done=0').fetchone()[0]
    nr = harvest_reddit(c)
    np_ = harvest_pepper(c)
    npa = harvest_pastes(c)
    commit_r(c)
    after = c.execute('SELECT COUNT(*) FROM queue WHERE done=0').fetchone()[0]
    total = nr + np_ + npa
    if total > 0:
        print('EXTRA-SOURCES: +%d (reddit %d, pepper %d, pastes %d) | queue %d->%d' % (total, nr, np_, npa, before, after))
    # пусто = cron ничего не шлёт

if __name__ == '__main__':
    main()
