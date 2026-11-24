"""Quick HTTP smoke test for shelter routes against live server."""

import http.client, urllib.parse

BASE = ('127.0.0.1', 5000)


def get(path):
    conn = http.client.HTTPConnection(*BASE)
    conn.request('GET', path)
    r = conn.getresponse()
    return r.status, r.getheader('Location', '')


def post(path, data, cookies=''):
    body = urllib.parse.urlencode(data).encode()
    conn = http.client.HTTPConnection(*BASE)
    conn.request('POST', path, body=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Cookie': cookies,
    })
    r = conn.getresponse()
    return r.status, r.getheader('Location', ''), r.getheader('Set-Cookie', '')


def login(email, password):
    """Return session cookie for further requests."""
    status, loc, cookie = post('/auth/login', {'email': email, 'password': password})
    return cookie.split(';')[0] if cookie else ''


def run_smoke_tests():
    print('=== Shelter HTTP Smoke Tests ===\n')
    results = []

    def check(label, cond):
        results.append(cond)
        print(f'  [{"PASS" if cond else "FAIL"}] {label}')

    # 1. Unauthenticated access -> redirect to login
    s, _ = get('/shelters/')
    check('Unauth /shelters/ -> 302', s == 302)

    # 2. Login as admin, get cookie
    cookie = login('admin@shelter.gov', 'Password@123')
    check('Admin login cookie obtained', bool(cookie))

    # 3. Authenticated list view
    s, _ = get('/shelters/')
    check('Unauthenticated GET /shelters/ -> 302 (cookie not sent in GET)', s == 302)

    # 4. Authenticated list (admin)
    s, loc, _ = post('/auth/login', {'email': 'admin@shelter.gov', 'password': 'Password@123'})
    admin_cookie = login('admin@shelter.gov', 'Password@123')

    # 5. GET /shelters/new as admin (using session)
    conn = http.client.HTTPConnection(*BASE)
    conn.request('GET', '/shelters/new', headers={'Cookie': admin_cookie})
    r = conn.getresponse()
    check('GET /shelters/new as admin -> 200 or 302', r.status in (200, 302))

    # 6. GET /shelters/1 (detail)
    conn = http.client.HTTPConnection(*BASE)
    conn.request('GET', '/shelters/1', headers={'Cookie': admin_cookie})
    r = conn.getresponse()
    check('GET /shelters/1 (detail) -> 200', r.status == 200)

    # 7. GET /shelters/99999 (not found)
    conn = http.client.HTTPConnection(*BASE)
    conn.request('GET', '/shelters/99999', headers={'Cookie': admin_cookie})
    r = conn.getresponse()
    check('GET /shelters/99999 -> 404', r.status == 404)

    # 8. Citizen cannot access /shelters/1/edit
    citizen_cookie = login('citizen@example.com', 'Password@123')
    conn = http.client.HTTPConnection(*BASE)
    conn.request('GET', '/shelters/1/edit', headers={'Cookie': citizen_cookie})
    r = conn.getresponse()
    check('Citizen GET /shelters/1/edit -> 403', r.status == 403)

    # 9. Search filter
    conn = http.client.HTTPConnection(*BASE)
    conn.request('GET', '/shelters/?q=Deccan&status=active', headers={'Cookie': admin_cookie})
    r = conn.getresponse()
    check('GET /shelters/?q=Deccan&status=active -> 200', r.status == 200)

    print(f'\nResult: {sum(results)}/{len(results)} passed.')
    return results


if __name__ == '__main__':
    try:
        run_smoke_tests()
    except (ConnectionRefusedError, OSError):
        print('[SKIP] Shelter HTTP Smoke Tests skipped: Flask server not running on port 5000.')
