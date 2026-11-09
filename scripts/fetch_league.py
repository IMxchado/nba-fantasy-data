"""Descarga los datos de una liga privada de ESPN Fantasy Basketball y los guarda en data/league.json."""
import json, os, sys, datetime, urllib.request, urllib.error

LEAGUE_ID = os.environ["LEAGUE_ID"]
TEAM_ID = int(os.environ.get("TEAM_ID", "0"))
SEASON = os.environ.get("SEASON", "2027")
COOKIES = f"espn_s2={os.environ['ESPN_S2']}; SWID={os.environ['ESPN_SWID']}"
BASE = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{SEASON}"
LEAGUE = f"{BASE}/segments/0/leagues/{LEAGUE_ID}"

STATS = {0:"PTS",1:"BLK",2:"STL",3:"AST",4:"OREB",5:"DREB",6:"REB",7:"EJ",8:"FF",9:"PF",10:"TF",
         11:"TO",12:"DQ",13:"FGM",14:"FGA",15:"FTM",16:"FTA",17:"3PM",18:"3PA",19:"FG%",20:"FT%",
         21:"3P%",22:"AFG%",23:"FGMI",24:"FTMI",25:"3PMI",37:"DD",38:"TD",39:"QD",40:"MIN",41:"GS",42:"GP"}
SLOTS = {0:"PG",1:"SG",2:"SF",3:"PF",4:"C",5:"G",6:"F",7:"SG/SF",8:"G/F",9:"PF/C",10:"F/C",
         11:"UT",12:"BE",13:"IR",14:"?",15:"?"}
POS = {1:"PG",2:"SG",3:"SF",4:"PF",5:"C"}
PRO = {0:"FA",1:"ATL",2:"BOS",3:"NOP",4:"CHI",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GSW",10:"HOU",
       11:"IND",12:"LAC",13:"LAL",14:"MIA",15:"MIL",16:"MIN",17:"BKN",18:"NYK",19:"ORL",20:"PHI",
       21:"PHX",22:"POR",23:"SAC",24:"SAS",25:"OKC",26:"UTA",27:"WAS",28:"TOR",29:"MEM",30:"CHA"}
SPLITS = {(0,0):"temporada",(0,1):"ult7",(0,2):"ult15",(0,3):"ult30",(1,0):"proyeccion"}
KEY_STATS = ["MIN","PTS","REB","AST","STL","BLK","TO","3PM","FGM","FGA","FTM","FTA","FG%","FT%","DD","TD"]


