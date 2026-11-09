"""Lee data/league.json y genera data/resumen.json: un archivo pequeño con todo ya calculado
(valor de cada jugador, partidos que le quedan, proyección del matchup, necesidades de cada equipo,
waivers recomendados y trades realistas). Solo usa la biblioteca estándar de Python."""
import json, os, datetime, itertools

SRC, OUT = "data/league.json", "data/resumen.json"
ACTIVE_SLOTS = ["PG", "SG", "SF", "PF", "C", "G", "F", "UT", "UT", "UT"]
SLOT_OK = {"PG": {"PG"}, "SG": {"SG"}, "SF": {"SF"}, "PF": {"PF"}, "C": {"C"},
           "G": {"PG", "SG", "G"}, "F": {"SF", "PF", "F"}, "UT": None}
# Pesos del valor: forma reciente pesa más, la proyección de ESPN suaviza muestras pequeñas.
WEIGHTS = {"ult7": 0.10, "ult15": 0.30, "ult30": 0.25, "proyeccion": 0.35}
TRADE_MARGIN = 0.12      # diferencia máxima de valor de trade para considerar un trade "justo"
STAR_EXP = 1.3           # prima por calidad: un jugador de 30 vale más que dos de 20 (consolidación)
TOP_TRADES_PER_TEAM = 2
TOP_TRADES = 12


def r(x, n=1):
    return round(x, n) if isinstance(x, (int, float)) else x


def fp(p, k):
    s = p["stats"].get(k) or {}
    return s.get("fpts_prom")


def valor(p):
    num = den = 0.0
    for k, w in WEIGHTS.items():
        v = fp(p, k)
        if v is None:
            continue
        pj = (p["stats"].get(k) or {}).get("PJ") or 0
        if k != "proyeccion" and pj < 3:      # muestras de 1-2 partidos pesan la mitad
            w *= 0.5
        num += v * w; den += w
    return num / den if den else 0.0


def disponible(p):
    return p.get("lesion") not in ("OUT", "SUSPENSION")


def can_play(p, slot):
    ok = SLOT_OK[slot]
    return ok is None or any(s in ok for s in p["slots_elegibles"])


FIXED = ["PG", "SG", "SF", "PF", "C", "G", "F"]
NSTATE = (1 << 7) * 4
_memo = {}


def _masks(p):
    if "_m" not in p:
        p["_m"] = [i for i, sl in enumerate(FIXED) if can_play(p, sl)]
    return p["_m"]


def lineup_value(players):
    """Valor de la alineación óptima (10 slots) por programación dinámica; con caché."""
    pool = tuple(sorted(p["id"] for p in players if disponible(p)))
    if pool in _memo:
        return _memo[pool]
    NEG = -1.0
    best = [NEG] * NSTATE; best[0] = 0.0
    for p in players:
        if not disponible(p):
            continue
        v = p["valor"]; ms = _masks(p); nxt = best[:]
        for st in range(NSTATE):
            cur = best[st]
            if cur < 0:
                continue
            mask, ut = st >> 2, st & 3
            for i in ms:
                if not mask & (1 << i):
                    k = ((mask | (1 << i)) << 2) | ut
                    if nxt[k] < cur + v: nxt[k] = cur + v
            if ut < 3:
                k = st + 1
                if nxt[k] < cur + v: nxt[k] = cur + v
        best = nxt
    _memo[pool] = max(best)
    return _memo[pool]


