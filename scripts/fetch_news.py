#!/usr/bin/env python3
"""Builds news.json for the TRRXITTE apps from public X posts.

Sources, in order (first that yields posts wins):
  1. X API v2 (env X_BEARER_TOKEN): timelines of the official handles + recent search.
  2. xAI Responses API x_search tool (env XAI_API_KEY): post URLs from server-side citations,
     then enriched via the public FxTwitter API (text, author, media). Model text is never trusted
     for post content; only cited x.com status URLs are used.
If every source fails, the existing news.json is kept and marked stale (no fake posts).
Secrets never leave the Action; the output contains only public post data.
"""
import json, os, re, sys, time, datetime, urllib.request, urllib.error, urllib.parse

HANDLES = ["trrxitte", "traaitt", "traaittXTCASH", "nyantereum"]
KEYWORDS = ["trrxitte", "traaitt", "traaittXTCASH", "XTCASH", "\"TRRXITTE Ethereum\""]
OUT = os.environ.get("NEWS_OUT", "news.json")
MAX_ITEMS = 40
UA = {"User-Agent": "trrxitte-news-bot/1.0 (+https://github.com/XTEfoundation/trrxitte-news)"}

def http_json(url, headers=None, data=None, method=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={**UA, **(headers or {}), **({"Content-Type": "application/json"} if data is not None else {})},
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def iso(ts):
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ts

def clean_text(t):
    t = (t or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"(^|\s+)https://t\.co/\w+$", "", t).strip()

def fx_enrich(handle, pid):
    try:
        d = http_json(f"https://api.fxtwitter.com/{handle or 'i'}/status/{pid}", timeout=20)
        t = d.get("tweet") or {}
        if not t:
            return None
        media = []
        for m in ((t.get("media") or {}).get("all") or []):
            thumb = m.get("thumbnail_url") or m.get("url")
            if thumb:
                media.append({"type": m.get("type", "photo"), "thumb": thumb, "url": m.get("url", thumb)})
        a = t.get("author") or {}
        return {
            "id": str(t.get("id", pid)),
            "url": t.get("url") or f"https://x.com/{a.get('screen_name', handle)}/status/{pid}",
            "author": {"handle": a.get("screen_name", handle), "name": a.get("name", handle),
                       "avatar": (a.get("avatar_url") or "").replace("_normal", "_bigger")},
            "text": clean_text(t.get("text")),
            "createdAt": iso(t.get("created_timestamp")) or t.get("created_at"),
            "media": media,
            "metrics": {"likes": t.get("likes", 0), "reposts": t.get("retweets", 0), "replies": t.get("replies", 0)},
        }
    except Exception as e:
        print(f"fx enrich failed for {pid}: {e}", file=sys.stderr)
        return None

def from_x_api(token):
    h = {"Authorization": f"Bearer {token}"}
    base = "https://api.x.com/2"
    users = http_json(f"{base}/users/by?usernames={','.join(HANDLES)}&user.fields=profile_image_url,name", h).get("data", [])
    byid = {u["id"]: u for u in users}
    fields = "tweet.fields=created_at,public_metrics,attachments,author_id&expansions=attachments.media_keys,author_id&media.fields=preview_image_url,url,type&user.fields=profile_image_url,name,username"
    pages = []
    for u in users:
        pages.append(http_json(f"{base}/users/{u['id']}/tweets?max_results=10&exclude=retweets,replies&{fields}", h))
    q = urllib.parse.quote("(" + " OR ".join(KEYWORDS) + ") -is:retweet")
    try:
        pages.append(http_json(f"{base}/tweets/search/recent?max_results=25&query={q}&{fields}", h))
    except urllib.error.HTTPError as e:
        print(f"recent search unavailable: {e}", file=sys.stderr)
    items = []
    for p in pages:
        media = {m["media_key"]: m for m in (p.get("includes", {}).get("media") or [])}
        for u in (p.get("includes", {}).get("users") or []):
            byid.setdefault(u["id"], u)
        for t in p.get("data") or []:
            u = byid.get(t.get("author_id"), {})
            handle = u.get("username", "i")
            ms = []
            for k in (t.get("attachments") or {}).get("media_keys", []):
                m = media.get(k)
                if m and (m.get("url") or m.get("preview_image_url")):
                    ms.append({"type": m["type"], "thumb": m.get("preview_image_url") or m["url"], "url": m.get("url") or m.get("preview_image_url")})
            pm = t.get("public_metrics") or {}
            items.append({"id": t["id"], "url": f"https://x.com/{handle}/status/{t['id']}",
                          "author": {"handle": handle, "name": u.get("name", handle), "avatar": (u.get("profile_image_url") or "").replace("_normal", "_bigger")},
                          "text": clean_text(t.get("text")), "createdAt": t.get("created_at"), "media": ms,
                          "metrics": {"likes": pm.get("like_count", 0), "reposts": pm.get("retweet_count", 0), "replies": pm.get("reply_count", 0)}})
    return items, "x-api-v2"

STATUS_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)")

def from_xai(key):
    since = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    body = {
        "model": os.environ.get("XAI_MODEL", "grok-4.7"),
        "input": "List the most recent X posts from these accounts and recent posts mentioning TRRXITTE, traaitt, XTE (traaitt) or XTCASH. "
                 "Reply only with the post URLs, one per line.",
        "tools": [{"type": "x_search", "allowed_x_handles": HANDLES, "from_date": since}],
        "max_turns": 3,
    }
    d = http_json("https://api.x.ai/v1/responses", {"Authorization": f"Bearer {key}"}, body, "POST", timeout=180)
    urls = set(u for u in d.get("citations") or [] if isinstance(u, str))
    for out in d.get("output") or []:
        for c in out.get("content") or []:
            for a in c.get("annotations") or []:
                if a.get("url"):
                    urls.add(a["url"])
    items = []
    for m in {STATUS_RE.search(u).groups() for u in urls if STATUS_RE.search(u)}:
        it = fx_enrich(*m)
        if it:
            items.append(it)
    return items, "xai-x_search+fxtwitter"

def main():
    prev = {}
    if os.path.exists(OUT):
        try: prev = json.load(open(OUT))
        except Exception: prev = {}
    items, source, errors = [], None, []
    for env, fn in (("X_BEARER_TOKEN", from_x_api), ("XAI_API_KEY", from_xai)):
        if not os.environ.get(env):
            errors.append(f"{env} not set"); continue
        try:
            items, source = fn(os.environ[env])
            if items: break
            errors.append(f"{fn.__name__}: no posts")
        except Exception as e:
            msg = str(e)
            if isinstance(e, urllib.error.HTTPError):
                try: msg += " " + e.read().decode()[:200]
                except Exception: pass
            errors.append(f"{fn.__name__}: {msg}")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if items:
        merged = {i["id"]: i for i in (prev.get("items") or [])}
        merged.update({i["id"]: i for i in items})
        allitems = sorted(merged.values(), key=lambda i: i.get("createdAt") or "", reverse=True)[:MAX_ITEMS]
        out = {"version": 1, "generatedAt": now, "lastSuccessAt": now, "source": source, "stale": False,
               "handles": HANDLES, "items": allitems}
    else:
        out = {**prev, "version": 1, "generatedAt": now, "stale": True, "handles": HANDLES,
               "items": prev.get("items") or [], "lastError": "; ".join(errors)[:500]}
    json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)
    print(f"{'updated' if items else 'kept previous (stale)'}: {len(out['items'])} items; source={out.get('source')}; errors={errors}")

if __name__ == "__main__":
    main()
