"""JLCPCB parts-library client (CPython, stdlib only) - THE one sanctioned JLC stock / C-number / library lookup:
    python jlc_api.py C860407 RT0603BRB0747KL ...   one line per part (C-number = exact code, anything else = MPN)
    python jlc_api.py --maker Nexperia BAT54S       MPN lookups only accept that maker (else: other_maker)
    python jlc_api.py --json C860407                structured JSON instead of text
    exit code: 0 every part found, 1 a lookup failed (network / block / bad reply), 3 a part was not found, had no
    exact MPN match, was ambiguous (same MPN from several makers - never resolved by stock) or was inconclusive
    BOM refresh: python scripts/bom.py refresh --jlc --only MPN[,MPN] (targeted) / --full - it calls
    snapshot_rows() below and stores the observations in bom/bom.json (this client writes no BOM file)
    python jlc_api.py --search "10uF 0805" [--pages 2] [--library base|expand|preferred] [--in-stock]
    common: --no-cache (always fetch, still refreshes the cache), --max-age HOURS (default 12), --qty N (price qty;
    default: the BOM need of that C-number / MPN from bom/bom.json, else SETS)
Never write an ad-hoc JLC / LCSC scraper in this repo: extend this file instead (and scripts/test_jlc_api.py).

Endpoint (JLC's own parts-library search, the one jlcpcb.com/parts uses; no key, no cookie):
    POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList
    body {"keyword": str, "currentPage": 1.., "pageSize": 1..100}  + optional filters (verified 2026-09-29):
      "componentLibraryType": "base" | "expand"   basic / extended only
      "preferredComponentFlag": true              preferred (extended) parts only - do NOT combine with
                                                  componentLibraryType (JLC then silently ignores the flag)
      "stockFlag": true                           in-stock parts only
    Keyword matching is fuzzy (a C-number query also returns e.g. a "JLCPCB Assembly" listing whose model IS that
    C-number); one keyword per request (a second word is ANDed / dropped, never an OR list).
    A short C-number (C25, C100) matches tens of thousands of codes and the exact one is often not in the first
    hundreds of hits: by_code pages a bounded amount and then says "inconclusive", never "not found".
Reply: HTTP 200 JSON {"code": 200, "message": null, "data": {"componentPageInfo": {"total", "pages", "pageSize",
    "list": [item, ...] | null (null when total = 0)}, ...}}. A page past the last one gives componentPageInfo null
    (or total 0); on page 1 that shape - or data null, or items without componentCode - means the API changed and
    raises JlcBadResponse (never cached, never reported as "not found"). A bad request is still HTTP 200 but
    {"success": false, "code": 101, "message": "<Chinese text>", "data": null}. Per item (types seen in 2 948 items):
    componentCode "C15850", componentModelEn (MPN), componentBrandEn (maker; "JLCPCB Assembly" = JLC's own
    placeholder listing, C99... codes), stockCount int = JLC ASSEMBLY stock (not LCSC's), componentLibraryType
    "base" | "expand", preferredComponentFlag bool, componentPrices [{startNumber, endNumber (-1 = open), productPrice
    USD}], componentSpecificationEn (package), describe, firstSortName / secondSortName, dataManualUrl (null ~8 %),
    lcscGoodsUrl (null ~8 %), attributes [{attribute_name_en, attribute_value_name}] (null ~2 %), lossNumber
    (attrition parts per order), leastPatchNumber, minPurchaseNum, canPresaleNumber, isBuyComponent "1" / "0" (string)
    + noBuyReason, urlSuffix (part page). Every field is parsed defensively here: missing / null / differently typed
    values become None, never a crash. Text contains non-ASCII (degree C, Ohm, CJK) - output is forced to UTF-8.
Politeness / robustness: every request has a 30 s timeout; a machine-wide cross-process lock (%TEMP%/din8r_jlc_api/,
override JLC_API_LOCK_DIR) serialises requests from parallel agents (also from scratch copies of the repo) and keeps
>= 1.2 s between them. Waiters queue first-come first-served (ticket files in queue/), and the wait only times out
after LOCK_WAIT s WITHOUT progress, so a lookup queued behind a long BOM refresh waits its turn instead of failing.
Retries (<= 4 tries, exponential backoff + jitter) only on timeouts, connection errors, HTTP 5xx and HTTP 429.
A 429's Retry-After (<= 60 s) is written to %TEMP%/din8r_jlc_api/.cooldown so EVERY process waits it out; a longer one
(or a 429 that persists) fails loudly and parks every process like a block. HTTP 403, HTML / bot-challenge pages,
non-JSON and error-code replies are NOT retried: they raise at once, and a bot page / 403 also parks every process for
15 min (%TEMP%/din8r_jlc_api/.blocked - delete it to override). A BOM refresh stops after 3 consecutive failed
lookups.
Replies are cached on disk (bom/.jlc_api_cache/, git-ignored, keyed by the request body, 12 h TTL).
"""
import argparse
import hashlib
import http.client
import json
import math
import os
import random
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
PART_PAGE = "https://jlcpcb.com/partdetail/{}"
BOM_JSON = ROOT / "bom" / "bom.json"          # read only (needs for the CLI)
# Attrition (owner 2026-10-04, "more realistic attrition"): JLC does not publish its attrition rule, and the parts
# API's lossNumber is a per-listing figure fetched WITHOUT the order quantity (0 for most ICs). Plan / reserve
# need + max(lossNumber, ceil(ATTRITION_RATE x need), ATTRITION_FLOOR); JLC's BOM quote screen is the authority.
ATTRITION_RATE = 0.05
ATTRITION_FLOOR = 2
CACHE_DIR = ROOT / "bom" / ".jlc_api_cache"
# lock / request stamp / block marker: machine-wide (not per repo copy), so agents working in scratch copies of the
# repo still queue behind each other
LOCK_DIR = Path(os.environ.get("JLC_API_LOCK_DIR") or Path(tempfile.gettempdir()) / "din8r_jlc_api")
USER_AGENT = "din8r-jlc_api/1.0 (python urllib; parts lookup, <= 1 req/s)"