def lineup(players, key="valor"):
    """Alineación óptima con asignación (se usa pocas veces: solo para mostrar)."""
    pool = [p for p in players if disponible(p)]
    best = {(0, 0): (0.0, ())}
    for p in pool:
        nxt = dict(best)
        for (mask, ut), (tot, asg) in best.items():
            for i in _masks(p):
                if not mask & (1 << i):
                    k = (mask | (1 << i), ut); v = tot + p[key]
                    if k not in nxt or nxt[k][0] < v: nxt[k] = (v, asg + ((FIXED[i], p),))
            if ut < 3:
                k = (mask, ut + 1); v = tot + p[key]
                if k not in nxt or nxt[k][0] < v: nxt[k] = (v, asg + (("UT", p),))
        best = nxt
    tot, asg = max(best.values(), key=lambda x: x[0])
    order = {sl: i for i, sl in enumerate(FIXED + ["UT"])}
    return tot, sorted(asg, key=lambda x: order[x[0]])


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    L = d["liga"]
    me_id = L["mi_team_id"]
    today = L["dia_actual_scoring_period"]
    per_now = L["periodo_matchup_actual"]
    acq_limit = (L.get("adquisiciones") or {}).get("matchupAcquisitionLimit")

    # ---- fechas y periodos (semanas lunes-domingo, ajustadas al periodo que reporta ESPN) ----
    upd = datetime.datetime.strptime(d["actualizado_utc"], "%Y-%m-%d %H:%M") - datetime.timedelta(hours=5)
    day1 = upd.date() - datetime.timedelta(days=today - 1)
    monday0 = day1 - datetime.timedelta(days=day1.weekday())
    date_of = lambda sp: day1 + datetime.timedelta(days=sp - 1)
    raw_per = lambda sp: 1 + (date_of(sp) - monday0).days // 7
    off = per_now - raw_per(today)
    period_of = lambda sp: raw_per(sp) + off
    days_now = [sp for sp in range(today, today + 8) if period_of(sp) == per_now]
    days_next = [sp for sp in range(today, today + 15) if period_of(sp) == per_now + 1]
    cal = d.get("calendario_nba_dias_con_partido") or {}
    cal = {k: set(v) for k, v in cal.items() if isinstance(v, list)}

    def games(p, days):
        return sum(1 for sp in days if sp in cal.get(p["equipo_nba"], set()))

    # ---- enriquecer jugadores ----
    teams = d["equipos"]
    names = {t["id"]: t["nombre"] for t in teams}
    allp = []
    for t in teams:
        for p in t["roster"]:
            p["_team"] = t["id"]; allp.append(p)
    for p in d["agentes_libres"]:
        p["_team"] = None; allp.append(p)
    for p in allp:
        p["valor"] = valor(p)
        p["pj_semana"] = games(p, days_now)
        p["pj_prox"] = games(p, days_next)

    fa = [p for p in d["agentes_libres"] if disponible(p)]
    fa.sort(key=lambda p: -p["valor"])
    reemplazo = sum(p["valor"] for p in fa[:5]) / max(1, len(fa[:5]))
    for p in allp:
        p["vsr"] = max(0.0, p["valor"] - reemplazo)       # valor sobre reemplazo (para trades)
        if p.get("lesion") == "OUT":
            p["vsr"] *= 0.6                                # lesionado: nadie lo paga a precio completo
        p["vt"] = p["vsr"] ** STAR_EXP                     # valor de trade (con prima por estrellas)

    rostered = sorted([p for p in allp if p["_team"]], key=lambda p: -p["valor"])
    for i, p in enumerate(rostered, 1):
        p["rank_liga"] = i

    def pj(p, extra=()):
        o = {"id": p["id"], "nombre": p["nombre"], "nba": p["equipo_nba"], "pos": "/".join(
            s for s in p["slots_elegibles"] if s in ("PG", "SG", "SF", "PF", "C")), "valor": r(p["valor"]),
            "ult15": r(fp(p, "ult15")), "proy": r(fp(p, "proyeccion")), "estado": p["lesion"],
            "pj_semana": p["pj_semana"], "pj_prox": p["pj_prox"]}
        if p.get("rank_liga"): o["rank"] = p["rank_liga"]
        for k in extra: o[k] = p.get(k)
        return o

    # ---- perfil de cada equipo ----
    pos_avg = {}
    prof = {}
    for t in teams:
        total, filled = lineup(t["roster"])
        by_pos = {}
        for pos in ["PG", "SG", "SF", "PF", "C"]:
            elig = sorted([p["valor"] for p in t["roster"] if disponible(p) and pos in p["slots_elegibles"]], reverse=True)
            by_pos[pos] = sum(elig[:2])
        prof[t["id"]] = {"total": total, "by_pos": by_pos, "lineup": filled}
    for pos in ["PG", "SG", "SF", "PF", "C"]:
        pos_avg[pos] = sum(prof[t["id"]]["by_pos"][pos] for t in teams) / len(teams)

    ranked = sorted(teams, key=lambda t: (-int(t["record"].split("-")[0]), -t["puntos_a_favor"]))
    pos_tabla = {t["id"]: i for i, t in enumerate(ranked, 1)}

    def needs(tid):
        bp = prof[tid]["by_pos"]
        diffs = sorted(((bp[k] - pos_avg[k]) / pos_avg[k] for k in bp), key=lambda x: x)
        return [k for k in sorted(bp, key=lambda k: (bp[k] - pos_avg[k]) / pos_avg[k]) if (bp[k] - pos_avg[k]) / pos_avg[k] < -0.08][:2]

    def strengths(tid):
        bp = prof[tid]["by_pos"]
        return [k for k in sorted(bp, key=lambda k: -(bp[k] - pos_avg[k]) / pos_avg[k]) if (bp[k] - pos_avg[k]) / pos_avg[k] > 0.08][:2]

    # proyección de lo que resta de la semana: por día, mejores 10 disponibles que juegan
    def proj_rest(roster):
        tot = 0.0
        for sp in days_now:
            if sp == today:
                continue   # el día en curso ya está parcialmente en el marcador
            playing = [p for p in roster if disponible(p) and sp in cal.get(p["equipo_nba"], set())]
            tot += lineup_value(playing)
        return tot

    equipos_out = []
    for t in teams:
        tid = t["id"]
        equipos_out.append({
            "id": tid, "nombre": t["nombre"], "record": t["record"], "posicion_tabla": pos_tabla[tid],
            "pts_favor": t["puntos_a_favor"], "fuerza_alineacion": r(prof[tid]["total"]),
            "necesita": needs(tid), "fuerte_en": strengths(tid),
            "lesionados": [p["nombre"] for p in t["roster"] if p["lesion"] == "OUT"],
            "roster": [pj(p) for p in sorted(t["roster"], key=lambda p: -p["valor"])],
        })

    # ---- matchup actual ----
    me_name = names[me_id]
    cur = next((m for m in d["matchups"] if m["periodo"] == per_now and me_name in (m["local"], m["visitante"])), None)
    matchup = None
    if cur:
        home = cur["local"] == me_name
        rival_name = cur["visitante"] if home else cur["local"]
        rival = next(t for t in teams if t["nombre"] == rival_name)
        me_t = next(t for t in teams if t["id"] == me_id)
        mis, sus = (cur["pts_local"], cur["pts_visitante"]) if home else (cur["pts_visitante"], cur["pts_local"])
        pm, pr = proj_rest(me_t["roster"]), proj_rest(rival["roster"])
        matchup = {"rival": rival_name, "mis_puntos": mis, "sus_puntos": sus,
                   "proy_resto_mio": r(pm), "proy_resto_rival": r(pr),
                   "proy_final_mio": r(mis + pm), "proy_final_rival": r(sus + pr),
                   "dias_restantes": len([x for x in days_now if x > today]),
                   "mis_partidos_restantes": sum(games(p, [x for x in days_now if x > today]) for p in me_t["roster"] if disponible(p)),
                   "sus_partidos_restantes": sum(games(p, [x for x in days_now if x > today]) for p in rival["roster"] if disponible(p))}

    # ---- waivers ----
    me_t = next(t for t in teams if t["id"] == me_id)
    my_sorted = sorted(me_t["roster"], key=lambda p: p["valor"])
    drop_cands = [p for p in my_sorted if disponible(p)][:3]
    waivers = []
    for p in fa[:40]:
        worst = drop_cands[0] if drop_cands else None
        mejora = p["valor"] - (worst["valor"] if worst else 0)
        if mejora > 0.5:
            waivers.append(pj(p, ()) | {"tipo": p.get("estado"), "pct_rostered": p.get("pct_rostered"),
                                         "mejora_vs_peor": r(mejora), "soltaria": worst["nombre"] if worst else None})
    waivers = waivers[:10]
    streaming = sorted([p for p in fa[:60] if p["pj_semana"]], key=lambda p: -(p["valor"] * games(p, [x for x in days_now if x > today])))[:5]

    # ---- adquisiciones: 1 por cada día con partidos; plan de streaming con un cupo rotativo ----
    game_days = set().union(*cal.values()) if cal else set()
    dias_sem = [sp for sp in days_now if sp in game_days]
    dias_prox = [sp for sp in days_next if sp in game_days]
    libres = [p for p in fa if p.get("estado") == "FREEAGENT"]
    plan_stream = []
    usados = {w["id"] for w in waivers[:1]}       # la mejor adición de waivers se queda fija, no se rota
    for sp in [x for x in dias_sem + dias_prox if x > today][:10]:
        juegan = [p for p in libres if p["id"] not in usados and sp in cal.get(p["equipo_nba"], set())
                  and p["valor"] >= 0.8 * reemplazo]
        if not juegan:
            continue
        b = max(juegan, key=lambda p: p["valor"])
        usados.add(b["id"])
        plan_stream.append({"fecha": str(date_of(sp)), "semana": "actual" if sp in days_now else "proxima",
                            "agregar": b["nombre"], "nba": b["equipo_nba"], "valor": r(b["valor"]),
                            "estado": b["lesion"]})
    adquisiciones = {"regla": "1 adquisición de agencia libre por cada día con partidos; los trades no cuentan",
                     "dias_con_partido_semana_actual": len(dias_sem),
                     "dias_con_partido_restantes_hoy_incluido": len([x for x in dias_sem if x >= today]),
                     "dias_con_partido_proxima_semana": len(dias_prox)}

    # ---- trades realistas ----
    def lineup_gain(roster, out_ids, inc):
        new = [p for p in roster if p["id"] not in out_ids] + list(inc)
        return lineup_value(new) - lineup_value(roster)

    trades = []
    for t in teams:
        if t["id"] == me_id:
            continue
        cands = []
        mine = sorted([p for p in me_t["roster"] if p["vsr"] > 0], key=lambda p: -p["valor"])[:10]
        theirs = sorted([p for p in t["roster"] if p["vsr"] > 0], key=lambda p: -p["valor"])[:9]
        shapes = [(1, 1), (2, 1), (1, 2), (2, 2)]
        for a, b in shapes:
            for give in itertools.combinations(mine, a):
                for get in itertools.combinations(theirs, b):
                    vg, vr = sum(p["vt"] for p in give), sum(p["vt"] for p in get)
                    if vg <= 0 or vr <= 0:
                        continue
                    if abs(vg - vr) / max(vg, vr) > TRADE_MARGIN:
                        continue
                    # quien recibe 1 por 2 debe ganar en calidad, no solo en cantidad
                    g_me = lineup_gain(me_t["roster"], {p["id"] for p in give}, get)
                    if g_me <= 0.5:
                        continue
                    g_them = lineup_gain(t["roster"], {p["id"] for p in get}, give)
                    if g_them < -0.5:
                        continue
                    # el otro equipo no cede a su mejor jugador por piezas de menor rango
                    best_theirs = max(t["roster"], key=lambda p: p["valor"])
                    if any(p["id"] == best_theirs["id"] for p in get) and max(p["valor"] for p in give) < best_theirs["valor"] * 0.9:
                        continue
                    fit = len({pos for p in give for pos in p["slots_elegibles"]} & set(needs(t["id"])))
                    score = g_me + 0.6 * g_them + 1.5 * fit
                    cands.append((score, give, get, g_me, g_them, vg, vr, fit))
        cands.sort(key=lambda x: -x[0])
        seen_g, seen_r = set(), set()
        for c in cands:
            kg = tuple(sorted(p["id"] for p in c[1])); kr = tuple(sorted(p["id"] for p in c[2]))
            if kg in seen_g or kr in seen_r:
                continue
            seen_g.add(kg); seen_r.add(kr)
            score, give, get, g_me, g_them, vg, vr, fit = c
            trades.append({"con": t["nombre"], "doy": [pj(p) for p in give], "recibo": [pj(p) for p in get],
                           "mejora_mi_alineacion": r(g_me), "mejora_su_alineacion": r(g_them),
                           "valor_trade_doy": r(vg), "valor_trade_recibo": r(vr), "cubre_necesidad_rival": bool(fit),
                           "necesidades_rival": needs(t["id"]), "puntaje": r(score),
                           "yo_debo_soltar": max(0, len(get) - len(give)), "rival_debe_soltar": max(0, len(give) - len(get)),
                           "incluye_lesionado_out": any(p["lesion"] == "OUT" for p in give + get)})
            if len([x for x in trades if x["con"] == t["nombre"]]) >= TOP_TRADES_PER_TEAM:
                break
    trades.sort(key=lambda x: -x["puntaje"])
    trades = trades[:TOP_TRADES]

    out = {
        "actualizado_utc": d["actualizado_utc"],
        "liga": {"nombre": L["nombre"], "periodo_actual": per_now, "dia_scoring": today,
                 "fecha_hoy": str(date_of(today)),
                 "semana": f"{date_of(days_now[0])} a {date_of(days_now[-1])}" if days_now else None,
                 "puntuacion": {x["stat"]: x["puntos"] for x in L["puntuacion"]},
                 "slots": L["slots_alineacion"], "adquisiciones": adquisiciones,
                 "waivers_se_procesan": (L.get("adquisiciones") or {}).get("waiverProcessDays"),
                 "trades": L.get("trades"), "valor_reemplazo": r(reemplazo),
                 "nota_valor": "valor = promedio ponderado de fpts (ult7 10%, ult15 30%, ult30 25%, proyección ESPN 35%); vsr = valor sobre el nivel de los 5 mejores agentes libres (x0.6 si está OUT); valor_trade = vsr^1.3 (prima por estrellas)"},
        "mi_equipo": {"nombre": me_name, "record": me_t["record"], "posicion_tabla": pos_tabla[me_id],
                      "fuerza_alineacion": r(prof[me_id]["total"]), "necesita": needs(me_id), "fuerte_en": strengths(me_id),
                      "alineacion_optima": [{"slot": s, "jugador": p["nombre"], "valor": r(p["valor"]), "pj_semana": p["pj_semana"]} for s, p in prof[me_id]["lineup"]]},
        "matchup_actual": matchup,
        "waivers_recomendados": waivers,
        "streaming_esta_semana": [pj(p) for p in streaming],
        "plan_streaming": {"nota": "cupo rotativo: se suelta al streamer del día anterior (el primero reemplaza al peor de candidatos_a_soltar); excluye la mejor adición de waivers_recomendados, que se queda fija",
                           "dias": plan_stream},
        "candidatos_a_soltar": [pj(p) for p in drop_cands],
        "trades_sugeridos": trades,
        "tabla": [{"pos": pos_tabla[t["id"]], "equipo": t["nombre"], "record": t["record"], "pts_favor": t["puntos_a_favor"]} for t in ranked],
        "equipos": equipos_out,
        "agentes_libres_top": [pj(p, ("pct_rostered",)) | {"tipo": p.get("estado")} for p in fa[:40]],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK resumen: {len(trades)} trades, {len(waivers)} waivers, {os.path.getsize(OUT)//1024} KB")


if __name__ == "__main__":
    main()
