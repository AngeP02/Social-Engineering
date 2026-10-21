"""
questionario_self_report.py
============================
Questionario self-report somministrato dopo il consenso informato,
prima del questionario T0 e delle chat sperimentali.

STRUTTURA (ordine di somministrazione):
  Sezione E  — Dati demografici e stile di vita         (10 item misti)
  Sezione P  — Personalità / BFI-10                     (10 item Likert 7)
  Sezione Q  — Valori / PVQ-10r riformulato             (10 item Likert 7)
  Sezione R  — Preoccupazioni / WDQ-3r                  ( 3 item Likert 7)
  TOTALE scale Likert: 23 item

Scala Likert unica (7 punti, accordo/disaccordo):
  1 Completamente in disaccordo
  2 In forte disaccordo
  3 Piuttosto in disaccordo
  4 Né d'accordo né in disaccordo
  5 Piuttosto d'accordo
  6 In forte accordo
  7 Completamente d'accordo

Riferimenti strumenti:
  BFI-10  : Rammstedt & John (2007), Journal of Research in Personality
  PVQ-10r : adattato da Schwartz et al. (2012), European Journal of Psychology
  WDQ-3r  : adattato da Tallis, Eysenck & Mathews (1994) — 3 domini su 5

Campi JSON popolati:
  non_sensitive  : occupation, education, hobbies, city_or_region,
                   travel_mobility_signals
  private        : age, gender
  psychological  : big_five_personality, personal_values, fears_and_anxieties
  mvp            : primary_fear, dominant_persuasion_lever, primary_desire
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Scala Likert 7 — unica per tutte le sezioni P, Q, R
# ---------------------------------------------------------------------------

SCALA_LIKERT_7 = {
    1: "Completamente in disaccordo",
    2: "In forte disaccordo",
    3: "Piuttosto in disaccordo",
    4: "Né d'accordo né in disaccordo",
    5: "Piuttosto d'accordo",
    6: "In forte accordo",
    7: "Completamente d'accordo",
}


# ---------------------------------------------------------------------------
# Dataclass item
# ---------------------------------------------------------------------------

@dataclass
class ItemSR:
    id: str
    sezione: str
    testo: str
    tipo: str = "likert7"          # likert7 | scelta | multi_scelta | numero
    opzioni: Optional[list] = None
    invertito: bool = False
    campo_profilo: Optional[str] = None
    sottocampo: Optional[str] = None


# ---------------------------------------------------------------------------
# SEZIONE E — Dati demografici e stile di vita
# Popola: age, gender, education, occupation, city_or_region,
#         hobbies, travel_mobility_signals
# ---------------------------------------------------------------------------

SEZIONE_E_SR: list[ItemSR] = [
    ItemSR(
        "P1", "P", "Età",
        tipo="numero",
        campo_profilo="age",
    ),
    ItemSR(
        "P6", "P", "Con quale frequenza viaggia (non considerando i viaggi di lavoro/studio)?",
        tipo="scelta",
        opzioni=[
            "Raramente o mai",
            "1–2 volte l'anno",
            "3–5 volte l'anno",
            "Più di 5 volte l'anno",
        ],
        campo_profilo="travel_mobility_signals",
    ),
    ItemSR(
        "P3", "P", "Titolo di studio più alto conseguito",
        tipo="scelta",
        opzioni=[
            "Scuola media",
            "Diploma superiore",
            "Laurea triennale",
            "Laurea magistrale",
            "Dottorato o specializzazione post-laurea",
        ],
        campo_profilo="education",
    ),
    ItemSR(
        "P4", "P", "Qual è la sua professione o ruolo attuale?",
        tipo="scelta",
        opzioni=[
            "Studente",
            "Ricercatore / dottorando",
            "Docente universitario",
            "Professionista (settore privato)",
            "Libero professionista",
            "Dipendente pubblico",
            "Altro",
        ],
        campo_profilo="occupation",
    ),


    ItemSR(
        "P7", "P",
        "Quali sono i principali interessi o hobby? (si possono selezionare più opzioni)",
        tipo="multi_scelta",
        opzioni=[
            "Sport e attività fisica",
            "Lettura e scrittura",
            "Musica",
            "Arte e creatività",
            "Tecnologia e informatica",
            "Cucina e gastronomia",
            "Viaggi ed esplorazione",
            "Cinema e serie TV",
            "Natura e attività all'aperto",
            "Volontariato e impegno sociale",
        ],
        campo_profilo="hobbies",
    ),
]

SEZIONE_P: list[ItemSR] = [
    ItemSR("Q1",  "Q", "Sono una persona riservata.",
           invertito=True,  campo_profilo="big_five_personality", sottocampo="extraversion"),
    ItemSR("Q2",  "Q", "Mi fido generalmente delle persone.",
           invertito=False, campo_profilo="big_five_personality", sottocampo="agreeableness"),
    ItemSR("Q3",  "Q", "Tendo ad essere pigro/a.",
           invertito=True,  campo_profilo="big_five_personality", sottocampo="conscientiousness"),
    ItemSR("Q4",  "Q", "Sono una persona rilassata, non mi innervosisco facilmente.",
           invertito=True,  campo_profilo="big_five_personality", sottocampo="neuroticism"),
    ItemSR("Q5",  "Q", "Ho scarso interesse per l'arte e la cultura.",
           invertito=True,  campo_profilo="big_five_personality", sottocampo="openness"),
    ItemSR("Q6",  "Q", "Sono una persona socievole ed estroversa.",
           invertito=False, campo_profilo="big_five_personality", sottocampo="extraversion"),
    ItemSR("Q7",  "Q", "Tendo a trovare difetti negli altri.",
           invertito=True,  campo_profilo="big_five_personality", sottocampo="agreeableness"),
    ItemSR("Q8",  "Q", "Porto a termine i compiti in modo accurato.",
           invertito=False, campo_profilo="big_five_personality", sottocampo="conscientiousness"),
    ItemSR("Q9",  "Q", "Mi agito facilmente.",
           invertito=False, campo_profilo="big_five_personality", sottocampo="neuroticism"),
    ItemSR("Q10", "Q", "Ho una vivace fantasia e mi piace immaginare scenari nuovi.",
           invertito=False, campo_profilo="big_five_personality", sottocampo="openness"),
]


# ---------------------------------------------------------------------------
# SEZIONE Q — Valori (PVQ-10r, riformulato in prima persona)
# Adattato da Schwartz et al. (2012)
# Un item per ciascuno dei 10 tipi motivazionali di base
# ---------------------------------------------------------------------------

SEZIONE_Q: list[ItemSR] = [
    ItemSR("R1",  "R",
           "Per me è importante avere idee originali e fare le cose a modo mio.",
           campo_profilo="personal_values", sottocampo="autonomia"),
    ItemSR("R2",  "R",
           "Amo le situazioni nuove e stimolanti: la routine mi pesa.",
           campo_profilo="personal_values", sottocampo="stimolazione"),
    ItemSR("R3",  "R",
           "Credo che tutti gli esseri umani debbano essere trattati con uguale giustizia.",
           campo_profilo="personal_values", sottocampo="universalismo"),
    ItemSR("R4",  "R",
           "Aiutare le persone che mi stanno vicino è una priorità nella mia vita.",
           campo_profilo="personal_values", sottocampo="benevolenza"),
    ItemSR("R5",  "R",
           "Rispettare tradizioni e usanze della mia cultura è importante per me.",
           campo_profilo="personal_values", sottocampo="tradizione"),
    ItemSR("R6",  "R",
           "Mi comporto sempre in modo corretto, anche quando nessuno mi osserva.",
           campo_profilo="personal_values", sottocampo="conformismo"),
    ItemSR("R7",  "R",
           "La sicurezza e la stabilità nella mia vita quotidiana vengono prima di tutto.",
           campo_profilo="personal_values", sottocampo="sicurezza"),
    ItemSR("R8",  "R",
           "Tengo molto ad avere successo e a che gli altri riconoscano i miei risultati.",
           campo_profilo="personal_values", sottocampo="riuscita"),
    ItemSR("R9",  "R",
           "Voglio avere influenza sulle decisioni e sulle persone che mi circondano.",
           campo_profilo="personal_values", sottocampo="potere"),
    ItemSR("R10", "R",
           "Godermi la vita e i piaceri quotidiani è qualcosa a cui tengo molto.",
           campo_profilo="personal_values", sottocampo="edonismo"),
]


# ---------------------------------------------------------------------------
# SEZIONE R — Preoccupazioni (WDQ-3r, 3 domini su 5)
# Adattato da Tallis, Eysenck & Mathews (1994)
# Rimossi: relazioni affettive e questioni globali/politiche
# ---------------------------------------------------------------------------

SEZIONE_R: list[ItemSR] = [
    ItemSR("S1", "S",
           "Mi preoccupo spesso per la mia salute o per quella delle persone a me care.",
           campo_profilo="fears_and_anxieties", sottocampo="salute"),
    ItemSR("S2", "S",
           "Mi preoccupo spesso per la mia situazione economica e finanziaria.",
           campo_profilo="fears_and_anxieties", sottocampo="economia"),
    ItemSR("S3", "S",
           "Mi preoccupo spesso per il mio percorso professionale o lavorativo.",
           campo_profilo="fears_and_anxieties", sottocampo="lavoro_carriera"),
]


# ---------------------------------------------------------------------------
# Struttura complessiva
# ---------------------------------------------------------------------------

SEZIONI_SR: list[tuple[str, str, list[ItemSR]]] = [
    ("E", "Sezione 1 — Informazioni generali", SEZIONE_E_SR),
    ("P", "Sezione 2 — Come mi descriverei", SEZIONE_P),
    ("Q", "Sezione 3 — Cosa conta per me", SEZIONE_Q),
    ("R", "Sezione 4 — Cosa mi preoccupa", SEZIONE_R),
]

TUTTI_ITEM_SR: list[ItemSR] = [
    item for _, _, items in SEZIONI_SR for item in items
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _correggi(item: ItemSR, valore: int) -> float:
    """Inverte il valore su scala 7 se l'item è reverse-scored."""
    return float(8 - valore) if item.invertito else float(valore)


