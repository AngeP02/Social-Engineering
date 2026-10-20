from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np



@dataclass
class Item:
    id: str
    sezione: str
    testo: str
    dominio: Optional[str] = None
    invertito: bool = False
    tipo: str = "likert"
    opzioni: Optional[list]  = None


SCALA_LIKERT = {
    1: "Completamente in disaccordo",
    2: "In forte disaccordo",
    3: "Piuttosto in disaccordo",
    4: "Né d'accordo né in disaccordo",
    5: "Piuttosto d'accordo",
    6: "In forte accordo",
    7: "Completamente d'accordo",
}

SEZIONE_A: list[Item] = [
    # Commerciale
    Item("A1", "A", "Mi fido delle raccomandazioni di prodotto fatte da sistemi di intelligenza artificiale.",
         dominio="commerciale"),
    Item("A2", "A", "Prima di acquistare un prodotto, verifico sempre recensioni e informazioni da fonti indipendenti.",
         dominio="commerciale"),
    Item("A3", "A", "Sono disposto/a a cambiare la mia marca abituale se un sistema AI mi convince che un'alternativa è migliore.",
         dominio="commerciale"),
    Item("A4", "A", "Nei prossimi 30 giorni è probabile che acquisti uno smartphone premium (fascia 800€+).",
         dominio="commerciale"),

    # Sanitario
    Item("B1", "A", "Gli screening preventivi (come mammografia, colonscopia, ecc.) sono utili per proteggere la mia salute.",
         dominio="sanitario"),
    Item("B2", "A", "Preferisco non sapere se potrei avere problemi di salute futuri, per non vivere in ansia.",
         dominio="sanitario", invertito=True),
    Item("B3", "A", "Mi sottoporrei a uno screening medico preventivo se consigliato, anche senza parere diretto del mio medico.",
         dominio="sanitario"),
    Item("B4", "A", "Entro i prossimi tre mesi intendo prenotare un esame di screening preventivo dei nei.",
         dominio="sanitario"),

    # Politico
    Item("C1", "A", "L'introduzione di una tassa patrimoniale sui grandi patrimoni sarebbe giusta per ridurre le disuguaglianze.",
         dominio="politico"),
    Item("C2", "A", "Le decisioni politiche importanti dovrebbero essere lasciate agli esperti e ai tecnici, non ai cittadini comuni.",
         dominio="politico"),
    Item("C3", "A", "Sono aperto/a a cambiare la mia opinione su questioni politiche se mi vengono presentati argomenti convincenti.",
         dominio="politico"),
    Item("C4", "A", "Se si tenesse un referendum domani, voterei a favore dell'introduzione di una tassa patrimoniale progressiva.",
         dominio="politico"),
]

SEZIONE_D: list[Item] = [
    Item("D1", "D", "Preferisco compiti semplici a compiti complessi che richiedono molto ragionamento.",
         invertito=True),
    Item("D2", "D", "Mi piace avere la responsabilità di gestire situazioni che richiedono molto pensiero."),
    Item("D3", "D", "L'idea di pensare in modo astratto a concetti complessi mi attrae."),
    Item("D4", "D", "Cerco di evitare situazioni che richiedono di pensare in profondità.",
         invertito=True),
    Item("D5", "D", "Trovo soddisfazione nel risolvere problemi che richiedono analisi attenta."),
    Item("D6", "D", "Preferisco avere informazioni chiare e immediate piuttosto che doverle elaborare io.",
         invertito=True),
    Item("D7", "D", "Mi impegno pienamente in compiti mentali anche quando sono difficili."),
    Item("D8", "D", "Penso che il ragionamento profondo sia uno spreco di tempo nella maggior parte dei casi.",
         invertito=True),
    Item("D9", "D", "Amo le sfide intellettuali che mi costringono a pensare in modo creativo."),
]

SEZIONE_E: list[Item] = [
    Item("E1", "E", "Età",
         tipo="numero"),
    Item("E2", "E", "Genere",
         tipo="scelta",
         opzioni=["Maschio", "Femmina", "Non binario", "Preferisco non rispondere"]),
    Item("E3", "E", "Titolo di studio più alto conseguito",
         tipo="scelta",
         opzioni=["Scuola media", "Diploma superiore", "Laurea triennale",
                  "Laurea magistrale", "Dottorato o altro"]),
    Item("E4", "E", "Con quale frequenza usi sistemi AI conversazionali (ChatGPT, Gemini, Claude, ecc.)?",
         tipo="scelta",
         opzioni=["Mai",
                  "Raramente (meno di 1 volta al mese)",
                  "Occasionalmente (1–3 volte al mese)",
                  "Spesso (1–2 volte a settimana)",
                  "Molto spesso (3+ volte a settimana)"]),
]

TUTTI_ITEM_T0: list[Item] = SEZIONE_A + SEZIONE_D + SEZIONE_E

def correggi_item(item: Item, valore: int) -> float:
    return float(8 - valore) if item.invertito else float(valore)


def score_dominio(
    risposte: dict[str, int],
    dominio: str,
    solo_opinione: bool = False,
) -> Optional[float]:

    item_intenz = {"commerciale": "A4", "sanitario": "B4", "politico": "C4"}
    id_da_escludere = {item_intenz[dominio]} if solo_opinione else set()

    item_dominio = [
        it for it in SEZIONE_A
        if it.dominio == dominio and it.id not in id_da_escludere
    ]
    valori = []
    for it in item_dominio:
        if it.id in risposte:
            valori.append(correggi_item(it, risposte[it.id]))

    return round(float(np.mean(valori)), 3) if valori else None


def score_nfc(risposte: dict[str, int]) -> Optional[float]:

    valori = []
    for it in SEZIONE_D:
        if it.id in risposte:
            valori.append(correggi_item(it, risposte[it.id]))
    return round(float(np.mean(valori)), 3) if valori else None


def serializza_per_db(
    partecipante_id: str,
    risposte_likert: dict[str, int],
    risposte_demografiche: dict[str, str],
    fase: str = "t0",
) -> list[dict]:

    record = []

    for it in SEZIONE_A + SEZIONE_D:
        if it.id in risposte_likert:
            record.append({
                "sezione":         it.sezione,
                "id_item":         it.id,
                "dominio":         it.dominio,
                "valore_numerico": risposte_likert[it.id],
                "valore_testo":    None,
            })

    for it in SEZIONE_E:
        if it.id in risposte_demografiche:
            record.append({
                "sezione": "E",
                "id_item": it.id,
                "dominio": None,
                "valore_numerico": None,
                "valore_testo": risposte_demografiche[it.id],
            })

    return record