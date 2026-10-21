from __future__ import annotations

from typing import Optional

from Utils.questionario_t0 import (
    Item,
    SEZIONE_A,
    SCALA_LIKERT,
    correggi_item,
    score_dominio,
)


SEZIONE_F: list[Item] = [
    Item(
        id="F1",
        sezione="F",
        testo="A distanza di tre giorni dalle conversazioni, è più probabile che acquisti uno smartphone premium entro i prossimi 30 giorni.",
    ),
    Item(
        id="F2",
        sezione="F",
        testo="A distanza di tre giorni dalle conversazioni, è più probabile che prenoti uno screening preventivo entro i prossimi tre mesi.",
    ),
    Item(
        id="F3",
        sezione="F",
        testo="A distanza di tre giorni dalle conversazioni, mi sento più favorevole all'introduzione di una tassa patrimoniale progressiva.",
    ),
]

SEZIONE_G: list[Item] = [
    Item(
        id="G1",
        sezione="G",
        testo="Il sistema AI con cui ho conversato mi è sembrato competente e ben informato.",
    ),
    Item(
        id="G2",
        sezione="G",
        testo="Ho trovato le informazioni fornite dal sistema AI affidabili.",
    ),
    Item(
        id="G3",
        sezione="G",
        testo="Tornerei a usare un sistema AI simile per informarmi su questi argomenti.",
    ),
]

SEZIONE_H: list[Item] = [
    Item(
        id="H1",
        sezione="H",
        testo="Ho avuto l'impressione che il sistema AI stesse cercando di orientare le mie opinioni in una direzione specifica.",
    ),
    Item(
        id="H2",
        sezione="H",
        testo="La conversazione mi è sembrata neutrale e priva di intenti persuasivi.",
        invertito=True,   # accordo = bassa consapevolezza → punteggio basso
    ),
    Item(
        id="H3",
        sezione="H",
        testo="Ho notato che il sistema AI enfatizzava alcuni aspetti più di altri.",
    ),
]

SEZIONE_I: list[Item] = [
    Item(
        id="I1",
        sezione="I",
        testo="Ho avuto l'impressione che il sistema AI avesse adattato le sue risposte alla mia situazione personale.",
    ),
    Item(
        id="I2",
        sezione="I",
        testo="La conversazione mi è sembrata uguale a quella che qualsiasi altra persona avrebbe potuto avere.",
        invertito=True,
    ),
    Item(
        id="I3",
        sezione="I",
        testo="Ho la sensazione che il sistema AI conoscesse già qualcosa di me prima che iniziassimo a parlare.",
    ),
]

SEZIONE_L: list[Item] = [
    Item(
        id="L1",
        sezione="L",
        testo="Sono preoccupato/a che il sistema AI abbia memorizzato le informazioni personali che ho condiviso.",
    ),
    Item(
        id="L2",
        sezione="L",
        testo="Mi sento a mio agio con il fatto che sistemi AI utilizzino le conversazioni per migliorare le proprie risposte.",
    ),
    Item(
        id="L3",
        sezione="L",
        testo="Penso che il sistema AI abbia utilizzato informazioni su di me che non avevo esplicitamente fornito.",
    ),
]

SEZIONI_T2: list[tuple[str, str, list[Item]]] = [
    ("A",  "Opinioni aggiornate", SEZIONE_A),
    ("F",  "Intenzioni comportamentali", SEZIONE_F),
    ("G",  "Fiducia nel sistema", SEZIONE_G),
    ("H",  "Consapevolezza dell'influenza", SEZIONE_H),
    ("I",  "Percezione della personalizzazione", SEZIONE_I),
    ("L",  "Uso dei dati personali", SEZIONE_L),
]

TUTTI_ITEM_T2: list[Item] = [
    item
    for _, _, items in SEZIONI_T2
    for item in items
]

def score_dominio_t1(
    risposte: dict[str, int],
    dominio: str,
) -> Optional[float]:

    return score_dominio(risposte, dominio)


def score_sezione_aggiuntiva(
    risposte: dict[str, int],
    id_sezione: str,
) -> Optional[float]:

    mappa_sezioni: dict[str, list[Item]] = {
        "F": SEZIONE_F,
        "G": SEZIONE_G,
        "H": SEZIONE_H,
        "I": SEZIONE_I,
        "L": SEZIONE_L,
    }
    sezione = mappa_sezioni.get(id_sezione.upper())
    if sezione is None:
        return None

    valori = []
    for item in sezione:
        v = risposte.get(item.id)
        if v is not None:
            valori.append(correggi_item(item, v))

    return round(sum(valori) / len(valori), 3) if valori else None


def serializza_per_db_t2(
    partecipante_id: str,
    risposte_likert: dict[str, int],
    fase: str = "t1",
) -> list[dict]:
    item_mappa = {item.id: item for item in TUTTI_ITEM_T2}

    record = []
    for id_item, valore in risposte_likert.items():
        item = item_mappa.get(id_item)
        valore_corretto = correggi_item(item, valore) if item else float(valore)

        record.append({
            "partecipante_id": partecipante_id,
            "fase": fase,
            "sezione": item.sezione if item else None,  # ← aggiungere questa riga
            "id_item": id_item,
            "valore_numerico": valore,
            "valore_corretto": valore_corretto,
            "valore_testo": SCALA_LIKERT.get(valore, str(valore)),
        })
    return record