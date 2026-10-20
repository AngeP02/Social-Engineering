"""
Utils/database.py

Tutte le operazioni sul database Supabase.
Ogni funzione fa UNA cosa sola e ha un nome che lo dice chiaramente.
Nessuna logica sperimentale qui — solo lettura e scrittura dati.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import streamlit as st
from supabase import Client, create_client


# ─────────────────────────────────────────────────────────────────────────────
# Connessione (singleton via cache Streamlit)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def ottieni_client() -> Client:
    """
    Crea e restituisce il client Supabase.
    Cached da Streamlit: viene creato una volta sola per sessione applicazione.
    Le credenziali vengono lette da st.secrets oppure da variabili d'ambiente.
    """
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except (KeyError, AttributeError):
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL e SUPABASE_KEY non trovati. "
            "Aggiungili in .streamlit/secrets.toml oppure come variabili d'ambiente."
        )
    return create_client(url, key)


# ─────────────────────────────────────────────────────────────────────────────
# Partecipanti
# ─────────────────────────────────────────────────────────────────────────────

def leggi_tutti_partecipanti() -> list[dict]:
    """Restituisce tutti i partecipanti ordinati per id."""
    client = ottieni_client()
    risultato = (
        client.table("partecipanti")
        .select("*")
        .order("id")
        .execute()
    )
    return risultato.data or []


def leggi_partecipante(partecipante_id: str) -> Optional[dict]:
    """Restituisce il record di un singolo partecipante, o None."""
    client = ottieni_client()
    risultato = (
        client.table("partecipanti")
        .select("*")
        .eq("id", partecipante_id)
        .single()
        .execute()
    )
    return risultato.data


def aggiorna_fase(partecipante_id: str, nuova_fase: str) -> None:
    """Aggiorna la fase corrente del partecipante."""
    client = ottieni_client()
    client.table("partecipanti").update(
        {"fase_corrente": nuova_fase}
    ).eq("id", partecipante_id).execute()


def segna_consenso_firmato(partecipante_id: str) -> None:
    client = ottieni_client()
    client.table("partecipanti").update(
        {
            "consenso_firmato":         True,
            "timestamp_primo_accesso":  datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", partecipante_id).execute()


def segna_t0_completato(partecipante_id: str) -> None:
    client = ottieni_client()
    client.table("partecipanti").update(
        {"timestamp_t0_completato": datetime.now(timezone.utc).isoformat()}
    ).eq("id", partecipante_id).execute()


def segna_t1_completato(partecipante_id: str) -> None:
    """Segna T1 come completato e calcola il timestamp di sblocco T2 (+ 72h)."""
    from datetime import timedelta
    adesso = datetime.now(timezone.utc)
    sblocco_t2 = adesso + timedelta(hours=72)
    client = ottieni_client()
    client.table("partecipanti").update(
        {
            "timestamp_t1_completato": adesso.isoformat(),
            "timestamp_t2_sbloccato":  sblocco_t2.isoformat(),
            "fase_corrente":           "attesa_t2",
        }
    ).eq("id", partecipante_id).execute()


def segna_t2_completato(partecipante_id: str) -> None:
    client = ottieni_client()
    client.table("partecipanti").update(
        {
            "timestamp_t2_completato": datetime.now(timezone.utc).isoformat(),
            "fase_corrente":           "completato",
        }
    ).eq("id", partecipante_id).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Profili JSON
# ─────────────────────────────────────────────────────────────────────────────

def leggi_profilo(partecipante_id: str) -> Optional[dict]:
    """Restituisce il profilo JSON del partecipante, o None."""
    client = ottieni_client()
    risultato = (
        client.table("profili")
        .select("profilo_json")
        .eq("partecipante_id", partecipante_id)
        .single()
        .execute()
    )
    if risultato.data:
        return risultato.data["profilo_json"]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Questionari — salvataggio risposte
# ─────────────────────────────────────────────────────────────────────────────

def salva_risposte_questionario(
    partecipante_id: str,
    fase: str,
    risposte: list[dict],
) -> None:
    """
    Salva tutte le risposte di un questionario in blocco.

    `risposte` è una lista di dict con campi:
        sezione, id_item, dominio (opzionale),
        valore_numerico (opzionale), valore_testo (opzionale)
    """
    client = ottieni_client()
    adesso = datetime.now(timezone.utc).isoformat()

    record = [
        {
            "partecipante_id": partecipante_id,
            "fase":            fase,
            "sezione":         r["sezione"],
            "id_item":         r["id_item"],
            "dominio":         r.get("dominio"),
            "valore_numerico": r.get("valore_numerico"),
            "valore_testo":    r.get("valore_testo"),
            "timestamp":       adesso,
        }
        for r in risposte
    ]

    client.table("risposte_questionari").upsert(
        record,
        on_conflict="partecipante_id,fase,id_item",
    ).execute()


def leggi_risposte_questionario(
    partecipante_id: str,
    fase: str,
) -> list[dict]:
    """Legge tutte le risposte di un partecipante per una fase."""
    client = ottieni_client()
    risultato = (
        client.table("risposte_questionari")
        .select("*")
        .eq("partecipante_id", partecipante_id)
        .eq("fase", fase)
        .execute()
    )
    return risultato.data or []


def leggi_risposte_tutti_partecipanti(fase: str) -> list[dict]:
    """Legge le risposte di tutti i partecipanti per una fase (per dashboard)."""
    client = ottieni_client()
    risultato = (
        client.table("risposte_questionari")
        .select("*")
        .eq("fase", fase)
        .execute()
    )
    return risultato.data or []


# ─────────────────────────────────────────────────────────────────────────────
# Sessioni chat
# ─────────────────────────────────────────────────────────────────────────────

def crea_sessione_chat(
    partecipante_id: str,
    tipo: str,
    ordine: Optional[int] = None,
    modalita: Optional[str] = None,
    dominio: Optional[str] = None,
    llm: Optional[str] = None,
) -> int:
    """Crea una nuova sessione chat e restituisce il suo ID."""
    client = ottieni_client()
    risultato = (
        client.table("sessioni_chat")
        .insert(
            {
                "partecipante_id":   partecipante_id,
                "tipo":              tipo,
                "ordine":            ordine,
                "modalita":          modalita,
                "dominio":           dominio,
                "llm":               llm,
                "timestamp_inizio":  datetime.now(timezone.utc).isoformat(),
            }
        )
        .execute()
    )
    return risultato.data[0]["id"]


def chiudi_sessione_chat(
    sessione_id: int,
    n_turni_utente: int,
    durata_minuti: float,
    rifiuto_modello: str = "nessuno",
    metriche: Optional[dict] = None,
) -> None:
    """Segna una sessione come completata con le metriche finali."""
    client = ottieni_client()
    client.table("sessioni_chat").update(
        {
            "completata":       True,
            "n_turni_utente":   n_turni_utente,
            "durata_minuti":    durata_minuti,
            "rifiuto_modello":  rifiuto_modello,
            "metriche_json":    metriche or {},
            "timestamp_fine":   datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", sessione_id).execute()


def leggi_sessioni_partecipante(partecipante_id: str) -> list[dict]:
    client = ottieni_client()
    risultato = (
        client.table("sessioni_chat")
        .select("*")
        .eq("partecipante_id", partecipante_id)
        .order("timestamp_inizio")
        .execute()
    )
    return risultato.data or []


def leggi_tutte_sessioni() -> list[dict]:
    """Per la dashboard sviluppatore."""
    client = ottieni_client()
    risultato = (
        client.table("sessioni_chat")
        .select("*")
        .order("timestamp_inizio", desc=True)
        .execute()
    )
    return risultato.data or []


# ─────────────────────────────────────────────────────────────────────────────
# Messaggi chat
# ─────────────────────────────────────────────────────────────────────────────

def salva_messaggio(
    sessione_id: int,
    partecipante_id: str,
    ruolo: str,
    contenuto: str,
) -> None:
    """Salva un singolo messaggio nella chat."""
    client = ottieni_client()
    client.table("messaggi_chat").insert(
        {
            "sessione_id":      sessione_id,
            "partecipante_id":  partecipante_id,
            "ruolo":            ruolo,
            "contenuto":        contenuto,
        }
    ).execute()


def leggi_messaggi_sessione(sessione_id: int) -> list[dict]:
    client = ottieni_client()
    risultato = (
        client.table("messaggi_chat")
        .select("*")
        .eq("sessione_id", sessione_id)
        .order("timestamp")
        .execute()
    )
    return risultato.data or []


# ─────────────────────────────────────────────────────────────────────────────
# Aggiornamenti profilazione
# ─────────────────────────────────────────────────────────────────────────────

def salva_aggiornamento_profilazione(
    partecipante_id: str,
    sessione_id: int,
    turno_numero: int,
    categoria: str,
    valore_estratto: str,
    confidenza: str,
    json_snapshot: dict,
) -> None:
    client = ottieni_client()
    client.table("aggiornamenti_profilazione").insert(
        {
            "partecipante_id":  partecipante_id,
            "sessione_id":      sessione_id,
            "turno_numero":     turno_numero,
            "categoria":        categoria,
            "valore_estratto":  valore_estratto,
            "confidenza":       confidenza,
            "json_snapshot":    json_snapshot,
        }
    ).execute()


def leggi_evoluzione_profilazione(partecipante_id: str) -> list[dict]:
    client = ottieni_client()
    risultato = (
        client.table("aggiornamenti_profilazione")
        .select("*")
        .eq("partecipante_id", partecipante_id)
        .order("turno_numero")
        .execute()
    )
    return risultato.data or []


# ─────────────────────────────────────────────────────────────────────────────
# Persuasion Lift
# ─────────────────────────────────────────────────────────────────────────────

def salva_persuasion_lift(
    partecipante_id: str,
    dominio: str,
    score_t0: float,
    score_t1: Optional[float],
    score_t2: Optional[float],
    pl_t1: Optional[float],
    pl_t2: Optional[float],
    decadimento: Optional[float],
    sd_campione_t0: float,
) -> None:
    client = ottieni_client()
    client.table("persuasion_lift").upsert(
        {
            "partecipante_id": partecipante_id,
            "dominio":         dominio,
            "score_t0":        score_t0,
            "score_t1":        score_t1,
            "score_t2":        score_t2,
            "pl_t1":           pl_t1,
            "pl_t2":           pl_t2,
            "decadimento":     decadimento,
            "sd_campione_t0":  sd_campione_t0,
            "calcolato_at":    datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="partecipante_id,dominio",
    ).execute()


def leggi_tutti_persuasion_lift() -> list[dict]:
    client = ottieni_client()
    risultato = (
        client.table("persuasion_lift")
        .select("*")
        .execute()
    )
    return risultato.data or []