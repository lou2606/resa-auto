"""Réserve la place fixe sur Deskbird dès l'ouverture (7h, J-20), lundi à jeudi.

Cron (Europe/Paris): 59 6 * * 1-5  cd ~/PycharmProjects/resa_auto && .venv/bin/python main.py
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

PARIS = ZoneInfo("Europe/Paris")
DAYS_AHEAD = 20
DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
OPEN_AT = (7, 0)
GIVE_UP_AFTER = timedelta(minutes=5)

# users.json: {"firebase_api_key": "...", "users": [{"name": "x", "refresh_token": "...",
#   "days": ["lun", "mar", "mer", "jeu"],
#   "office": "Paris - The 44", "desks": ["191", "192", "185-190"],   (bureaux par préférence, résolus via l'API)
#   ou "spots": [{"resourceId": "..", "zoneItemId": 0, "workspaceId": ".."}, ...]}]}   (spots par ordre de préférence)
# "token" (bearer copié du navigateur) peut remplacer "refresh_token" pour un test ponctuel.
CONFIG = json.load(open(os.path.join(os.path.dirname(__file__), "users.json")))


def id_token(user):
    if "token" in user:
        return user["token"]
    r = requests.post(
        "https://securetoken.googleapis.com/v1/token",
        params={"key": CONFIG["firebase_api_key"]},
        data={"grant_type": "refresh_token", "refresh_token": user["refresh_token"]},
    )
    r.raise_for_status()
    return r.json()["id_token"]


def day_window(day):
    """07h-19h Paris, comme la résa "journée" de l'UI, en ms epoch."""
    start = datetime(day.year, day.month, day.day, 7, tzinfo=PARIS)
    return int(start.timestamp() * 1000), int((start + timedelta(hours=12)).timestamp() * 1000)


API = "https://api.deskbird.com"


def expand(desks):
    """["191", "185-187"] -> ["191", "185", "186", "187"] (ordre de préférence conservé)."""
    out = []
    for d in desks:
        lo, _, hi = str(d).partition("-")
        out += [str(n) for n in range(int(lo), int(hi or lo) + 1)] if hi else [str(d)]
    return out


def resolve_spots(user, headers):
    """"office" + "desks" (noms de bureaux, par préférence) -> spots Deskbird, ou "spots" tels quels."""
    if "spots" in user:
        return user["spots"]
    get = lambda path, **params: requests.get(f"{API}/{path}", params=params, headers=headers).json()
    office = next(w for w in get("v1.1/company/internalWorkspaces", companyId=CONFIG["company_id"])["results"]
                  if w["name"] == user["office"] and w["isActive"])
    by_name = {}  # "Desk 191" -> spot (le préfixe évite les collisions avec les casiers)
    for floor in get("v1/floors", officeId=office["id"])["data"]:
        if floor["status"] != "active":
            continue
        for res in get(f"v1/floors/{floor['id']}", include="resources,zones", statuses="active").get("resources", []):
            by_name[res["name"]] = {
                "resourceId": res["zoneId"], "zoneItemId": int(res["id"]), "workspaceId": office["id"]}
    names = [f"Desk {d}" for d in expand(user["desks"])]
    missing = [n for n in names if n not in by_name]
    if missing:
        print(f"{user['name']}: bureaux introuvables dans {user['office']}: {missing}")
    return [by_name[n] for n in names if n in by_name]


def book(user, headers, spots, target, deadline):
    """Essaie les places de l'utilisateur dans l'ordre, en boucle, jusqu'à un succès ou la deadline."""
    start, end = day_window(target)
    while spots and datetime.now(PARIS) < deadline:
        for spot in spots:
            body = {"bookings": [{"bookingStartTime": start, "bookingEndTime": end, "isAnonymous": False, **spot}]}
            r = requests.post(f"{API}/v1.1/bookings", json=body, headers=headers)
            print(datetime.now(PARIS).isoformat(), user["name"], target, spot["zoneItemId"], r.status_code, r.text[:400])
            if r.ok and r.json().get("successfulBookings"):  # Deskbird répond 200 même si la place est refusée
                return True
        time.sleep(0.5)
    return False


def main():
    now = datetime.now(PARIS)
    test = len(sys.argv) > 1  # `main.py 2026-10-22`: réserve ce jour tout de suite
    target = datetime.fromisoformat(sys.argv[1]).date() if test else (now + timedelta(days=DAYS_AHEAD)).date()
    users = [u for u in CONFIG["users"] if DAYS[target.weekday()] in u["days"]]
    if not users:
        return print(f"{target}: personne à réserver")

    # token + résolution des places avant l'ouverture, pour tirer dès 7h00:00
    prepared = []
    for u in users:
        headers = {"authorization": f"Bearer {id_token(u)}", "origin": "https://app.deskbird.com"}
        prepared.append((u, headers, resolve_spots(u, headers)))

    opening = now.replace(hour=OPEN_AT[0], minute=OPEN_AT[1], second=0, microsecond=0)
    if not test:
        time.sleep(max(0, (opening - datetime.now(PARIS)).total_seconds()))
    deadline = (now if test else max(opening, datetime.now(PARIS))) + GIVE_UP_AFTER  # max: runner GitHub parfois en retard

    with ThreadPoolExecutor(len(users)) as pool:
        results = list(pool.map(lambda p: book(*p, target, deadline), prepared))
    failed = [u["name"] for u, ok in zip(users, results) if not ok]
    if failed:
        sys.exit(f"échec réservation {target}: {', '.join(failed)}")


if __name__ == "__main__":
    assert day_window(datetime(2026, 10, 21).date())[0] == 1792558800000  # = ta résa capturée
    assert expand(["191", "192", "185-187"]) == ["191", "192", "185", "186", "187"]
    main()