def score_big_five(risposte: dict[str, int]) -> dict[str, float]:
    """
    Restituisce i 5 tratti come media dei due item per tratto (scala 1–7).
    Accoppiamenti BFI-10: (P1,P6), (P2,P7), (P3,P8), (P4,P9), (P5,P10).
    """
    coppie: dict[str, tuple[str, str]] = {
        "extraversion":      ("P1",  "P6"),
        "agreeableness":     ("P2",  "P7"),
        "conscientiousness": ("P3",  "P8"),
        "neuroticism":       ("P4",  "P9"),
        "openness":          ("P5",  "P10"),
    }
    mappa = {i.id: i for i in SEZIONE_P}
    risultati = {}
    for tratto, (id1, id2) in coppie.items():
        valori = [
            _correggi(mappa[id_], risposte[id_])
            for id_ in (id1, id2) if id_ in risposte
        ]
        if valori:
            risultati[tratto] = round(float(np.mean(valori)), 3)
    return risultati


def score_valori(risposte: dict[str, int]) -> dict[str, float]:
    """Restituisce {nome_valore: score_1-7} per i 10 tipi motivazionali."""
    mappa = {i.id: i for i in SEZIONE_Q}
    return {
        mappa[id_].sottocampo: float(v)
        for id_, v in risposte.items()
        if id_ in mappa and mappa[id_].sottocampo
    }


