"""Test auth routes via HTTP — no browser needed."""

import http.client
import urllib.parse
import urllib.request
import urllib.error


def http_get(path):
    """GET a path and return (status_code, final_url)."""
    url = f'http://127.0.0.1:5000{path}'
    try:
        resp = urllib.request.urlopen(url)
        return resp.status, resp.url
    except urllib.error.HTTPError as e:
        return e.code, url


def http_post_login(email, password):
    """POST to /auth/login, return (status_code, Location_header)."""
    body = urllib.parse.urlencode({'email': email, 'password': password}).encode()
    conn = http.client.HTTPConnection('127.0.0.1', 5000)
    conn.request(
        'POST', '/auth/login', body=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    resp = conn.getresponse()
    return resp.status, resp.getheader('Location', '—')


def run_auth_smoke_tests():
    results = []

    def check(label, status, expected_status):
        ok = (status == expected_status)
        results.append(ok)
        mark = 'PASS' if ok else 'FAIL'
        print(f'  [{mark}] {label}: HTTP {status} (expected {expected_status})')

    print('=== Live HTTP Route Tests ===\n')

    s, _ = http_get('/')
    check('GET / (home)                    ', s, 200)

    s, _ = http_get('/auth/login')
    check('GET /auth/login                 ', s, 200)

    s, _ = http_get('/auth/register')
    check('GET /auth/register              ', s, 200)

    # Unauthenticated access to protected route -- follows redirect to login page (200)
    s, final = http_get('/shelters/')
    check('GET /shelters/ (unauth)  -> login', s, 200)

    # Bad login -- stays on login page (200) with error flash
    s, loc = http_post_login('nobody@example.com', 'badpassword')
    check('POST /auth/login (bad creds)    ', s, 200)

    # Good login -- 302 redirect to home
    s, loc = http_post_login('admin@shelter.gov', 'Password@123')
    check('POST /auth/login (admin)   -> 302', s, 302)
    print(f'         Redirect target: {loc}')

    s, loc = http_post_login('responder1@shelter.gov', 'Password@123')
    check('POST /auth/login (responder) ->302', s, 302)

    s, loc = http_post_login('citizen@example.com', 'Password@123')
    check('POST /auth/login (citizen) -> 302', s, 302)

    print()
    passed = sum(results)
    total  = len(results)
    print(f'Result: {passed}/{total} tests passed.')
    if passed == total:
        print('ALL TESTS PASSED.')
    return passed == total


if __name__ == '__main__':
    try:
        run_auth_smoke_tests()
    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        print('[SKIP] Auth HTTP Smoke Tests skipped: Flask server not running on port 5000.')
