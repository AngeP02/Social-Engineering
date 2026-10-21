from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Optional
import streamlit as st
from supabase import Client, create_client

@st.cache_resource
def ottieni_client() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL e SUPABASE_KEY non trovati. "
            "Aggiungili in .streamlit/secrets.toml oppure come variabili d'ambiente."
        )
    return create_client(url, key)

def leggi_tutti_partecipanti() -> list[dict]:
    client = ottieni_client()
    risultato = (
        client.table("partecipanti")
        .select("*")
        .order("id")
        .execute()
    )
    return risultato.data or []


def leggi_partecipante(partecipante_id: str) -> Optional[dict]:
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
    client = ottieni_client()
    client.table("partecipanti").update(
        {"fase_corrente": nuova_fase}
    ).eq("id", partecipante_id).execute()


def segna_consenso_firmato(partecipante_id: str) -> None:
    client = ottieni_client()
    client.table("partecipanti").update(
        {
            "consenso_firmato": True,
            "timestamp_primo_accesso":  datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", partecipante_id).execute()


def segna_t0_completato(partecipante_id: str) -> None:
    client = ottieni_client()
    client.table("partecipanti").update(
        {"timestamp_t0_completato": datetime.now(timezone.utc).isoformat()}
    ).eq("id", partecipante_id).execute()

def segna_t1_completato(partecipante_id: str) -> None:
    from datetime import timedelta
    adesso = datetime.now(timezone.utc)
    sblocco_t2 = adesso + timedelta(hours=72)
    client = ottieni_client()
    client.table("partecipanti").update(
        {
            "timestamp_t1_completato": adesso.isoformat(),
            "timestamp_t2_sbloccato":  sblocco_t2.isoformat(),
            "fase_corrente": "attesa_t2",
        }
    ).eq("id", partecipante_id).execute()

def segna_t2_completato(partecipante_id: str) -> None:
    client = ottieni_client()
    client.table("partecipanti").update(
        {
            "timestamp_t2_completato": datetime.now(timezone.utc).isoformat(),
            "fase_corrente": "completato",
        }
    ).eq("id", partecipante_id).execute()

def leggi_profilo(partecipante_id: str) -> Optional[dict]:
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

def salva_risposte_questionario(partecipante_id: str, fase: str, risposte: list[dict]) -> None:
    client = ottieni_client()
    adesso = datetime.now(timezone.utc).isoformat()

    record = [
        {
            "partecipante_id": partecipante_id,
            "fase": fase,
            "sezione": r["sezione"],
            "id_item": r["id_item"],
            "dominio": r.get("dominio"),
            "valore_numerico": r.get("valore_numerico"),
            "valore_testo": r.get("valore_testo"),
            "timestamp": adesso,
        }
        for r in risposte
    ]

    client.table("risposte_questionari").upsert(
        record,
        on_conflict="partecipante_id,fase,id_item",
    ).execute()


def leggi_risposte_questionario(partecipante_id: str, fase: str) -> list[dict]:
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
    client = ottieni_client()
    risultato = (
        client.table("risposte_questionari")
        .select("*")
        .eq("fase", fase)
        .execute()
    )
    return risultato.data or []

def crea_sessione_chat(partecipante_id: str, tipo: str, ordine: Optional[int] = None, modalita: Optional[str] = None, dominio: Optional[str] = None, llm: Optional[str] = None) -> int:
    client = ottieni_client()
    risultato = (
        client.table("sessioni_chat")
        .insert(
            {
                "partecipante_id": partecipante_id,
                "tipo": tipo,
                "ordine": ordine,
                "modalita": modalita,
                "dominio": dominio,
                "llm": llm,
                "timestamp_inizio": datetime.now(timezone.utc).isoformat(),
            }
        )
        .execute()
    )
    return risultato.data[0]["id"]

def chiudi_sessione_chat(sessione_id: int, n_turni_utente: int, durata_minuti: float, rifiuto_modello: str = "nessuno", metriche: Optional[dict] = None) -> None:
    client = ottieni_client()
    client.table("sessioni_chat").update(
        {
            "completata": True,
            "n_turni_utente": n_turni_utente,
            "durata_minuti": durata_minuti,
            "rifiuto_modello": rifiuto_modello,
            "metriche_json": metriche or {},
            "timestamp_fine": datetime.now(timezone.utc).isoformat(),
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
    client = ottieni_client()
    risultato = (
        client.table("sessioni_chat")
        .select("*")
        .order("timestamp_inizio", desc=True)
        .execute()
    )
    return risultato.data or []

def salva_messaggio(sessione_id: int, partecipante_id: str, ruolo: str, contenuto: str) -> None:
    client = ottieni_client()
    client.table("messaggi_chat").insert(
        {
            "sessione_id": sessione_id,
            "partecipante_id": partecipante_id,
            "ruolo": ruolo,
            "contenuto": contenuto,
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

def salva_aggiornamento_profilazione(partecipante_id: str, sessione_id: int, turno_numero: int, categoria: str, valore_estratto: str, confidenza: str, json_snapshot: dict) -> None:
    client = ottieni_client()
    client.table("aggiornamenti_profilazione").insert(
        {
            "partecipante_id": partecipante_id,
            "sessione_id": sessione_id,
            "turno_numero": turno_numero,
            "categoria": categoria,
            "valore_estratto": valore_estratto,
            "confidenza": confidenza,
            "json_snapshot": json_snapshot,
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

def salva_persuasion_lift(partecipante_id: str, dominio: str, score_t0: float, score_t1: Optional[float], score_t2: Optional[float], pl_t1: Optional[float], pl_t2: Optional[float], decadimento: Optional[float], sd_campione_t0: float) -> None:
    client = ottieni_client()
    client.table("persuasion_lift").upsert(
        {
            "partecipante_id": partecipante_id,
            "dominio": dominio,
            "score_t0": score_t0,
            "score_t1": score_t1,
            "score_t2": score_t2,
            "pl_t1": pl_t1,
            "pl_t2": pl_t2,
            "decadimento": decadimento,
            "sd_campione_t0": sd_campione_t0,
            "calcolato_at": datetime.now(timezone.utc).isoformat(),
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

import io
import json

def storage_leggi_json(percorso: str) -> dict:
    """Legge un file JSON dallo Storage Supabase. percorso es: 'Dati/schema_vuoto.json'"""
    client = ottieni_client()
    risposta = client.storage.from_("files").download(percorso)
    return json.loads(risposta)

def storage_salva_json(percorso: str, dati: dict) -> None:
    """Salva/sovrascrive un file JSON sullo Storage Supabase."""
    client = ottieni_client()
    contenuto = json.dumps(dati, ensure_ascii=False, indent=2).encode("utf-8")
    # upsert=True sovrascrive se esiste già
    client.storage.from_("files").upload(
        percorso,
        contenuto,
        {"content-type": "application/json", "upsert": "true"},
    )

def storage_file_esiste(percorso: str) -> bool:
    """Controlla se un file esiste nello Storage."""
    client = ottieni_client()
    try:
        client.storage.from_("files").download(percorso)
        return True
    except Exception as e:
        print(f"[storage] file non trovato: {percorso} → {e}")  # ← debug
        return False