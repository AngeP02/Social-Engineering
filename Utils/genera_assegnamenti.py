"""
genera_assegnamenti.py

Genera/aggiorna config_assegnamenti.json in modo incrementale.

- L'ordine delle modalità è SEMPRE: controllo, velato, diretto.
- Ogni partecipante fa tutti e 3 i domini.
- Ogni partecipante usa 3 LLM distinti.
- Aggiungere un partecipante NON modifica le assegnazioni già salvate.
- La struttura per ciascun partecipante utilizza le chiavi "chat_1", "chat_2", "chat_3".

Uso:
    python genera_assegnamenti.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

# ── Configurazione ───────────────────────────────────────────────────────────

MODALITA = ["controllo", "velato", "diretto"]  # ordine fisso
DOMINI = ["commerciale", "sanitario", "politico"]

LLMS = [
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash",
    "anthropic/claude-haiku-4.5",
    "deepseek/deepseek-chat-v3-0324",
    "qwen/qwen-plus",
    "meta-llama/llama-3.3-70b-instruct",
]

INPUT_XLSX = Path(__file__).resolve().parent.parent / "Dati" /  "Partecipanti.xlsx"
OUTPUT_JSON = Path("config_assegnamenti.json")

def leggi_partecipanti(percorso: Path) -> list[str]:
    """
    Legge Dati/Partecipanti.xlsx e restituisce gli ID nel formato COGNOME_NOME.

    Riconosce le colonne 'cognome' e 'nome' indipendentemente da maiuscole,
    minuscole e spazi nell'intestazione.
    """
    df = pd.read_excel(percorso)

    colonne_normalizzate = {
        str(colonna).strip().lower(): colonna
        for colonna in df.columns
    }

    if "cognome" not in colonne_normalizzate or "nome" not in colonne_normalizzate:
        raise ValueError(
            f"Non ho trovato le colonne 'cognome' e/o 'nome' in {percorso}.\n"
            f"Colonne trovate: {list(df.columns)}\n"
            f"Rinominale esattamente in 'cognome' e 'nome', "
            f"oppure adatta questa funzione."
        )

    col_cognome = colonne_normalizzate["cognome"]
    col_nome = colonne_normalizzate["nome"]

    ids = (
        df[col_cognome].astype(str).str.strip()
        + "_"
        + df[col_nome].astype(str).str.strip()
    ).str.upper().tolist()

    if not ids:
        raise ValueError(f"Nessun partecipante trovato in {percorso}.")

    if len(ids) != len(set(ids)):
        raise ValueError("Ci sono partecipanti duplicati (stesso COGNOME_NOME).")

    return ids


def assegna_nuovo_partecipante(indice: int) -> dict[str, dict]:
    """
    Assegna le 3 sessioni al partecipante con indice progressivo `indice`.
    Restituisce un dizionario contenente la chiave 'chat' con le relative sessioni.
    """
    sessioni = {}

    for s, modalita in enumerate(MODALITA, start=1):
        dominio = DOMINI[(indice + (s - 1)) % len(DOMINI)]
        llm = LLMS[(indice + 2 * (s - 1)) % len(LLMS)]

        sessioni[f"chat_{s}"] = {
            "modalita": modalita,
            "dominio": dominio,
            "llm": llm,
        }

    # Struttura richiesta da Manipolazione.py con il dizionario "chat"
    return {"chat": sessioni}


def verifica(assegnamenti: dict) -> None:
    modalita = Counter()
    domini = Counter()
    llms = Counter()
    llm_dominio = Counter()
    llm_modalita = Counter()

    for dati_pid in assegnamenti.values():
        # Supporta sia la struttura con "chat" che eventuali vecchie strutture piatte
        sessioni = dati_pid.get("chat", dati_pid) if isinstance(dati_pid, dict) else {}

        for sessione in sessioni.values():
            if not isinstance(sessione, dict):
                continue
            m = sessione.get("modalita")
            d = sessione.get("dominio")
            l = sessione.get("llm")

            if m and d and l:
                modalita[m] += 1
                domini[d] += 1
                llms[l] += 1
                llm_dominio[(d, l)] += 1
                llm_modalita[(m, l)] += 1

    print("\n=== Verifica ===")
    print("Modalità:", dict(modalita))
    print("Domini:", dict(domini))
    print("LLM:", dict(llms))

    if llm_dominio and llm_dominio.values():
        print(
            "LLM per dominio — min/max:",
            min(llm_dominio.values()),
            max(llm_dominio.values()),
        )

    if llm_modalita and llm_modalita.values():
        print(
            "LLM per modalità — min/max:",
            min(llm_modalita.values()),
            max(llm_modalita.values()),
        )


def genera_o_aggiorna(
    partecipanti: list[str],
    output_json: Path = OUTPUT_JSON,
) -> dict:
    """
    Carica le assegnazioni esistenti, preserva i partecipanti già presenti
    e assegna solo quelli nuovi. Converte automaticamente vecchi formati
    (liste o chiavi numeriche semplici) nel formato 'chat_N'.
    """
    if output_json.exists():
        try:
            with open(output_json, encoding="utf-8") as f:
                contenuto = json.load(f)

            if isinstance(contenuto, dict) and "partecipanti" in contenuto:
                assegnamenti = contenuto["partecipanti"]
            elif isinstance(contenuto, dict):
                assegnamenti = contenuto
            else:
                raise ValueError("Formato JSON non riconosciuto.")

            # Retrocompatibilità: converte liste o chiavi numeriche in "chat_N"
            for pid, dati_pid in assegnamenti.items():
                if isinstance(dati_pid, list):
                    assegnamenti[pid] = {
                        f"chat_{i + 1}": sessione
                        for i, sessione in enumerate(dati_pid)
                    }
                elif isinstance(dati_pid, dict):
                    nuovo_diz = {}
                    for k, v in dati_pid.items():
                        chiave = k if k.startswith("chat_") else f"chat_{k}"
                        nuovo_diz[chiave] = v
                    assegnamenti[pid] = nuovo_diz

            print(f"✓ Caricate assegnazioni esistenti: {output_json}")

        except (json.JSONDecodeError, ValueError) as e:
            backup = output_json.with_suffix(".json.corrotto.bak")
            output_json.replace(backup)

            print(f"⚠ Il file {output_json} è vuoto o corrotto: {e}")
            print(f"⚠ Ho creato un backup: {backup}")
            print("ℹ Ricreo le assegnazioni da zero.")

            assegnamenti = {}
    else:
        assegnamenti = {}
        print("ℹ Nessun file esistente: creo nuove assegnazioni.")

    indice = len(assegnamenti)
    nuovi = []

    for partecipante_id in partecipanti:
        if partecipante_id in assegnamenti:
            continue

        assegnamenti[partecipante_id] = assegna_nuovo_partecipante(indice)
        nuovi.append(partecipante_id)
        indice += 1

    output_json.write_text(
        json.dumps(
            {"partecipanti": assegnamenti},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"✓ Nuovi partecipanti assegnati: {len(nuovi)}")
    for pid in nuovi:
        print(f"  - {pid}")

    print(f"✓ Salvato in: {output_json.resolve()}")
    return assegnamenti


if __name__ == "__main__":
    partecipanti = leggi_partecipanti(INPUT_XLSX)
    assegnamenti = genera_o_aggiorna(partecipanti)
    verifica(assegnamenti)