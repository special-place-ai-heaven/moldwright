import json

TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
OWNER_LOGIN = "special-place-administrator"
BOT_LOGIN = "moldwright-factory[bot]"
APP_AUTHOR = "app/moldwright-factory"
REST_FIELDS = ".[] | {user: {login: .user.login, type: .user.type}, author_association, body}"


def _who(item):
    return item.get("user") or item.get("author") or {}


def person(item):
    association = item.get("author_association") or item.get("authorAssociation")
    return association in TRUSTED_ASSOCIATIONS or _who(item).get("login") == OWNER_LOGIN


def factory(item):
    who = _who(item)
    login = who.get("login")
    return (login == BOT_LOGIN and who.get("type") == "Bot") or login == APP_AUTHOR


def trusted(item):
    return person(item) or factory(item)


def comments(gh, repo, n):
    out = gh(["api", "repos/%s/issues/%d/comments" % (repo, int(n)), "--paginate", "--jq", REST_FIELDS])
    return [json.loads(line) for line in out.splitlines() if line.strip()]
