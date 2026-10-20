"""Isolated Chrome transport for public HLTV pages; optional websocket-client dependency."""

from base64 import b64decode
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from .core import FetchError, HttpCache, atomic_write, digest, json_bytes, utc_now


def page_selector(url):
    path = urlsplit(url).path
    if path == "/results":
        return ".results-all, .results"
    if re.match(r"/matches/\d+/", path):
        return ".timeAndEvent"
    if path.startswith("/stats/matches/"):
        return "table.stats-table"
    raise FetchError("Unsupported HLTV page path: " + path)


def browser_binary(path=None):
    candidates = [str(path)] if path else []
    candidates += [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    candidates += [shutil.which(name) for name in ("google-chrome", "chromium", "chromium-browser")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FetchError("Chrome/Edge not found; provide --browser with its executable path")


class HltvBrowser(HttpCache):
    """One owned browser per run. No personal profiles, credentials or cookies are imported."""

    def __init__(self, *args, browser=None, headless=False, proxy="direct", page_wait=45, **kwargs):
        super().__init__(*args, **kwargs)
        self.binary = browser
        self.headless = headless
        self.proxy = proxy
        self.page_wait = page_wait
        self.process = None
        self.channel = None
        self.log = None
        self.sequence = 0
        self.document = {}
        self.browser_info = None
        self.lifecycle = {"started": False, "closed": True}
        self.local_http = build_opener(ProxyHandler({}))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _local_json(self, url):
        with self.local_http.open(url, timeout=1) as response:
            return json.load(response)

    def _start(self):
        if self.channel is not None:
            return
        try:
            import websocket
        except ImportError as error:
            raise FetchError("HLTV browser needs optional dependencies: pip install -r data/pipeline/requirements-hltv.txt") from error
        binary = browser_binary(self.binary)
        profile = self.root / "raw" / "browser" / "hltv" / "profile"
        profile.mkdir(parents=True, exist_ok=True)
        log_path = profile.parent / ("browser-" + str(time.time_ns()) + ".log")
        self.log = log_path.open("w", encoding="utf-8")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        command = [binary, "--remote-debugging-port=" + str(port), "--remote-debugging-address=127.0.0.1",
                   "--user-data-dir=" + str(profile.resolve()), "--no-first-run", "--no-default-browser-check",
                   "--disable-component-update", "--disable-background-networking", "about:blank"]
        if self.headless:
            command.insert(1, "--headless=new")
        else:
            command.insert(1, "--window-position=-32000,-32000")
        if self.proxy == "direct":
            command.insert(1, "--no-proxy-server")
        elif self.proxy == "environment":
            parsed = urlsplit(os.environ.get("HTTPS_PROXY", ""))
            if not parsed.hostname or parsed.username:
                raise FetchError("--browser-proxy environment requires an HTTPS_PROXY URL without embedded credentials")
            command.insert(1, "--proxy-server=" + parsed.scheme + "://" + parsed.netloc)
        options = {}
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options["startupinfo"] = startup
        self.process = subprocess.Popen(command, stdout=self.log, stderr=self.log, **options)
        self.lifecycle = {"started": True, "closed": False, "pid": self.process.pid}
        deadline = time.monotonic() + 15
        target = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise FetchError("Chrome exited during startup (profile in use or Windows sandbox IPC blocked); see " + str(log_path))
            try:
                tabs = self._local_json(f"http://127.0.0.1:{port}/json/list")
                target = next(tab for tab in tabs if tab["type"] == "page")
                break
            except (OSError, ValueError, IndexError, StopIteration):
                pass
            time.sleep(0.25)
        if target is None:
            raise FetchError("Chrome debugging endpoint did not start within 15 seconds")
        self.channel = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
        info = self._call("Browser.getVersion")
        self.browser_info = {key: info.get(key) for key in ("product", "protocolVersion", "userAgent")}
        self.browser_info["webdriver"] = self._call("Runtime.evaluate", {"expression": "navigator.webdriver", "returnByValue": True}).get("result", {}).get("value")
        self._call("Page.enable")
        self._call("Network.enable")

    def _call(self, method, params=None):
        self.sequence += 1
        message_id = self.sequence
        try:
            self.channel.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                message = json.loads(self.channel.recv())
                if message.get("method") == "Network.responseReceived":
                    event = message["params"]
                    if event.get("type") == "Document":
                        response = event["response"]
                        self.document[response["url"]] = {"status": int(response["status"]),
                                                           "request_id": event["requestId"],
                                                           "mime_type": response.get("mimeType")}
                if message.get("id") == message_id:
                    if "error" in message:
                        raise FetchError("Chrome protocol error: " + str(message["error"]))
                    return message.get("result", {})
        except FetchError:
            raise
        except Exception as error:
            raise FetchError("Chrome connection failed: " + str(error)) from error
        raise FetchError("Chrome protocol response timed out")

    def get(self, url, *, refresh=False):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "www.hltv.org":
            raise FetchError("HLTV browser accepts only https://www.hltv.org URLs")
        selector = page_selector(url)
        folder = self.root / "raw" / "http" / digest(url.encode("utf-8"))
        if (folder / "latest.json").exists() and (self.offline or not refresh):
            return super().get(url, refresh=refresh)
        if self.offline:
            raise FetchError("No cached response: " + url)
        self._start()
        time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        navigation = self._call("Page.navigate", {"url": url})
        if navigation.get("errorText"):
            raise FetchError("Chrome navigation failed: " + navigation["errorText"])
        expression = "JSON.stringify({url:location.href,title:document.title,ready:document.readyState,valid:!!document.querySelector(" + json.dumps(selector) + "),html:document.documentElement.outerHTML})"
        deadline = time.monotonic() + self.page_wait
        state = {}
        while time.monotonic() < deadline:
            time.sleep(0.5)
            value = self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            raw = value.get("result", {}).get("value")
            if not raw:
                continue
            state = json.loads(raw)
            current = urlsplit(state["url"])
            if (current.hostname == parsed.hostname and current.path.rstrip("/") == parsed.path.rstrip("/")
                    and current.query == parsed.query and state["valid"] and state["ready"] in ("interactive", "complete")):
                break
            if state["url"].startswith("chrome-error:"):
                raise FetchError("Chrome displayed a network error: " + url)
        else:
            failed_body = state.get("html", "").encode("utf-8")
            failure = {"url": url, "fetched_at": utc_now(), "transport": "chrome_cdp",
                       "error": "challenge_or_unrecognized_page", "title": state.get("title"),
                       "document_ready": state.get("ready"), "expected_selector_found": state.get("valid"),
                       "final_path": urlsplit(state.get("url", "")).path,
                       "query_matches": urlsplit(state.get("url", "")).query == parsed.query,
                       "sha256": digest(failed_body)}
            # Diagnostic failures never enter the successful-page cache.
            atomic_write(self.root / "raw" / "browser_errors" / (failure["sha256"] + ".html"), failed_body)
            self.requests.append(failure)
            raise FetchError("HLTV challenge or unrecognized page after " + str(self.page_wait) + "s (" + str(state.get("title")) + "): " + url)
        body = state["html"].encode("utf-8")
        representation = "rendered_dom"
        response = self.document.get(state["url"], {})
        if response.get("status") == 200:
            try:
                original = self._call("Network.getResponseBody", {"requestId": response["request_id"]})
                body = b64decode(original["body"]) if original.get("base64Encoded") else original["body"].encode("utf-8")
                representation = "http_response_body"
            except FetchError:
                pass
        metadata = {"url": url, "final_url": state["url"], "fetched_at": utc_now(), "status": response.get("status"),
                    "sha256": digest(body), "content_type": response.get("mime_type", "text/html"),
                    "transport": "chrome_cdp", "representation": representation, "browser": self.browser_info}
        metadata["body_file"] = metadata["sha256"] + ".body"
        atomic_write(folder / metadata["body_file"], body)
        atomic_write(folder / "latest.json", json_bytes(metadata))
        self.requests.append({**metadata, "cache_hit": False})
        return body, metadata

    def close(self):
        if self.channel is not None:
            try:
                self.channel.send(json.dumps({"id": 99999999, "method": "Browser.close"}))
            except Exception:
                pass
            try:
                self.channel.close()
            except Exception:
                pass
            self.channel = None
        if self.process is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    options = {"startupinfo": subprocess.STARTUPINFO()}
                    options["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    options["startupinfo"].wShowWindow = subprocess.SW_HIDE
                    result = subprocess.run(["taskkill.exe", "/PID", str(self.process.pid), "/T", "/F"],
                                            capture_output=True, timeout=10, **options)
                    self.lifecycle["taskkill_exit_code"] = result.returncode
                else:
                    self.process.terminate()
                self.process.wait(timeout=5)
            self.lifecycle["closed"] = self.process.poll() is not None
            self.lifecycle["exit_code"] = self.process.poll()
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None
