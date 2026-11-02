# trrxitte-news

Public, sanitized feed of recent X posts about TRRXITTE / traaitt / XTE / XTCASH, consumed by the
TRRXITTE iOS, iPadOS, macOS, tvOS and watchOS apps.

**Feed URL:** https://raw.githubusercontent.com/XTEfoundation/trrxitte-news/main/news.json

Accounts: [@trrxitte](https://x.com/trrxitte), [@traaitt](https://x.com/traaitt),
[@traaittXTCASH](https://x.com/traaittXTCASH), [@nyantereum](https://x.com/nyantereum).

The `Refresh X news feed` workflow runs every 15 minutes (`scripts/fetch_news.py`):

1. `X_BEARER_TOKEN` secret → X API v2 timelines + recent search, or
2. `XAI_API_KEY` secret → xAI Responses API `x_search` (only cited x.com post URLs are used),
   enriched with public post data from FxTwitter.

If no source works, the previous posts are kept and `stale: true` is set. No secrets are ever
written to the feed or shipped in the apps.

Schema: `{version, generatedAt, lastSuccessAt, source, stale, handles[], items[{id, url, author{handle,name,avatar}, text, createdAt, media[{type,thumb,url}], metrics{likes,reposts,replies}}]}`
