"""Alerte quand un nouveau bureau Deskbird devient actif (ex: "Paris - The 44").

Cron: */10 * * * *  cd ~/PycharmProjects/resa_auto && .venv/bin/python watch.py
users.json: "ntfy_topic": "<topic secret>" (optionnel) pour recevoir le push sur le téléphone via ntfy.sh.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime

import requests

from main import CONFIG, id_token

SOUND = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
STATE = os.path.join(os.path.dirname(__file__), "watch_state.json")  # ids actifs déjà vus


def alert(msg):
    print(msg)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "Deskbird", msg])
    if shutil.which("pw-play"):  # cron n'a pas XDG_RUNTIME_DIR, nécessaire pour atteindre PipeWire
        env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
        for _ in range(3):
            subprocess.run(["pw-play", SOUND], env=env)
    if "ntfy_topic" in CONFIG:
        requests.post(f"https://ntfy.sh/{CONFIG['ntfy_topic']}", data=msg.encode())


def main():
    r = requests.get(
        "https://api.deskbird.com/v1.1/company/internalWorkspaces",
        params={"companyId": CONFIG["company_id"], "includeInactive": "true"},
        headers={"authorization": f"Bearer {id_token(CONFIG['users'][0])}"},
    )
    r.raise_for_status()
    active = {w["id"]: w["name"] for w in r.json()["results"] if w["isActive"]}
    first = not os.path.exists(STATE)  # premier run: on mémorise sans alerter
    seen = set() if first else set(json.load(open(STATE)))
    for i, name in active.items():
        if i not in seen and not first:
            alert(f"Nouveau bureau dispo sur Deskbird : {name} (workspaceId {i})")
    print(datetime.now().isoformat(timespec="seconds"), "ok", len(active), "actifs")
    json.dump(sorted(seen | set(active)), open(STATE, "w"))


if __name__ == "__main__":
    main()
