"""Request-local routing: direct first, live configured proxy only as fallback."""
from functools import lru_cache
import ipaddress
import socket
import time
from threading import local
from urllib.parse import urlsplit
from urllib.request import getproxies

import requests


@lru_cache(maxsize=1)
def live_proxy():
    """Do not inherit a dead localhost proxy or modify Windows networking."""
    proxies = getproxies()
    value = proxies.get('https') or proxies.get('http') or proxies.get('all')
    if not value:
        return None
    try:
        endpoint = urlsplit(value if '://' in value else 'http://' + value)
        if endpoint.scheme not in {'http', 'https', 'socks5', 'socks5h'} or not endpoint.hostname:
            return None
        host = endpoint.hostname
        is_local = host.lower() == 'localhost'
        try:
            is_local = is_local or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        # Automatic fallback only uses the user's existing local proxy service.
        if not is_local:
            return None
        with socket.create_connection((host, endpoint.port or 80), timeout=0.3):
            pass
        return endpoint.geturl()
    except (ValueError, OSError):
        return None


class NetworkClient:
    def __init__(self, allow_proxy=True):
        self.allow_proxy = allow_proxy
        self._sessions = local()

    def session_for(self, route, endpoint):
        session = getattr(self._sessions, route, None)
        if session is None:
            session = requests.Session()
            session.trust_env = False
            if endpoint:
                session.proxies = {'http': endpoint, 'https': endpoint}
            setattr(self._sessions, route, session)
        return session

    def get(self, url, timeout=10, **kwargs):
        routes = [('direct', None)]
        proxy = live_proxy() if self.allow_proxy else None
        if proxy:
            routes.append(('configured_proxy', proxy))
        failures = []
        for route, endpoint in routes:
            for attempt in range(2):
                try:
                    # One pool per thread and route: reuse verified TLS sessions
                    # without sharing a requests.Session between worker threads.
                    session = self.session_for(route, endpoint)
                    response = session.get(url, timeout=(min(timeout, 5), timeout), **kwargs)
                    response.raise_for_status()
                    response.finance_route = route
                    return response
                except requests.RequestException as error:
                    failures.append(route + ':' + type(error).__name__)
                    # Retry a transient timeout/reset once, not authentication,
                    # rate limits or other permanent client errors.
                    if isinstance(error, requests.HTTPError) and error.response is not None and error.response.status_code < 500:
                        break
                    if attempt == 0:
                        time.sleep(0.3)
        # Never persist proxy credentials or an authenticated request URL.
        raise requests.ConnectionError('连接未完成（' + '；'.join(failures) + '）')
