import requests

from ui import err


def gh_session(token):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return s


def gh_get(s, path, params=None):
    url = f"https://api.github.com{path}"
    try:
        r = s.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        err(f"GitHub API error {e.response.status_code}: {path}")
        return None
    except Exception as e:
        err(f"Request failed: {e}")
        return None