def score_preoccupazioni(risposte: dict[str, int]) -> dict[str, float]:
    """Restituisce {dominio: score_1-7} per i 3 domini WDQ."""
    mappa = {i.id: i for i in SEZIONE_R}
    return {
        mappa[id_].sottocampo: float(v)
        for id_, v in risposte.items()
        if id_ in mappa and mappa[id_].sottocampo
    }


# ---------------------------------------------------------------------------
# Compilazione profilo JSON
# ---------------------------------------------------------------------------

def compila_campi_profilo(
    risposte_likert: dict[str, int],
    risposte_demografiche: dict[str, object],
    schema_vuoto: dict,
) -> dict:
    """
    Produce una copia parzialmente compilata di schema_vuoto a partire
    dalle risposte del self-report.

    Confidence fissa a 0.85 per i campi self-report dichiarati
    (giustificata dalla fonte diretta vs. inferenza da chat).

    Parametri
    ----------
    risposte_likert      : {id_item: valore_int} per sezioni P, Q, R
    risposte_demografiche: {id_item: valore} per sezione E
    schema_vuoto         : dict caricato da schema_vuoto_user_profile.json
    """
    profilo = copy.deepcopy(schema_vuoto)
    CONF = 0.85
    INF  = "self_report"

    def _set(sezione: str, campo: str, valore, sottocampo: str | None = None) -> None:
        """Scrive valore + metadati nel campo corretto del profilo."""
        target = profilo[sezione]
        if sottocampo:
            target = target[campo]
            campo  = sottocampo
        if campo in target and isinstance(target[campo], dict):
            target[campo]["value"]          = valore
            target[campo]["confidence"]     = CONF
            target[campo]["inference_type"] = INF
            target[campo]["evidence"]       = [{"quote": str(valore), "doc_id": "self_report"}]

    # -- Demografici --
    mapping_demo = {
        "E1": ("private_attributes",      "age",                    None),
        "E2": ("private_attributes",      "gender",                 None),
        "E3": ("non_sensitive_attributes","education",              None),
        "E4": ("non_sensitive_attributes","occupation",             None),
        "E5": ("non_sensitive_attributes","city_or_region",         None),
        "E6": ("private_attributes",      "travel_mobility_signals",None),
        "E7": ("non_sensitive_attributes","hobbies",                None),
    }
    for id_item, (sezione, campo, sotto) in mapping_demo.items():
        if id_item in risposte_demografiche:
            _set(sezione, campo, risposte_demografiche[id_item], sotto)

    # -- Big Five --
    bf = score_big_five(risposte_likert)
    for tratto, valore in bf.items():
        bf_campo = profilo["psychological_attributes"]["big_five_personality"].get(tratto, {})
        bf_campo["value"]          = valore
        bf_campo["confidence"]     = CONF
        bf_campo["inference_type"] = INF
        bf_campo["evidence"]       = [{"quote": str(valore), "doc_id": "self_report"}]
        profilo["psychological_attributes"]["big_five_personality"][tratto] = bf_campo

    # Leva persuasiva dominante dal Big Five:
    # alto Agreeableness → social proof / appello emotivo
    # alto Openness      → argomenti nuovi / narrativa
    # basso Neuroticism  → argomentazione logica
    # alto Neuroticism   → fear appeal / urgenza
    if bf:
        n  = bf.get("neuroticism", 4.0)
        a  = bf.get("agreeableness", 4.0)
        o  = bf.get("openness", 4.0)
        if n >= 5.5:
            leva = "fear_appeal"
        elif a >= 5.5:
            leva = "social_proof"
        elif o >= 5.5:
            leva = "narrative_framing"
        else:
            leva = "argomentazione_logica"
        mvp_leva = profilo["manipulation_vulnerability_profile"]["dominant_persuasion_lever"]
        mvp_leva["value"]      = leva
        mvp_leva["confidence"] = round(CONF * 0.75, 2)  # inferita, non dichiarata

    # -- Valori --
    valori = score_valori(risposte_likert)
    if valori:
        top3 = sorted(valori, key=lambda k: valori[k], reverse=True)[:3]
        pv = profilo["psychological_attributes"]["personal_values"]
        pv["dominant_values"]  = top3
        pv["confidence"]       = CONF
        pv["inference_type"]   = INF
        pv["evidence"]         = [{"quote": str(valori), "doc_id": "self_report"}]
        # MVP: desiderio primario dal valore più alto
        profilo["manipulation_vulnerability_profile"]["primary_desire"]["value"]      = top3[0]
        profilo["manipulation_vulnerability_profile"]["primary_desire"]["confidence"] = CONF

    # -- Preoccupazioni --
    preoc = score_preoccupazioni(risposte_likert)
    if preoc:
        primaria = max(preoc, key=lambda k: preoc[k])
        fa = profilo["psychological_attributes"]["fears_and_anxieties"]
        fa["value"]          = sorted(preoc, key=lambda k: preoc[k], reverse=True)
        fa["confidence"]     = CONF
        fa["inference_type"] = INF
        fa["evidence"]       = [{"quote": str(preoc), "doc_id": "self_report"}]
        profilo["manipulation_vulnerability_profile"]["primary_fear"]["value"]      = primaria
        profilo["manipulation_vulnerability_profile"]["primary_fear"]["confidence"] = CONF

    return profilo