TIMEOUT = 30              # s per request
MIN_INTERVAL = 1.2        # s between two requests, across all processes
MAX_TRIES = 4             # per request, transient errors only
BACKOFF_BASE = 2.0        # s, doubled per try, + up to 1 s jitter
BACKOFF_CAP = 30.0        # s
RETRY_AFTER_CAP = 60      # s; a longer Retry-After fails loudly instead of waiting
LOCK_WAIT = 300           # s of NO progress (queue not moving, no request sent) before a waiter gives up
TICKET_STALE = 15         # s: a queue ticket not refreshed for this long belongs to a dead process and is dropped
BLOCK_COOLDOWN = 900      # s every process stays off JLC after a bot page / 403 / persistent 429
RATE_PARK_MAX = 3600      # s: longest park after a 429 whose Retry-After is over RETRY_AFTER_CAP
BOM_MAX_CONSECUTIVE_FAILS = 3   # a BOM refresh stops after this many failed lookups in a row (endpoint down / changed)
CNUM_SCAN_PAGES = 3       # by_code: extra pages of 100 fuzzy hits to scan when the code is not in the first 25
CACHE_SKEW_S = 300        # s: a cache entry dated further in the future than this is ignored
DEFAULT_MAX_AGE_H = 12.0  # cache TTL
PAGE_SIZE_MAX = 100
SETS = 18                 # the order: 18 PCBA sets; must equal bom.JLC_SETS (tested)
PLACEHOLDER_MAKER = "JLCPCB Assembly"
C_RE = re.compile(r"C\d+", re.I)
NOT_FOUND_STATES = ("not_found", "no_exact", "ambiguous", "other_maker", "inconclusive")

_transport_hook = None    # tests replace this: fn(data: bytes) -> (status, headers: dict, raw: bytes)
_sleep = time.sleep       # tests replace this


# --------------------------------------------------------------------------------------------------------- errors
class JlcError(RuntimeError):
    """Any JLC lookup failure. The message says what happened and what to do; callers print it and stop."""


class JlcBlocked(JlcError):
    """403 / HTML / bot-challenge page: never retried, parks all processes for BLOCK_COOLDOWN."""


class JlcRateLimited(JlcError):
    """429 with a Retry-After longer than RETRY_AFTER_CAP, or still 429 after MAX_TRIES."""


class JlcBadResponse(JlcError):
    """Non-JSON body, unexpected JSON shape, or an error code in the JSON body (e.g. code 101 = bad request)."""


class JlcTransient(JlcError):
    """Timeouts / connection errors / 5xx that persisted through MAX_TRIES tries."""


