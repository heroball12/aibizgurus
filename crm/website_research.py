"""Evidence from public HTML. A missing signal is never proof a feature is absent."""

import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser

from django.utils import timezone
from .lead_finder import listing_email
from .public_site import SiteError, USER_AGENT, fetch_page, safe_url


def tidy(value, limit=500):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


class PageFacts(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.title, self.description = url, "", ""
        self.links, self.embeds, self.headings, self.structured = [], [], [], []
        self.emails, self.phones = [], []
        self.capture, self.text, self.link, self.script, self.script_type = (
            "",
            [],
            None,
            None,
            "",
        )
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", attrs.get("property", "")).lower() in {
            "description",
            "og:description",
        }:
            self.description = self.description or tidy(attrs.get("content"))
        if tag in {"script", "iframe"} and attrs.get("src"):
            url = safe_url(urljoin(self.url, attrs["src"]))
            if url:
                self.embeds.append(url)
        if tag == "script":
            self.script, self.script_type = [], attrs.get("type", "")
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"title", "h1", "h2"}:
            self.capture, self.text = tag, []
        if tag == "a" and attrs.get("href"):
            href = attrs["href"].strip()
            if href.lower().startswith("mailto:"):
                address = listing_email(unquote(href[7:].split("?")[0]))
                if address:
                    self.emails.append(address)
            elif href.lower().startswith("tel:"):
                number = unquote(href[4:].split("?")[0])
                if re.fullmatch(r"[+\d ()\-.]{7,30}", number):
                    self.phones.append(number)
            url = safe_url(urljoin(self.url, href))
            self.link = (
                {"url": url, "text": [attrs.get("aria-label", "")]} if url else None
            )
        if tag == "form" and attrs.get("action"):
            url = safe_url(urljoin(self.url, attrs["action"]))
            if url:
                self.links.append({"url": url, "label": "Form action"})

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if self.hidden:
            return
        if self.capture:
            self.text.append(data)
        if self.link:
            self.link["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            value = "".join(self.script)
            if self.script_type == "application/ld+json":
                try:
                    self.structured.append(json.loads(value))
                except (ValueError, RecursionError):
                    pass
            else:
                # Recognize actual embedded script URLs, not mentions in articles.
                for match in re.findall(
                    r"""["']((?:https?:)?//[^\s"'<>]+)["']""", value
                )[:60]:
                    url = safe_url(urljoin(self.url, match))
                    if url:
                        self.embeds.append(url)
            self.script = None
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == self.capture:
            text = tidy(" ".join(self.text), 180)
            if tag == "title":
                self.title = text
            elif text:
                self.headings.append(text)
            self.capture, self.text = "", []
        if tag == "a" and self.link:
            self.links.append(
                {
                    "url": self.link["url"],
                    "label": tidy(" ".join(self.link["text"]), 100),
                }
            )
            self.link = None


# A detected script identifies an integration, not whether its live conversation works.
AI_EMBEDS = {
    "chatbase.co": "Chatbase AI chat",
    "customgpt.ai": "CustomGPT AI chat",
    "sitegpt.ai": "SiteGPT AI chat",
}
CHAT_EMBEDS = {
    "intercom.io": "Intercom",
    "intercomcdn.com": "Intercom",
    "tidio.co": "Tidio",
    "tidiochat.com": "Tidio",
    "tawk.to": "Tawk.to",
    "livechatinc.com": "LiveChat",
    "crisp.chat": "Crisp",
    "drift.com": "Drift",
    "driftt.com": "Drift",
    "zopim.com": "Zendesk chat",
    "zdassets.com": "Zendesk",
    "widget.manychat.com": "Manychat",
    "voiceflow.com": "Voiceflow",
    "botpress.cloud": "Botpress",
    "podium.com": "Podium",
    "gorgias.chat": "Gorgias",
}
BOOK_HOSTS = {
    "calendly.com",
    "acuityscheduling.com",
    "opentable.com",
    "resy.com",
    "booksy.com",
    "vagaro.com",
    "fresha.com",
    "square.site",
    "squareup.com",
    "zocdoc.com",
    "setmore.com",
    "youcanbook.me",
    "mindbodyonline.com",
    "schedulicity.com",
}
SHOP_HOSTS = {
    "checkout.shopify.com",
    "buy.stripe.com",
    "checkout.stripe.com",
    "paypal.com",
    "toasttab.com",
    "chownow.com",
    "order.online",
    "doordash.com",
    "ubereats.com",
    "dutchie.com",
    "iheartjane.com",
    "weedmaps.com",
}


def host_matches(url, host):
    name = (urlsplit(url).hostname or "").lower()
    return name == host or name.endswith("." + host)


def inspect_pages(pages):
    findings = {
        key: {"status": "not_observed", "evidence": []}
        for key in ("chat", "booking", "checkout")
    }
    details = {
        "description": "",
        "title": "",
        "emails": [],
        "phones": [],
        "headings": [],
        "address": "",
        "hours": [],
    }

    def add(key, page, detail, status="detected"):
        item = {"page": page, "detail": detail}
        if item not in findings[key]["evidence"] and len(findings[key]["evidence"]) < 5:
            findings[key]["evidence"].append(item)
        if findings[key]["status"] != "ai_detected":
            findings[key]["status"] = status

    for page in pages:
        details["title"] = details["title"] or page.title
        details["description"] = details["description"] or page.description
        for key in ("emails", "phones", "headings"):
            details[key].extend(getattr(page, key))
        for url in page.embeds:
            for host, label in AI_EMBEDS.items():
                if host_matches(url, host):
                    add("chat", page.url, label + " embed code found.", "ai_detected")
            for host, label in CHAT_EMBEDS.items():
                if host_matches(url, host):
                    add(
                        "chat",
                        page.url,
                        label + " embed found; AI mode is unconfirmed.",
                        "chat_detected",
                    )
        for link in page.links + [
            {"url": url, "label": "Embedded tool"} for url in page.embeds
        ]:
            url, label = link["url"], link["label"]
            path = unquote(urlsplit(url).path).lower()
            text = (label + " " + path).lower()
            booking_host = any(
                host_matches(url, host)
                for host in BOOK_HOSTS - {"square.site", "squareup.com"}
            )
            if booking_host or re.search(
                r"\b(book(?:ing)?|schedule|reserve|reservations?|appointments?)\b", text
            ):
                # Don't interpret the general word 'book' on a bookstore as proof of reservations.
                if booking_host or re.search(
                    r"book (?:now|a |an |your|online)|schedule|reserv|appointment|/book(?:ing)?(?:/|$)",
                    text,
                ):
                    add(
                        "booking",
                        page.url,
                        f"Booking / scheduling link or tool: {label or path[:100]}.",
                    )
            if any(host_matches(url, host) for host in SHOP_HOSTS) or re.search(
                r"\b(checkout|cart|buy now|order online|order now|shop now|add to cart)\b|/(?:shop|store|orders?)(?:/|$)",
                text,
            ):
                add(
                    "checkout",
                    page.url,
                    f"Shopping / ordering link or tool: {label or path[:100]}.",
                )
            if re.search(r"\b(?:live chat|chat with us|chat now)\b", label.lower()):
                add(
                    "chat",
                    page.url,
                    "A chat link is offered; AI mode is unconfirmed.",
                    "chat_detected",
                )
            elif re.search(
                r"\b(?:meet|open|talk to|chat with|ask)\b.{0,35}\bAI (?:assistant|guide|employee|concierge|chatbot)\b",
                label,
                re.I,
            ):
                add(
                    "chat",
                    page.url,
                    "A link offers an AI assistant conversation; its live behavior is unconfirmed.",
                    "chat_detected",
                )
        # Only extract business schema, avoiding product, review or article attribution.
        nodes = list(page.structured)
        for _ in range(80):
            if not nodes:
                break
            node = nodes.pop(0)
            if isinstance(node, list):
                nodes.extend(node[:30])
                continue
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph", [])
            nodes.extend(graph[:30] if isinstance(graph, list) else [graph])
            kind = str(node.get("@type", "")).lower()
            if not any(
                word in kind
                for word in (
                    "business",
                    "organization",
                    "restaurant",
                    "store",
                    "dentist",
                    "hotel",
                    "salon",
                    "service",
                )
            ):
                continue
            address = node.get("address")
            if isinstance(address, dict) and not details["address"]:
                details["address"] = tidy(
                    ", ".join(
                        str(address.get(k, ""))
                        for k in (
                            "streetAddress",
                            "addressLocality",
                            "addressRegion",
                            "postalCode",
                        )
                        if address.get(k)
                    )
                )
            if isinstance(node.get("telephone"), str):
                details["phones"].append(tidy(node["telephone"], 40))
            if isinstance(node.get("email"), str) and listing_email(node["email"]):
                details["emails"].append(listing_email(node["email"]))
            hours = node.get("openingHours", [])
            if isinstance(hours, str):
                hours = [hours]
            if isinstance(hours, list):
                details["hours"].extend(
                    tidy(x, 120) for x in hours[:7] if isinstance(x, str)
                )
            details["description"] = details["description"] or (
                tidy(node.get("description"))
                if isinstance(node.get("description"), str)
                else ""
            )
    for key in ("emails", "phones", "headings", "hours"):
        details[key] = list(dict.fromkeys(details[key]))[:8]
    labels = {
        "chat": {
            "ai_detected": "AI chat code detected",
            "chat_detected": "Chat detected · AI unconfirmed",
            "not_observed": "No chat evidence found",
        },
        "booking": {
            "detected": "Booking option detected",
            "not_observed": "No booking evidence found",
        },
        "checkout": {
            "detected": "Shopping / ordering detected",
            "not_observed": "No checkout evidence found",
        },
    }
    for key in findings:
        findings[key]["label"] = labels[key][findings[key]["status"]]
    return details, findings


def research_website(website):
    start = safe_url(website if "://" in website else "https://" + website)
    if not start:
        raise SiteError("This result needs a valid public website first.")
    deadline, robots, warnings = time.monotonic() + 22, {}, []

    def allowed(url):
        parsed = urlsplit(url)
        origin = (parsed.scheme, parsed.netloc)
        if origin not in robots:
            robot_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            parser = RobotFileParser()
            try:
                _, rules = fetch_page(robot_url, deadline=deadline, plain=True)
                if "<html" in rules.lower():
                    parser.parse(
                        []
                    )  # Some sites serve their normal 404 HTML with HTTP 200.
                else:
                    parser.parse(rules.splitlines())
            except SiteError as exc:
                if exc.status in {404, 410}:
                    parser.parse([])
                else:
                    raise SiteError(
                        "This site's crawl permissions could not be confirmed. Open its website to review it manually."
                    ) from None
            robots[origin] = parser
        return robots[origin].can_fetch(USER_AGENT, url)

    if not allowed(start):
        raise SiteError(
            "This website asks automated researchers not to crawl this page. Open the site for a manual review."
        )
    final, html = fetch_page(start, deadline=deadline)
    if final != start and not allowed(final):
        raise SiteError("The destination website restricts automated research.")
    home = PageFacts(final)
    home.feed(html)
    pages = [home]
    origin = (urlsplit(final).scheme, urlsplit(final).netloc)
    candidates = sorted(
        home.links,
        key=lambda link: (
            0 if re.search(r"contact|about", link["url"] + link["label"], re.I) else 1
        ),
    )
    seen = {final}
    for link in candidates:
        if len(pages) >= 3 or time.monotonic() > deadline - 2:
            break
        url = link["url"]
        parts = urlsplit(url)
        if (
            url in seen
            or (parts.scheme, parts.netloc) != origin
            or parts.query
            or not re.search(
                r"(?:^|/)(?:about(?:-us)?|contact(?:-us)?|services?)(?:/|$|\.)",
                parts.path,
                re.I,
            )
        ):
            continue
        seen.add(url)
        try:
            if not allowed(url):
                warnings.append(
                    "An additional page was excluded by the website’s crawl rules."
                )
                continue
            page_url, html = fetch_page(url, deadline=deadline, allowed_origin=origin)
            page = PageFacts(page_url)
            page.feed(html)
            pages.append(page)
        except SiteError as exc:
            warnings.append(str(exc))
        if len(seen) >= 4:
            break
    details, findings = inspect_pages(pages)
    from .business_status import website_closure

    return {
        "version": 1,
        "website": website,
        "checked_at": timezone.now().isoformat(),
        "details": details,
        "findings": findings,
        "business_notice": website_closure(home),
        "pages": [page.url for page in pages],
        "warnings": list(dict.fromkeys(warnings)),
        "limitation": "This scan reads public page code, not a live browser session. Scripts, cookie-gated widgets and sign-in-only features may be missed. Booking, checkout and chat were not operated or tested. No evidence found does not mean a feature is absent.",
    }
