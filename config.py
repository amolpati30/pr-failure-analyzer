import configparser
import os

JENKINS_CREDS_FILE = os.path.expanduser("~/conf/jenkins.conf")
GH_CREDS_FILE      = os.path.expanduser("~/conf/github.conf")
JENKINS_BASE_URL   = "https://jenkins-csb-satellite-qe-satqe.dno.corp.redhat.com"
CLAUDE_AGENT_NAME  = "test-failure-analyzer"


def load_github_token():
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    if os.path.exists(GH_CREDS_FILE):
        cfg = configparser.ConfigParser()
        cfg.read(GH_CREDS_FILE)
        token = cfg.get("credentials", "token", fallback="")
    return token


def _save_creds_file(path, updates):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = configparser.ConfigParser()
    if os.path.exists(path):
        cfg.read(path)
    if "credentials" not in cfg:
        cfg["credentials"] = {}
    cfg["credentials"].update(updates)
    with open(path, "w") as f:
        cfg.write(f)
    os.chmod(path, 0o600)


def save_github_token(token):
    _save_creds_file(GH_CREDS_FILE, {"token": token})


def load_jenkins_creds():
    user  = os.environ.get("JENKINS_USER", "")
    token = os.environ.get("JENKINS_TOKEN", "")
    if user and token:
        return user, token
    if os.path.exists(JENKINS_CREDS_FILE):
        cfg = configparser.ConfigParser()
        cfg.read(JENKINS_CREDS_FILE)
        user  = cfg.get("credentials", "user",  fallback="")
        token = cfg.get("credentials", "token", fallback="")
    return user, token