# ----------------------------------------------------------------------------------------------- typed accessors
def _str(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return None


def _int(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v == v and abs(v) != float("inf") else None
    if isinstance(v, str):
        try:
            return int(float(v.strip().replace(",", "")))
        except ValueError:
            return None
    return None


def _float(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "").lstrip("$"))
        except ValueError:
            return None
    return None


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y"):
            return True
        if s in ("0", "false", "no", "n"):
            return False
    return None


def _list(v):
    return v if isinstance(v, list) else []


def _dict(v):
    return v if isinstance(v, dict) else {}


def norm_mpn(s):
    """Exact-match key: upper case, all whitespace removed."""
    return re.sub(r"\s+", "", s or "").upper()


def _alnum(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def maker_tokens(s):
    """Maker name -> lower-case word tokens, accents folded ('Wurth' = 'Würth'); non-ASCII scripts (CJK) are kept,
    not dropped, so an all-CJK maker name never collapses to an empty string."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.findall(r"[^\W_]+", s.lower())


def norm_maker(s):
    return "".join(maker_tokens(s))


def makers_agree(a, b):
    """Maker comparison: equal ignoring case / punctuation / spacing, or one name's WHOLE words are the leading words
    of the other ('Vishay Intertech' ~ 'Vishay Intertech (Vishay Draloric)', 'SAMSUNG' ~ 'Samsung Electro-Mechanics').
    No partial-word prefixes ('Microchip Tech' != 'Micro Commercial Components', 'Analog Devices' != 'ANALOGY').
    A blank / missing name on either side means 'no expectation' and agrees; '--' (JLC's no-brand) does not."""
    if not (a or "").strip() or not (b or "").strip():
        return True
    x, y = maker_tokens(a), maker_tokens(b)
    if not x or not y:
        return x == y
    if "".join(x) == "".join(y):
        return True
    short, long_ = sorted((x, y), key=len)
    return long_[:len(short)] == short


def same_maker(a, b):
    """makers_agree, but a blank / missing name is NOT a match (used to pick or group listings)."""
    return bool((a or "").strip() and (b or "").strip() and makers_agree(a, b))


# ------------------------------------------------------------------------------------------------ result objects
@dataclass
class Part:
    code: str = None
    mpn: str = None
    maker: str = None
    stock: int = None                 # JLC assembly stock (NOT LCSC stock)
    library: str = None               # "base" | "expand" | None
    preferred: bool = False
    package: str = None
    description: str = None
    category: str = None
    datasheet: str = None
    lcsc_url: str = None
    jlc_url: str = None
    loss: int = None                  # attrition parts JLC adds per order
    least_patch: int = None
    min_purchase: int = None
    presale: int = None
    buyable: bool = None
    no_buy_reason: str = None
    prices: list = field(default_factory=list)       # [[start, end | None, unit USD], ...] ascending
    attributes: dict = field(default_factory=dict)   # {name: value}

    @classmethod
    def from_raw(cls, it):
        it = _dict(it)
        prices = []
        for p in _list(it.get("componentPrices")):
            p = _dict(p)
            start, end, price = _int(p.get("startNumber")), _int(p.get("endNumber")), _float(p.get("productPrice"))
            if start is None or price is None:
                continue
            prices.append([start, end if end is not None and end >= 0 else None, price])
        prices.sort(key=lambda b: b[0])
        attrs = {}
        for a in _list(it.get("attributes")):
            a = _dict(a)
            k = _str(a.get("attribute_name_en"))
            if k:
                attrs[k] = _str(a.get("attribute_value_name"))
        lib = _str(it.get("componentLibraryType"))
        suffix = _str(it.get("urlSuffix"))
        code = _str(it.get("componentCode"))
        cat = " / ".join(x for x in (_str(it.get("firstSortName")), _str(it.get("secondSortName"))) if x) or None
        return cls(code=code.upper() if code else None, mpn=_str(it.get("componentModelEn")),
                   maker=_str(it.get("componentBrandEn")), stock=_int(it.get("stockCount")),
                   library=lib.lower() if lib else None, preferred=bool(_bool(it.get("preferredComponentFlag"))),
                   package=_str(it.get("componentSpecificationEn")), description=_str(it.get("describe")),
                   category=cat, datasheet=_str(it.get("dataManualUrl")), lcsc_url=_str(it.get("lcscGoodsUrl")),
                   jlc_url=PART_PAGE.format(suffix) if suffix else (PART_PAGE.format(code) if code else None),
                   loss=_int(it.get("lossNumber")), least_patch=_int(it.get("leastPatchNumber")),
                   min_purchase=_int(it.get("minPurchaseNum")), presale=_int(it.get("canPresaleNumber")),
                   buyable=_bool(it.get("isBuyComponent")), no_buy_reason=_str(it.get("noBuyReason")),
                   prices=prices, attributes=attrs)

    @property
    def library_label(self):
        """basic | preferred | extended (JLC's three fee classes), '?' if the reply had no library type."""
        if self.library == "base":
            return "basic"
        if self.library == "expand":
            return "preferred" if self.preferred else "extended"
        return self.library or "?"

    @property
    def placeholder(self):
        """JLC's own 'JLCPCB Assembly' listing (C99... code, often 0 stock) - never the maker's part."""
        return (self.maker or "").strip().lower() == PLACEHOLDER_MAKER.lower()

    def price_at(self, qty):
        """Unit price (USD) at an order quantity, from the break table; None if JLC gave no prices."""
        if not self.prices:
            return None
        qty = max(int(qty or 1), 1)
        best = self.prices[0][2]
        for start, end, price in self.prices:
            if qty >= start:
                best = price
            if start <= qty and (end is None or qty <= end):
                return price
        return best

    def order_qty(self, need):
        """What to buy / reserve for `need` placements: need + attrition(need, lossNumber)."""
        return int(need) + attrition(need, self.loss)

    def to_dict(self):
        d = asdict(self)
        d["library_label"] = self.library_label
        d["placeholder"] = self.placeholder
        return d


@dataclass
class SearchPage:
    keyword: str
    page: int
    page_size: int
    total: int
    pages: int
    items: list                        # [Part]
    fetched_utc: str = None
    from_cache: bool = False

    def to_dict(self):
        return {"keyword": self.keyword, "page": self.page, "page_size": self.page_size, "total": self.total,
                "pages": self.pages, "fetched_utc": self.fetched_utc, "from_cache": self.from_cache,
                "items": [p.to_dict() for p in self.items]}


@dataclass
class Lookup:
    query: str
    kind: str                          # "cnum" | "mpn"
    # "ok" | "error" | C-number: "not_found" | "inconclusive" (fuzzy hits too many to scan)
    #                | MPN: "no_exact" | "ambiguous" (same MPN from > 1 maker) | "other_maker" (--maker not among them)
    status: str
    part: Part = None                  # the exact match; None unless status == "ok"
    also_exact: list = field(default_factory=list)   # other listings with the same MPN (reel codes, other makers)
    near: list = field(default_factory=list)         # similar MPNs - reported, NEVER picked
    error: str = None
    error_kind: str = None             # exception class name, e.g. JlcBlocked
    fetched_utc: str = None
    note: str = None                   # why a lookup is ambiguous / inconclusive / other_maker

    def to_dict(self):
        return {"query": self.query, "kind": self.kind, "status": self.status, "error": self.error,
                "error_kind": self.error_kind, "note": self.note,
                "fetched_utc": self.fetched_utc, "part": self.part.to_dict() if self.part else None,
                "also_exact": [p.to_dict() for p in self.also_exact], "near": [p.to_dict() for p in self.near]}


# ------------------------------------------------------------------------------------------------- lock + spacing
def _try_lock(fh):
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh):
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _read_float(path, key=None):
    """A float from a stamp file (plain number, or a JSON object's `key`); 0.0 if missing / unreadable / not finite."""
    try:
        txt = path.read_text(encoding="utf-8").strip()
        v = float(json.loads(txt).get(key, 0)) if key else float(txt)
    except (OSError, ValueError, AttributeError, TypeError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _unlink(path):
    try:
        path.unlink()
    except OSError:
        pass


class _Throttle:
    """Cross-process mutex around one HTTP request, first-come first-served, + >= MIN_INTERVAL since the previous
    request of ANY process (and past any shared 429 cool-down).

    Fairness: every waiter drops a ticket file (queue/<time_ns>-<pid>-<rand>.t) and only the oldest live ticket may
    take the lock, so a process that does many requests back to back cannot starve the others (a released lock is
    otherwise re-taken by its holder within milliseconds). Waiters refresh their ticket's mtime while they wait; a
    ticket not refreshed for TICKET_STALE s belongs to a dead process and is dropped. LOCK_WAIT is a NO-PROGRESS
    timeout: it restarts whenever the queue ahead shrinks or another request is sent."""

    sent = False

    def __enter__(self):
        _Throttle.sent = False
        qdir = LOCK_DIR / "queue"
        qdir.mkdir(parents=True, exist_ok=True)
        self.ticket = qdir / f"{time.time_ns():020d}-{os.getpid()}-{random.getrandbits(32):08x}.t"
        self.ticket.touch()
        self.fh = open(LOCK_DIR / ".lock", "a+b")
        try:
            self._wait_turn(qdir)
        except BaseException:
            _unlink(self.ticket)
            self.fh.close()
            raise
        _unlink(self.ticket)                                 # holding the lock now: leave the queue
        now = time.time()
        ready = max(_read_float(LOCK_DIR / ".last_request") + MIN_INTERVAL,
                    _read_float(LOCK_DIR / ".cooldown", "until"))
        wait = ready - now
        if wait > 0:
            _sleep(min(wait, RETRY_AFTER_CAP + 2.0))
        return self

    def _ahead(self, qdir):
        """Live tickets older than ours (stale ones are removed on the way)."""
        mine, now, out = self.ticket.name, time.time(), []
        try:
            names = sorted(e.name for e in os.scandir(qdir) if e.name.endswith(".t"))
        except OSError:
            return out
        for n in names:
            if n >= mine:
                break
            p = qdir / n
            try:
                if now - p.stat().st_mtime > TICKET_STALE:
                    _unlink(p)
                    continue
            except OSError:
                continue                                     # vanished: its owner got the lock
            out.append(n)
        return out

    def _wait_turn(self, qdir):
        mark, deadline = None, time.monotonic() + LOCK_WAIT
        while True:
            ahead = self._ahead(qdir)
            if not ahead:
                try:
                    _try_lock(self.fh)
                    return
                except OSError:
                    pass
            m = (len(ahead), _read_float(LOCK_DIR / ".last_request"))
            if m != mark:
                mark, deadline = m, time.monotonic() + LOCK_WAIT
            elif time.monotonic() > deadline:
                raise JlcError(f"jlc_api: no progress in the request queue ({LOCK_DIR}) for {LOCK_WAIT} s "
                               f"({len(ahead)} waiter(s) ahead, lock {'free' if not ahead else 'held'}) - is a "
                               "jlc_api process hung? Retry later.")
            try:
                os.utime(self.ticket)                        # still alive
            except OSError:
                try:
                    self.ticket.touch()                      # dropped as stale (we were descheduled): same place
                except OSError:
                    pass
            time.sleep(0.1)

    def __exit__(self, *exc):
        if _Throttle.sent:
            try:
                (LOCK_DIR / ".last_request").write_text(f"{time.time():.3f}", encoding="utf-8")
            except OSError:
                pass
        _unlock(self.fh)
        self.fh.close()
        return False


def _check_block():
    f = LOCK_DIR / ".blocked"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        until = float(d.get("until", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        return
    if until > time.time():
        raise JlcBlocked(f"jlc_api: JLC answered with a block / bot page at {d.get('at')} ({d.get('reason')}); all "
                         f"lookups are parked for {int(until - time.time())} s more. Do NOT work around it (no "
                         f"browser, no CAPTCHA, no other scraper); wait, or delete {f} if you know it is cleared.")


def _set_block(reason, seconds=BLOCK_COOLDOWN):
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        (LOCK_DIR / ".blocked").write_text(json.dumps({
            "until": time.time() + seconds, "reason": reason,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    except OSError:
        pass


def _set_cooldown(seconds):
    """Shared 429 cool-down: no process sends before `until` (read by _Throttle)."""
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        until = max(time.time() + seconds, _read_float(LOCK_DIR / ".cooldown", "until"))
        (LOCK_DIR / ".cooldown").write_text(json.dumps({"until": until}), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------- transport
def _transport(data):
    """One HTTP POST. Returns (status, headers dict, body bytes); network errors propagate."""
    if _transport_hook is not None:
        return _transport_hook(data)
    req = urllib.request.Request(URL, data=data, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:                                   # noqa: BLE001 - body of an error reply is best-effort
            raw = b""
        return e.code, dict(e.headers or {}), raw


# OSError covers socket timeouts, resets, DNS failures (URLError) and TLS errors
_TRANSIENT_EXC = (OSError, http.client.HTTPException)
_CHALLENGE = (b"captcha", b"just a moment", b"cf-chl", b"challenge-platform", b"verify you are human",
              b"slide to verify", b"access denied", b"attention required", b"are you a robot", b"window.location")


def _header(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _looks_like_html(raw, ctype):
    """Not JSON and HTML-ish (content type or a leading '<')."""
    head = (raw or b"")[:4096].lstrip().lower()
    if head[:1] in (b"{", b"["):
        return False
    return "html" in (ctype or "").lower() or head.startswith(b"<")


def _is_challenge(raw, ctype):
    """A bot wall / block page - as opposed to a proxy's plain HTML error page."""
    return _looks_like_html(raw, ctype) and any(m in (raw or b"")[:8192].lower() for m in _CHALLENGE)


def _retry_after(headers):
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date); 5 s when missing / unparseable /
    not finite ('nan', 'inf')."""
    v = _header(headers, "Retry-After")
    if v is None:
        return 5.0
    try:
        s = float(v)
    except (TypeError, ValueError):
        try:
            s = (parsedate_to_datetime(v) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, IndexError, OverflowError):
            return 5.0
    return max(s, 0.0) if math.isfinite(s) else 5.0


def _backoff(attempt):
    return min(BACKOFF_BASE * 2 ** (attempt - 1), BACKOFF_CAP) + random.uniform(0, 1.0)


def _shape_problem(d, body):
    """None if a code-200 reply has the shape this client understands, else what is wrong. Observed live 2026-09-29:
    no hits = componentPageInfo {total 0, list null}; a page past the last one = componentPageInfo null (page >= 2
    only). Anything else - data null, page 1 without componentPageInfo, a non-list 'list', a first page that claims
    hits but lists none, items without a componentCode - means JLC changed the API: it must never read as 'not found'."""
    data = d.get("data")
    if not isinstance(data, dict):
        return f"'data' is {type(data).__name__}, not an object"
    info = data.get("componentPageInfo")
    page = _int(body.get("currentPage")) or 1
    if info is None:
        return None if page > 1 else "no 'componentPageInfo' on page 1"
    if not isinstance(info, dict):
        return f"'componentPageInfo' is {type(info).__name__}"
    lst = info.get("list")
    if lst is not None and not isinstance(lst, list):
        return f"'list' is {type(lst).__name__}"
    total = _int(info.get("total"))
    if total is None and "total" in info and info.get("total") is not None:
        return f"'total' is {info.get('total')!r}"
    if lst:
        if not any(isinstance(it, dict) and _str(it.get("componentCode")) for it in lst):
            return f"{len(lst)} item(s), none with a componentCode"
    elif page == 1 and (total or 0) > 0:
        return f"total {total} but no items on page 1"
    return None


def _request(body, cache_hit=None):
    """POST `body`, return the decoded JSON dict (code 200). cache_hit(): re-checked under the lock, so N agents
    asking the same question at once cost one request."""
    _check_block()
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    last = None
    for attempt in range(1, MAX_TRIES + 1):
        wait = None
        with _Throttle():
            if cache_hit is not None:
                hit = cache_hit()
                if hit is not None:
                    return hit
            _Throttle.sent = True
            try:
                status, headers, raw = _transport(data)
            except _TRANSIENT_EXC as e:
                status, headers, raw = None, {}, b""
                last = f"{type(e).__name__}: {e}"
        if status is not None:
            ctype = _header(headers, "Content-Type") or ""
            if status == 429:
                ra = _retry_after(headers)
                last = f"HTTP 429 (Retry-After {ra:.0f} s)"
                if ra > RETRY_AFTER_CAP:
                    park = int(min(ra, RATE_PARK_MAX))
                    _set_block(f"HTTP 429, Retry-After {ra:.0f} s", park)
                    raise JlcRateLimited(f"jlc_api: JLC rate limit, Retry-After {ra:.0f} s > {RETRY_AFTER_CAP} s cap "
                                         f"- all jlc_api calls are parked for {park} s; retry later (do not loop).")
                _set_cooldown(ra + random.uniform(0, 1.0))   # every process waits it out (in _Throttle)
                wait = 0.0
            elif status == 403 or _is_challenge(raw, ctype):
                reason = f"HTTP {status}, {ctype or 'no content-type'}, body starts {raw[:80]!r}"
                _set_block(reason)
                raise JlcBlocked(f"jlc_api: JLC returned a block / bot-challenge page ({reason}). Not retried; all "
                                 f"jlc_api calls are parked for {BLOCK_COOLDOWN // 60} min. Never attempt a CAPTCHA "
                                 "or a workaround scraper - retry later.")
            elif status < 500 and _looks_like_html(raw, ctype):
                raise JlcBadResponse(f"jlc_api: JLC answered HTML instead of JSON (HTTP {status}, {ctype}, starts "
                                     f"{raw[:80]!r}) - the endpoint may have moved; not retried. Fix jlc_api.py.")
            elif 500 <= status < 600:                       # incl. a proxy's plain HTML error page
                last = f"HTTP {status}"
            elif status != 200:
                raise JlcError(f"jlc_api: HTTP {status} from JLC ({ctype}): {raw[:200]!r}")
            else:
                try:
                    d = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise JlcBadResponse(f"jlc_api: JLC reply is not JSON ({ctype}, {len(raw)} B, starts "
                                         f"{raw[:80]!r}). Not retried.") from None
                if not isinstance(d, dict):
                    raise JlcBadResponse(f"jlc_api: unexpected JSON ({type(d).__name__}), not retried.")
                code = _int(d.get("code"))
                if code != 200 or d.get("success") is False:
                    raise JlcBadResponse(f"jlc_api: JLC error code {d.get('code')}: {d.get('message')!r} for body "
                                         f"{body} - request rejected, not retried (fix the request).")
                problem = _shape_problem(d, body)
                if problem:
                    raise JlcBadResponse(f"jlc_api: JLC reply has an unexpected shape ({problem}) for body {body} - "
                                         "the API may have changed; not retried, not cached. Fix jlc_api.py.")
                return d
        if attempt < MAX_TRIES and wait != 0.0:              # a 429 waits in _Throttle (shared cool-down)
            _sleep(wait if wait is not None else _backoff(attempt))
    if last and last.startswith("HTTP 429"):
        _set_block(f"still HTTP 429 after {MAX_TRIES} tries")
        raise JlcRateLimited(f"jlc_api: still rate-limited after {MAX_TRIES} tries ({last}) - all jlc_api calls are "
                             f"parked for {BLOCK_COOLDOWN // 60} min; retry later.")
    raise JlcTransient(f"jlc_api: JLC unreachable after {MAX_TRIES} tries ({last}) - retry later.")


# -------------------------------------------------------------------------------------------------------- cache
def _cache_file(body):
    key = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{key}.json"


def _cache_read(body, max_age_s):
    """The cached record for `body` if it is fresh (0 <= age <= max_age_s, small clock skew tolerated) and has a
    shape this client understands; else None. One retry on PermissionError: on Windows a reader can hit the file while
    another process's os.replace() swaps it in."""
    if max_age_s is None or max_age_s <= 0:
        return None
    f = _cache_file(body)
    for attempt in (1, 2):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            break
        except PermissionError:
            if attempt == 2:
                return None
            time.sleep(0.05)
        except (OSError, ValueError):
            return None
    try:
        if rec.get("body") != body or not isinstance(rec.get("response"), dict):
            return None
        fetched = float(rec.get("fetched", 0))
        age = time.time() - fetched
        if not math.isfinite(age) or age > max_age_s or age < -CACHE_SKEW_S:
            return None
        if _shape_problem(rec["response"], body):
            return None
        return rec
    except (ValueError, TypeError, AttributeError):
        return None


def _cache_write(body, response):
    rec = {"fetched": time.time(), "body": body, "response": response}
    tmp = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = _cache_file(body)
        tmp = f.with_name(f"{f.stem}.{os.getpid()}.{random.getrandbits(32):08x}.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        if tmp is not None:
            _unlink(tmp)                                    # never leave orphan .tmp files in the cache
    return rec


def _utc(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(body, use_cache=True, max_age_h=DEFAULT_MAX_AGE_H):
    """(response dict, fetched_utc, from_cache) for a raw request body, via the cache."""
    max_age_s = max_age_h * 3600.0 if use_cache and max_age_h else 0
    rec = _cache_read(body, max_age_s)
    if rec is not None:
        return rec["response"], _utc(rec["fetched"]), True
    holder = {}

    def hit():
        r = _cache_read(body, max_age_s)
        if r is not None:
            holder["rec"] = r
            return r["response"]
        return None
    d = _request(body, cache_hit=hit if max_age_s else None)
    if "rec" in holder:
        return d, _utc(holder["rec"]["fetched"]), True
    rec = _cache_write(body, d)
    return d, _utc(rec["fetched"]), False


# ---------------------------------------------------------------------------------------------------- lookups
def build_body(keyword, page=1, page_size=25, library=None, in_stock=False):
    kw = (keyword or "").strip()
    if not kw:
        raise ValueError("jlc_api: empty keyword")
    page_size = int(page_size)
    if not 1 <= page_size <= PAGE_SIZE_MAX:
        raise ValueError(f"jlc_api: page_size must be 1..{PAGE_SIZE_MAX}")
    body = {"keyword": kw, "currentPage": max(int(page), 1), "pageSize": page_size}
    if library in ("base", "basic"):
        body["componentLibraryType"] = "base"
    elif library in ("expand", "extended"):
        body["componentLibraryType"] = "expand"
    elif library == "preferred":
        body["preferredComponentFlag"] = True          # alone: combined with a library type JLC ignores it
    elif library:
        raise ValueError(f"jlc_api: library must be base | expand | preferred, not {library!r}")
    if in_stock:
        body["stockFlag"] = True
    return body


def search(keyword, page=1, page_size=25, library=None, in_stock=False, use_cache=True,
           max_age_h=DEFAULT_MAX_AGE_H):
    body = build_body(keyword, page, page_size, library, in_stock)
    d, fetched, cached = fetch(body, use_cache, max_age_h)
    info = _dict(_dict(d.get("data")).get("componentPageInfo"))
    items = [Part.from_raw(it) for it in _list(info.get("list")) if isinstance(it, dict)]
    total = _int(info.get("total")) or 0
    pages = _int(info.get("pages")) or (1 if items else 0)
    return SearchPage(keyword=body["keyword"], page=body["currentPage"], page_size=page_size, total=total,
                      pages=pages, items=items, fetched_utc=fetched, from_cache=cached)


def search_all(keyword, max_pages=3, page_size=50, **kw):
    """Up to max_pages pages -> (total, [Part], fetched_utc of the first page)."""
    out, total, fetched = [], 0, None
    for p in range(1, max(int(max_pages), 1) + 1):
        pg = search(keyword, page=p, page_size=page_size, **kw)
        total, fetched = pg.total, fetched or pg.fetched_utc
        out += pg.items
        if len(pg.items) < page_size or p >= pg.pages or len(out) >= total:
            break
    return total, out, fetched


def is_cnum(q):
    return bool(C_RE.fullmatch((q or "").strip()))


def by_code(code, **kw):
    """Exact C-number -> Lookup (status ok | not_found | inconclusive | error). The keyword search is fuzzy: page 1
    (25 hits) settles every C-number of 4+ digits seen so far; if the code is not there and JLC reports more hits,
    up to CNUM_SCAN_PAGES pages of 100 are scanned. 'not_found' only when every hit was scanned."""
    c = code.strip().upper()
    try:
        pg = search(c, page_size=25, **kw)
        hit = next((p for p in pg.items if p.code == c), None)
        scanned, total, fetched = len(pg.items), pg.total, pg.fetched_utc
        page = 0
        while hit is None and scanned < total and page < CNUM_SCAN_PAGES:
            page += 1
            more = search(c, page=page, page_size=PAGE_SIZE_MAX, **kw)
            hit = next((p for p in more.items if p.code == c), None)
            scanned = max(scanned, (page - 1) * PAGE_SIZE_MAX + len(more.items))
            if len(more.items) < PAGE_SIZE_MAX:
                break
    except JlcError as e:
        return Lookup(c, "cnum", "error", error=str(e), error_kind=type(e).__name__)
    if hit:
        return Lookup(c, "cnum", "ok", part=hit, fetched_utc=fetched)
    if scanned < total:
        return Lookup(c, "cnum", "inconclusive", fetched_utc=fetched,
                      note=f"not among the first {scanned} of {total} fuzzy hits for {c} - existence not confirmed "
                           "(short C-numbers match too many codes); check the part page " + PART_PAGE.format(c))
    return Lookup(c, "cnum", "not_found", fetched_utc=fetched)


def _edit_distance_le(a, b, k):
    """True if the Levenshtein distance of a and b is <= k (banded, O(len * k))."""
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [k + 1] * len(b)
        lo, hi = max(1, i - k), min(len(b), i + k)
        for j in range(lo, hi + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        if min(cur[max(0, lo - 1):hi + 1]) > k:
            return False
        prev = cur
    return prev[len(b)] <= k


def _near(q, mpn):
    """Similar MPN worth showing (never picked): same letters / digits ignoring punctuation, one a prefix of the other
    (>= 5 chars), or 1 character off (2 for MPNs of 10+ chars) - e.g. RT0603BRB0747KL vs RT0603BRD0747KL."""
    a, b = _alnum(q), _alnum(mpn)
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 5 and (a.startswith(b) or b.startswith(a))):
        return True
    n = min(len(a), len(b))
    return n >= 6 and _edit_distance_le(a, b, 2 if n >= 10 else 1)


def _names(names, n=6):
    return ", ".join(names[:n]) + (f" + {len(names) - n} more" if len(names) > n else "")


def by_mpn(mpn, max_pages=2, maker=None, **kw):
    """Exact MPN (case / whitespace-insensitive) -> Lookup. Near matches are listed in .near and never returned as the
    part. The maker is NEVER chosen by stock: when the exact listings span more than one maker the status is
    'ambiguous' (no .part; every listing in .also_exact) - pass maker= (or use the C-number) to settle it. With maker=,
    only listings of that maker qualify ('other_maker' if the MPN exists only under other makers). Several listings of
    the same maker (reel / cut-tape codes) -> the highest-stock one is .part, the rest .also_exact (other makers'
    listings are not part of an 'ok' result)."""
    q = mpn.strip()
    try:
        _, items, fetched = search_all(q, max_pages=max_pages, page_size=50, **kw)
    except JlcError as e:
        return Lookup(q, "mpn", "error", error=str(e), error_kind=type(e).__name__)
    key = norm_mpn(q)
    exact = [p for p in items if norm_mpn(p.mpn) == key]
    exact.sort(key=lambda p: (p.placeholder, -(p.stock or 0)))
    seen = {p.code for p in exact}
    near = [p for p in items if p.code not in seen and _near(q, p.mpn)]
    if not exact:
        return Lookup(q, "mpn", "no_exact", near=near, fetched_utc=fetched)
    real = [p for p in exact if not p.placeholder] or exact
    if maker:
        mine = [p for p in real if same_maker(maker, p.maker)]
        if not mine:
            return Lookup(q, "mpn", "other_maker", also_exact=exact, near=near, fetched_utc=fetched,
                          note=f"{q} is listed only under {_names(sorted({p.maker or '?' for p in real}))} - not "
                               f"{maker} (a near match below may be that maker's orderable MPN)")
        return Lookup(q, "mpn", "ok", part=mine[0], also_exact=mine[1:], near=near, fetched_utc=fetched)
    makers = []
    for p in real:
        if not any(same_maker(p.maker, m) for m in makers):
            makers.append(p.maker)
    if len(makers) > 1:
        return Lookup(q, "mpn", "ambiguous", also_exact=exact, near=near, fetched_utc=fetched,
                      note=f"{len(real)} listings from {len(makers)} makers ({_names([m or '?' for m in makers])}) "
                           "- pass --maker / maker= or use the C-number")
    return Lookup(q, "mpn", "ok", part=real[0], also_exact=[p for p in exact if p is not real[0]], near=near,
                  fetched_utc=fetched)


def lookup(q, maker=None, **kw):
    return by_code(q, **kw) if is_cnum(q) else by_mpn(q, maker=maker, **kw)


# ---------------------------------------------------------------------------------------------------------- CLI
def _need_map(path=None):
    """{C-number or normalised MPN: pieces needed for SETS sets} from bom/bom.json (read only; {} if unreadable)."""
    m = {}
    try:
        doc = json.loads(Path(path or BOM_JSON).read_text(encoding="utf-8"))
        sets = doc["settings"]["sets"]
        for mpn, part in doc["parts"].items():
            j = part.get("jlc") or {}
            n = sum(ln["qty"] for ln in doc["lines"] if ln["mpn"] == mpn) * sets
            if not n:
                continue
            for k in (j.get("jlc_pn"), mpn, j.get("jlc_mpn")):
                if k:
                    m.setdefault(k.strip().upper() if is_cnum(k) else norm_mpn(k), n)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return m


def fmt_part(p, need):
    oq = p.order_qty(need)
    up = p.price_at(oq)
    flags = []
    if p.placeholder:
        flags.append("JLC placeholder listing")
    if p.buyable is False:
        flags.append(f"NOT BUYABLE: {p.no_buy_reason or 'no reason given'}")
    stock = "?" if p.stock is None else f"{p.stock:,}"
    price = "-" if up is None else f"${up:.4f}"
    return (f"{p.code or '?':11s} {p.mpn or '?':28s} {(p.maker or '?')[:26]:26s} stock {stock:>10s}  "
            f"{p.library_label:9s} {(p.package or '?')[:14]:14s} {price} @ {oq} ({need} + {oq - need} attrition, "
            f"JLC loss {p.loss or 0})"
            + (f"  [{'; '.join(flags)}]" if flags else ""))


def _print_lookup(r, need):
    if r.status == "error":
        print(f"{r.query}: ERROR {r.error}")
        return
    if r.status == "not_found":
        print(f"{r.query}: not in JLC's parts library")
    elif r.status == "inconclusive":
        print(f"{r.query}: INCONCLUSIVE - {r.note}")
    elif r.status == "no_exact":
        print(f"{r.query}: no exact MPN match at JLC" + (" - near matches below (NOT the same part)" if r.near
                                                          else ""))
    elif r.status in ("ambiguous", "other_maker"):
        print(f"{r.query}: {r.status.upper().replace('_', ' ')} - {r.note}")
        for p in r.also_exact:
            print("  ? " + fmt_part(p, need))
    else:
        print(fmt_part(r.part, need))
        for p in r.also_exact:
            print("  = also " + fmt_part(p, need))
    for p in r.near[:8]:
        print("  ~ near " + fmt_part(p, need))


def attrition(need, loss=None):
    """Spare parts to plan for `need` placements (see ATTRITION_RATE / ATTRITION_FLOOR)."""
    need = int(need or 0)
    if need <= 0:
        return 0
    return max(int(loss or 0), math.ceil(ATTRITION_RATE * need), ATTRITION_FLOOR)


SNAPSHOT_KEYS = ["bom_mpn", "jlc_pn", "choice", "jlc_policy", "status", "api_mpn", "api_maker", "stock", "need_sets",
                 "loss", "order_qty", "library", "preferred", "library_label", "package", "unit_price", "ext_price",
                 "least_patch", "min_purchase", "presale", "buyable", "no_buy_reason", "datasheet", "issues", "watch",
                 "error", "fetched_utc", "snapshot"]


def _snapshot_start(r):
    c = (r.get("jlc_pn") or "").strip().upper()
    return c, {"bom_mpn": r.get("mpn"), "jlc_pn": c, "choice": r.get("choice"), "jlc_policy": (r.get("jlc_policy") or
               "").strip(), "need_sets": _int(r.get("need_sets")) or 0, "snapshot": time.strftime("%Y-%m-%d")}


def snapshot_from_lookup(r, lk):
    """One BOM mapping row {mpn, jlc_pn, jlc_mfr, jlc_mpn, choice, jlc_policy, need_sets, jlc_library (the library
    recorded by the previous observation)} + its by_code() Lookup -> (snapshot row, [issue, ...]). The row carries
    the stock, planned order quantity (need + attrition), price at that quantity, every price tier ("prices"),
    lossNumber, MOQ (min_purchase), presale and buyable flag of the SAME reply, with its fetched_utc."""
    c, s = _snapshot_start(r)
    need, policy = s["need_sets"], s["jlc_policy"]
    s["status"], s["fetched_utc"] = lk.status, lk.fetched_utc
    probs = []
    if lk.status == "error":
        s["error"] = lk.error
        probs.append(f"lookup failed: {lk.error}")
    elif lk.status == "not_found":
        probs.append("C-number not found at JLC")
    elif lk.status == "inconclusive":
        s["error"] = lk.note
        probs.append(f"lookup inconclusive: {lk.note}")
    else:
        p = lk.part
        oq = p.order_qty(need)
        up = p.price_at(oq)
        s.update(api_mpn=p.mpn, api_maker=p.maker, stock=p.stock, loss=p.loss, order_qty=oq, library=p.library,
                 preferred=p.preferred, library_label=p.library_label, package=p.package, unit_price=up,
                 ext_price=round(up * oq, 4) if up is not None else None, least_patch=p.least_patch,
                 min_purchase=p.min_purchase, presale=p.presale, buyable=p.buyable, no_buy_reason=p.no_buy_reason,
                 datasheet=p.datasheet, prices=p.prices)
        consign = policy in ("consign", "global")       # the owner ships it / JLC Global Sourcing buys it
        tag = f" ({policy} row: JLC stock not used)" if consign else ""
        if p.stock is None:
            probs.append("JLC gave no stock figure")
        elif p.stock < need:
            probs.append(f"stock {p.stock} < need {need}{tag}")
        elif p.stock < oq and not consign:
            probs.append(f"stock {p.stock} < need + attrition {oq} (tight)")
        elif p.stock < 2 * oq and not consign:
            s["watch"] = f"thin: stock {p.stock} < 2 x order qty {oq}"
        was = (r.get("jlc_library") or "").strip().lower()
        if was and p.library and was != p.library:
            probs.append(f"library recorded {was} vs JLC {p.library}")
        want_mpn = (r.get("jlc_mpn") or r.get("mpn") or "").strip()
        if want_mpn and norm_mpn(want_mpn) != norm_mpn(p.mpn):
            probs.append(f"MPN mapping {want_mpn} vs JLC {p.mpn}")
        if not makers_agree(r.get("jlc_mfr"), p.maker):
            probs.append(f"maker mapping {r.get('jlc_mfr')} vs JLC {p.maker}")
        if p.buyable is False:
            probs.append(f"JLC marks it not buyable: {p.no_buy_reason}")
        if p.placeholder:
            probs.append("C-number is a JLC placeholder listing")
    s["issues"] = "; ".join(probs)
    return s, probs


def snapshot_rows(rows, use_cache=True, max_age_h=DEFAULT_MAX_AGE_H, echo=print):
    """Look up the jlc_pn of every BOM mapping row (see snapshot_from_lookup) -> (snapshot rows, issues, n_errors).
    Writes nothing: scripts/bom.py stores the result. A block / rate limit / BOM_MAX_CONSECUTIVE_FAILS failed lookups
    in a row stop the run (the remaining rows are 'skipped' errors)."""
    out, issues, errors = [], [], 0
    stop = None                        # a block / rate limit / failure streak ends the run: no point asking again
    streak = 0                         # consecutive failed lookups (endpoint down or changed)
    for r in rows:
        c, s = _snapshot_start(r)
        if not is_cnum(c):
            s["status"] = "no_jlc_pn"
            out.append(s)
            continue
        if stop:
            s["status"], s["error"] = "skipped", stop
            errors += 1
            out.append(s)
            continue
        lk = by_code(c, use_cache=use_cache, max_age_h=max_age_h)
        streak = streak + 1 if lk.status == "error" else 0
        if lk.error_kind in ("JlcBlocked", "JlcRateLimited"):
            stop = f"not looked up: run stopped at {c} ({lk.error_kind})"
        elif streak >= BOM_MAX_CONSECUTIVE_FAILS:
            stop = (f"not looked up: run stopped at {c} after {streak} failed lookups in a row "
                    f"(last: {lk.error_kind}) - JLC down or changed; retry later")
        s, probs = snapshot_from_lookup(r, lk)
        if lk.status in ("error", "inconclusive"):
            errors += 1                # could not be verified: treat like a failed lookup (nothing is stored)
        if probs:
            issues.append((r.get("mpn"), c, probs))
        out.append(s)
        if echo:
            echo(f"{c or '-':11s} {str(r.get('mpn'))[:26]:26s} {s['status']:9s} stock {str(s.get('stock', '-')):>9s} "
                 f"need {s['need_sets']:>4d}  {str(s.get('library_label', '-')):9s} "
                 f"${s['unit_price'] if s.get('unit_price') is not None else '-'}"
                 + (f"   <- {s['issues']}" if probs else ""))
    return out, issues, errors


def main(argv=None):
    for st in (sys.stdout, sys.stderr):                     # JLC text has degree C / Ohm / CJK: never crash on cp1252
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="jlc_api.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("parts", nargs="*", help="C-numbers (exact) and/or MPNs (exact, near matches listed)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--maker", help="MPN lookups: only accept listings of this maker (never chosen by stock)")
    ap.add_argument("--search", metavar="KEYWORD", help="paged keyword search (alternates)")
    ap.add_argument("--pages", type=int, default=1, help="--search: pages to fetch (default 1, max 10)")
    ap.add_argument("--page-size", type=int, default=50, help=f"--search: page size (1..{PAGE_SIZE_MAX})")
    ap.add_argument("--library", choices=["base", "expand", "preferred"], help="--search: library filter")
    ap.add_argument("--in-stock", action="store_true", help="--search: in-stock parts only")
    ap.add_argument("--qty", type=int, help=f"placements to price at (default: the BOM need from bom/bom.json, "
                                            f"else {SETS})")
    ap.add_argument("--no-cache", action="store_true", help="always fetch (the cache is still refreshed)")
    ap.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE_H, help="cache TTL in hours (default 12)")
    ap.add_argument("--bom-json", default=str(BOM_JSON), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    ck = {"use_cache": not a.no_cache, "max_age_h": a.max_age}
    if a.search:
        try:
            total, items, fetched = search_all(a.search, max_pages=min(max(a.pages, 1), 10),
                                               page_size=a.page_size, library=a.library, in_stock=a.in_stock, **ck)
        except (JlcError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 1
        need = a.qty or SETS
        if a.json:
            print(json.dumps({"keyword": a.search, "total": total, "fetched_utc": fetched,
                              "items": [p.to_dict() for p in items]}, indent=1, ensure_ascii=False))
        else:
            print(f"# {a.search!r}: {total} results at JLC, showing {len(items)} (fetched {fetched})")
            for p in items:
                print(fmt_part(p, need) + (f" | {p.description[:90]}" if p.description else ""))
        return 0
    if not a.parts:
        ap.print_help()
        return 2
    needs = _need_map(a.bom_json)
    results = []
    for q in a.parts:
        r = lookup(q, maker=a.maker, **ck)
        results.append(r)
        if not a.json:
            key = r.part.code if r.part and r.part.code in needs else (q.strip().upper() if is_cnum(q)
                                                                        else norm_mpn(q))
            _print_lookup(r, a.qty or needs.get(key, SETS))
    if a.json:
        print(json.dumps([r.to_dict() for r in results], indent=1, ensure_ascii=False))
    if any(r.status == "error" for r in results):
        return 1
    return 3 if any(r.status in NOT_FOUND_STATES for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
