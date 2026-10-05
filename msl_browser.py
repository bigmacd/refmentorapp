"""Browser session for mysoccerleague.com.

Cloudflare serves a human-check page instead of the login form to plain HTTP
clients. This session uses the installed browser, waits until that check is
done, and keeps the rest of the scrape in the same window.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_NAVIGATION_TIMEOUT_MS = 60_000
_LOGIN_URL = "https://mysoccerleague.com/YSLmobile.jsp"
_HUMAN_WAIT_SECONDS = 180

_BROWSER_CANDIDATES = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


class CloudflareChallengeError(RuntimeError):
    """The Cloudflare check did not finish, so the real page is not available."""


class LoginPageError(RuntimeError):
    """The site responded, but the expected form was not on the page."""


class HtmlPage:
    def __init__(self, status_code: int, html: str, url: str):
        self.status_code = status_code
        self.url = url
        self.soup = BeautifulSoup(html, "lxml")


class _SessionCompat:
    """Accepts the requests-style `session.verify` assignment and ignores it.

    Chromium uses the operating system trust store.
    """

    def __init__(self):
        self.verify = True


class PlaywrightBrowser:
    def __init__(self):
        self.session = _SessionCompat()
        self._form_selector = "form"
        self._closed = False
        self._headless = _headless()
        self._challenge_timeout_ms = 15_000 if self._headless else _HUMAN_WAIT_SECONDS * 1000
        self._edge_process = None
        self._edge_log = None
        self._playwright = None
        self._cdp_browser = None
        self._context = None
        self._page = None
        if self._headless:
            raise CloudflareChallengeError(
                "Cloudflare is showing a 'Verify you are human' checkbox. "
                "This process has no display, so it cannot be checked. "
                "Run the sync where a browser window can open, "
                "or ask MySoccerLeague to allowlist this client."
            )
        try:
            port = self._start_normal_browser(_LOGIN_URL)
            self._wait_for_human_check(port)
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._context = self._connect(port)
        except Exception:
            self.close()
            raise
        self._page.set_default_navigation_timeout(_NAVIGATION_TIMEOUT_MS)
        self._page.set_default_timeout(_NAVIGATION_TIMEOUT_MS)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        context = getattr(self, "_context", None)
        if context is not None:
            try:
                context.close()
            except Exception:
                logger.debug("Error while closing the browser context", exc_info=True)
        cdp_browser = getattr(self, "_cdp_browser", None)
        if cdp_browser is not None:
            try:
                cdp_browser.close()
            except Exception:
                logger.debug("Error while disconnecting from the browser", exc_info=True)
        playwright = getattr(self, "_playwright", None)
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                logger.debug("Error while stopping Playwright", exc_info=True)
        process = getattr(self, "_edge_process", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        edge_log = getattr(self, "_edge_log", None)
        if edge_log is not None:
            edge_log.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def title(self) -> str:
        try:
            return self._page.title()
        except Exception:
            return ""

    def open(self, url: str) -> HtmlPage:
        if self._on_url(url) and not _is_challenge_title(self.title()):
            logger.info("Already on %s (title: %s)", self._page.url, self.title())
            return self._snapshot(200)
        response = self._page.goto(url, wait_until="domcontentloaded")
        self._wait_until_clear()
        status = response.status if response is not None else 200
        # The challenge response itself is 403. Once the real document is showing,
        # report that settled page as success.
        if status >= 400:
            status = 200
        logger.info("Opened %s (title: %s)", self._page.url, self.title())
        return self._snapshot(status)

    def select_form(self, selector: str = "form") -> None:
        self._wait_until_clear()
        try:
            self._page.wait_for_selector(selector, timeout=_NAVIGATION_TIMEOUT_MS)
        except Exception as ex:
            names = self._field_names()
            raise LoginPageError(
                f"No element matched {selector!r} "
                f"(title={self.title()!r}, url={self._page.url}, fields={names})"
            ) from ex
        self._form_selector = selector

    def __setitem__(self, name: str, value) -> None:
        field = self._page.locator(f'{self._form_selector} [name="{name}"]').first
        try:
            field.wait_for(state="attached", timeout=10_000)
        except Exception as ex:
            raise LoginPageError(
                f"Form field {name!r} was not found (title={self.title()!r})"
            ) from ex

        text = "" if value is None else str(value)
        tag = field.evaluate("el => el.tagName.toLowerCase()")
        input_type = (field.get_attribute("type") or "").lower()

        if tag == "select":
            try:
                field.select_option(value=text)
            except Exception:
                field.select_option(label=text)
            return

        if input_type == "radio":
            radio = self._page.locator(
                f'{self._form_selector} [name="{name}"][value="{text}"]'
            ).first
            radio.check()
            return

        if input_type == "checkbox":
            if text.lower() in ("", "0", "false", "off"):
                field.uncheck()
            else:
                field.check()
            return

        if not field.is_visible():
            field.evaluate(
                """(el, val) => {
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                text,
            )
            return

        field.fill(text)

    def submit_selected(self) -> HtmlPage:
        form = self._page.locator(self._form_selector).first
        submit = form.locator(
            'input[type="submit"], button[type="submit"], button:not([type="button"])'
        )
        clicked = False
        for index in range(submit.count()):
            candidate = submit.nth(index)
            if candidate.is_visible():
                candidate.click()
                clicked = True
                break
        if not clicked:
            form.evaluate(
                "form => form.requestSubmit ? form.requestSubmit() : form.submit()"
            )
        self._page.wait_for_load_state("domcontentloaded")
        self._wait_until_clear()
        logger.info("Submitted form, now at %s (title: %s)", self._page.url, self.title())
        return self._snapshot(200)

    def _snapshot(self, status_code: int) -> HtmlPage:
        return HtmlPage(status_code, self._page.content(), self._page.url)

    def _field_names(self) -> list[str]:
        try:
            return self._page.eval_on_selector_all(
                "input, select, textarea",
                "els => els.map(el => el.getAttribute('name')).filter(Boolean)",
            )
        except Exception:
            return []

    def _human_check_visible(self) -> bool:
        for frame in self._page.frames:
            try:
                html = frame.content()
            except Exception:
                continue
            if "Verify you are human" in html or "Performing security verification" in html:
                return True
        return False

    def _raise_if_blocked(self) -> None:
        title = self.title()
        if "Attention Required" in title or "you have been blocked" in title.lower():
            raise CloudflareChallengeError(
                f"Cloudflare blocked this browser (title={title!r}, url={self._page.url})"
            )

    def _wait_until_clear(self) -> None:
        self._raise_if_blocked()
        deadline = time.monotonic() + (self._challenge_timeout_ms / 1000)
        told_user = False
        while time.monotonic() < deadline:
            if self._page.is_closed():
                raise CloudflareChallengeError(
                    "The browser window closed before Cloudflare finished its check."
                )
            self._raise_if_blocked()
            title = self.title()
            try:
                if self._page.locator('input[name="userName"], a[href*="YSLkey"]').count():
                    return
            except Exception:
                pass
            challenge = (
                not title
                or "Just a moment" in title
                or "Checking your browser" in title
            )
            if not challenge:
                return
            if self._human_check_visible():
                if self._headless:
                    raise CloudflareChallengeError(
                        "Cloudflare is showing a 'Verify you are human' checkbox. "
                        "This process has no display, so it cannot be checked. "
                        "Run the sync where a browser window can open (MSL_HEADLESS=0), "
                        "or ask MySoccerLeague to allowlist this client."
                    )
                if not told_user:
                    logger.warning(
                        "Cloudflare is showing \"Verify you are human\" again. "
                        "Check that box in the Edge window and leave it open."
                    )
                    told_user = True
            time.sleep(0.5)
        raise CloudflareChallengeError(
            f"Cloudflare challenge did not finish (title={self.title()!r}, url={self._page.url}). "
            "Set MSL_HEADLESS=0 and complete the checkbox in the browser window."
        )

    def _on_url(self, url: str) -> bool:
        # The login page is the only one we may already be sitting on after the
        # human check. Other pages share that path and differ by query string.
        if _url_path(url) == _url_path(_LOGIN_URL):
            return _url_path(self._page.url) == _url_path(_LOGIN_URL)
        return self._page.url.split("#", 1)[0] == url.split("#", 1)[0]

    def _start_normal_browser(self, url: str) -> int:
        """Start Edge or Chrome as a normal window.

        Playwright's own launcher marks the window as automated software.
        Cloudflare then rejects the human checkbox and puts it back.
        """
        executable = _browser_executable()
        if executable is None:
            raise CloudflareChallengeError(
                "Microsoft Edge or Google Chrome is not installed. "
                "Install one of them, or set CHROMIUM_PATH to the browser executable."
            )
        profile = os.path.abspath(
            os.environ.get("MSL_BROWSER_PROFILE") or os.path.join(".data", "msl-browser-profile")
        )
        os.makedirs(profile, exist_ok=True)
        port = _free_local_port()
        log_path = os.path.join(os.path.dirname(profile), "msl-edge.log")
        self._edge_log = open(log_path, "w")
        logger.warning(
            "Opening a normal browser window. The checkbox reset last time because "
            "that window was marked as automated. Check \"Verify you are human\" in "
            "this window and leave it open. Waiting up to 3 minutes."
        )
        self._edge_process = subprocess.Popen(
            [
                executable,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                url,
            ],
            stdout=self._edge_log,
            stderr=subprocess.STDOUT,
        )
        if not _wait_for_debug_port(port, self._edge_process, timeout=20):
            raise CloudflareChallengeError(
                "The browser window closed before its debugging port opened. "
                f"See {log_path}."
            )
        logger.info("Browser ready on port %s", port)
        return port

    def _wait_for_human_check(self, port: int) -> None:
        deadline = time.monotonic() + _HUMAN_WAIT_SECONDS
        while time.monotonic() < deadline:
            if not _debug_port_open(port) and self._edge_process.poll() is not None:
                raise CloudflareChallengeError(
                    "The browser window closed before Cloudflare finished its check."
                )
            for target in _debug_targets(port):
                if target.get("type") != "page":
                    continue
                page_url = target.get("url") or ""
                title = target.get("title") or ""
                if "mysoccerleague.com" not in page_url:
                    continue
                if _is_challenge_target(title, page_url):
                    continue
                logger.info("Cloudflare check finished (title: %s)", title or page_url)
                return
            time.sleep(0.5)
        raise CloudflareChallengeError(
            "Cloudflare challenge did not finish. Check \"Verify you are human\" "
            "in the browser window and leave that window open."
        )

    def _connect(self, port: int):
        browser = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        self._cdp_browser = browser
        if not browser.contexts:
            raise CloudflareChallengeError("Connected to the browser, but it had no open window.")
        context = browser.contexts[0]
        pages = [page for page in context.pages if "mysoccerleague.com" in (page.url or "")]
        self._page = pages[-1] if pages else context.pages[0]
        return context


def _browser_executable() -> str | None:
    configured = os.environ.get("CHROMIUM_PATH")
    if configured and os.path.exists(configured):
        return configured
    for candidate in _BROWSER_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def _free_local_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _debug_port_open(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_for_debug_port(port: int, process: subprocess.Popen, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _debug_port_open(port):
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.2)
    return _debug_port_open(port)


def _debug_targets(port: int) -> list:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _is_challenge_title(title: str) -> bool:
    return (
        not title
        or "Just a moment" in title
        or "Checking your browser" in title
    )


def _is_challenge_target(title: str, url: str) -> bool:
    if not title:
        return True
    lowered = title.lower()
    if "just a moment" in lowered or "checking your browser" in lowered or "verifying" in lowered:
        return True
    if "__cf_chl" in url:
        return True
    return False


def _url_path(url: str) -> str:
    without_query = url.split("?", 1)[0].rstrip("/")
    return without_query


def _headless() -> bool:
    flag = os.environ.get("MSL_HEADLESS")
    if flag == "1":
        return True
    if flag == "0":
        return False
    if os.environ.get("FLY_APP_NAME") or os.path.exists("/.dockerenv"):
        return True
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return True
    return False
