TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
FACTORY_LOGINS = ("special-place-administrator", "moldwright-factory[bot]", "moldwright-factory", "app/moldwright-factory")


def trusted(item):
    who = item.get("user") or item.get("author") or {}
    association = item.get("author_association") or item.get("authorAssociation")
    return association in TRUSTED_ASSOCIATIONS or who.get("login") in FACTORY_LOGINS