def get(url, views=(), headers=None, params=""):
    q = "&".join(f"view={v}" for v in views)
    full = f"{url}?{q}{('&' + params) if params else ''}"
    req = urllib.request.Request(full, headers={"Cookie": COOKIES, "Accept": "application/json",
                                                "User-Agent": "Mozilla/5.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit("ERROR: ESPN rechazó el acceso. Las cookies ESPN_S2/ESPN_SWID caducaron: renuévalas en GitHub Secrets.")
        raise


def r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def player_info(p, season):
    out = {
        "id": p.get("id"), "nombre": p.get("fullName"), "equipo_nba": PRO.get(p.get("proTeamId"), p.get("proTeamId")),
        "posicion": POS.get(p.get("defaultPositionId"), p.get("defaultPositionId")),
        "slots_elegibles": [SLOTS[s] for s in p.get("eligibleSlots", []) if s in SLOTS and s not in (12, 13, 14, 15)],
        "lesion": p.get("injuryStatus") or ("OUT" if p.get("injured") else "ACTIVE"),
        "pct_rostered": r((p.get("ownership") or {}).get("percentOwned"), 1),
        "stats": {},
    }
    for s in p.get("stats", []):
        if str(s.get("seasonId")) != str(season):
            continue
        key = SPLITS.get((s.get("statSourceId"), s.get("statSplitTypeId")))
        if not key:
            continue
        avg = s.get("averageStats") or {}
        out["stats"][key] = {
            "fpts_prom": r(s.get("appliedAverage")), "fpts_total": r(s.get("appliedTotal"), 1),
            "PJ": (s.get("stats") or {}).get("42"),
            **{STATS[int(k)]: r(v) for k, v in avg.items() if k.isdigit() and STATS.get(int(k)) in KEY_STATS},
        }
    return out


def main():
    league = get(LEAGUE, ["mSettings", "mTeam", "mRoster", "mMatchupScore", "mStatus"])
    season = league.get("seasonId", SEASON)
    st = league.get("settings", {})
    scoring = [{"stat": STATS.get(i["statId"], i["statId"]), "puntos": i["points"]}
               for i in st.get("scoringSettings", {}).get("scoringItems", [])]
    roster_slots = {SLOTS.get(int(k), k): v for k, v in st.get("rosterSettings", {}).get("lineupSlotCounts", {}).items() if v}

    teams = []
    for t in league.get("teams", []):
        rec = (t.get("record") or {}).get("overall", {})
        roster = []
        for e in (t.get("roster") or {}).get("entries", []):
            pi = player_info(e["playerPoolEntry"]["player"], season)
            pi["slot_actual"] = SLOTS.get(e.get("lineupSlotId"), e.get("lineupSlotId"))
            roster.append(pi)
        teams.append({
            "id": t["id"], "nombre": t.get("name") or f"{t.get('location','')} {t.get('nickname','')}".strip(),
            "abrev": t.get("abbrev"), "es_mi_equipo": t["id"] == TEAM_ID,
            "record": f"{rec.get('wins',0)}-{rec.get('losses',0)}-{rec.get('ties',0)}",
            "puntos_a_favor": r(rec.get("pointsFor"), 1), "puntos_en_contra": r(rec.get("pointsAgainst"), 1),
            "prioridad_waiver": t.get("waiverRank"),
            "contador_transacciones": t.get("transactionCounter"), "roster": roster,
        })
    names = {t["id"]: t["nombre"] for t in teams}

    matchups = []
    for m in league.get("schedule", []):
        h, a = m.get("home", {}), m.get("away", {})
        matchups.append({"periodo": m.get("matchupPeriodId"),
                         "local": names.get(h.get("teamId")), "pts_local": r(h.get("totalPoints"), 1),
                         "visitante": names.get(a.get("teamId")), "pts_visitante": r(a.get("totalPoints"), 1),
                         "ganador": m.get("winner")})

    flt = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": 150,
                       "filterSlotIds": {"value": list(range(0, 12))},
                       "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
    fa_raw = get(LEAGUE, ["kona_player_info"], {"X-Fantasy-Filter": json.dumps(flt)})
    free_agents = [player_info(x["player"], season) | {"estado": x.get("status")} for x in fa_raw.get("players", [])]

    try:
        pro = get(BASE, ["proTeamSchedules_wl"])
        calendario = {PRO.get(t["id"], t["id"]): sorted(int(k) for k in (t.get("proGamesByScoringPeriod") or {}))
                      for t in pro.get("settings", {}).get("proTeams", []) if t.get("id")}
    except Exception as e:  # el calendario es opcional
        calendario = {"error": str(e)}

    # ---- historial de transacciones (trades aceptados, propuestas, rechazos, waivers y agencia libre) ----
    names_pid = {}
    for t in league.get("teams", []):
        for e in (t.get("roster") or {}).get("entries", []):
            pl = e["playerPoolEntry"]["player"]; names_pid[pl["id"]] = pl.get("fullName")
    for x in fa_raw.get("players", []):
        names_pid[x["player"]["id"]] = x["player"].get("fullName")
    tx_types = ["TRADE_ACCEPT", "TRADE_PROPOSAL", "TRADE_DECLINE", "TRADE_UPHOLD", "TRADE_VETO", "FREEAGENT", "WAIVER"]
    tx_filter = {"transactions": {"filterType": {"value": tx_types}}}
    transacciones, seen = [], set()
    try:
        for sp in range(1, int(league.get("scoringPeriodId") or 1) + 1):
            raw = get(LEAGUE, ["mTransactions2"], {"X-Fantasy-Filter": json.dumps(tx_filter)}, f"scoringPeriodId={sp}")
            for x in raw.get("transactions", []) or []:
                if x.get("id") in seen:
                    continue
                seen.add(x.get("id"))
                fecha = x.get("proposedDate") or x.get("processDate")
                transacciones.append({
                    "id": x.get("id"), "tipo": x.get("type"), "estado": x.get("status"),
                    "fecha_utc": datetime.datetime.fromtimestamp(fecha / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M") if fecha else None,
                    "dia_scoring": x.get("scoringPeriodId"), "equipo": names.get(x.get("teamId"), x.get("teamId")),
                    "relacionada": x.get("relatedTransactionId"),
                    "items": [{"jugador": names_pid.get(i.get("playerId"), i.get("playerId")), "tipo": i.get("type"),
                               "de": names.get(i.get("fromTeamId"), "Agencia libre" if not i.get("fromTeamId") else i.get("fromTeamId")),
                               "a": names.get(i.get("toTeamId"), "Agencia libre" if not i.get("toTeamId") else i.get("toTeamId"))}
                              for i in x.get("items", []) or []],
                })
    except Exception as e:  # el historial es opcional: si falla, no detiene la actualización
        transacciones.append({"error": str(e)})
    transacciones.sort(key=lambda t: t.get("fecha_utc") or "")

    status = league.get("status", {})
    data = {
        "actualizado_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "liga": {"id": LEAGUE_ID, "nombre": st.get("name"), "temporada": season, "mi_team_id": TEAM_ID,
                 "periodo_matchup_actual": status.get("currentMatchupPeriod"),
                 "dia_actual_scoring_period": league.get("scoringPeriodId"),
                 "puntuacion": scoring, "slots_alineacion": roster_slots,
                 "trades": st.get("tradeSettings"), "adquisiciones": st.get("acquisitionSettings"),
                 "calendario_matchups": (st.get("scheduleSettings") or {}).get("matchupPeriods")},
        "equipos": teams, "matchups": matchups, "agentes_libres": free_agents,
        "calendario_nba_dias_con_partido": calendario,
        "transacciones": transacciones,
    }
    os.makedirs("data", exist_ok=True)
    with open("data/league.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK: {len(teams)} equipos, {len(free_agents)} agentes libres, {len(transacciones)} transacciones, {data['actualizado_utc']} UTC")


if __name__ == "__main__":
    main()