# ---------------------------------------------------------------------------
# Serializzazione per DB
# ---------------------------------------------------------------------------

def serializza_per_db_sr(
    partecipante_id: str,
    risposte_likert: dict[str, int],
    risposte_demografiche: dict[str, object],
    fase: str = "self_report",
) -> list[dict]:
    """
    Formato compatibile con salva_risposte_questionario() nel DB.
    Unisce risposte Likert e demografiche in un'unica lista di record.
    """
    mappa_item = {i.id: i for i in TUTTI_ITEM_SR}
    record = []

    for id_item, valore in risposte_likert.items():
        item = mappa_item.get(id_item)
        record.append({
            "partecipante_id": partecipante_id,
            "fase":            fase,
            "sezione":         item.sezione if item else None,
            "id_item":         id_item,
            "dominio":         item.campo_profilo if item else None,
            "valore_numerico": int(valore),
            "valore_testo":    SCALA_LIKERT_7.get(int(valore)),
        })

    for id_item, valore in risposte_demografiche.items():
        item = mappa_item.get(id_item)
        record.append({
            "partecipante_id": partecipante_id,
            "fase":            fase,
            "sezione":         item.sezione if item else None,
            "id_item":         id_item,
            "dominio":         item.campo_profilo if item else None,
            "valore_numerico": None,
            "valore_testo":    str(valore) if not isinstance(valore, list)
                               else ", ".join(valore),
        })

    return record