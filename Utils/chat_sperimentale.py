from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from Utils.prompts_chat_sperimentali import (
    VERSIONE_PROMPT_SPERIMENTALE,
    TURNI_MINIMI_UTENTE,
    TURNI_MASSIMI_UTENTE,
    costruisci_prompt_sperimentale,
    sintetizza_t0_per_dominio,
)
from Utils.database import (
    crea_sessione_chat,
    chiudi_sessione_chat,
    salva_messaggio,
    leggi_risposte_questionario,
)

_RADICE_PROGETTO = Path(__file__).resolve().parents[1]
_DIR_OUTPUT = _RADICE_PROGETTO / "output"
_DIR_PROFILI_VECCHIA = _RADICE_PROGETTO / "Dati" / "profili_json_completi"

_RE_METRICHE = re.compile(
    r"<metriche_turno>(.*?)</metriche_turno>",
    re.DOTALL | re.IGNORECASE,
)

from Utils.database import storage_leggi_json


def estrai_testo_pulito_sperimentale(risposta: str) -> str:
    return _RE_METRICHE.sub("", risposta).strip()


def _parse_metriche(risposta_raw: str) -> Optional[dict]:
    match = _RE_METRICHE.search(risposta_raw)
    if not match:
        return None
    contenuto = match.group(1).strip()
    try:
        return json.loads(contenuto)
    except json.JSONDecodeError:
        # Tentativo di recupero: estrai il primo oggetto JSON
        obj = re.search(r"\{.*\}", contenuto, re.DOTALL)
        if obj:
            try:
                return json.loads(obj.group())
            except json.JSONDecodeError:
                pass
    return None

def carica_profilo_json(partecipante_id: str) -> dict:
    candidati = [
        f"output/{partecipante_id}/profilo_completo.json",
        f"Dati/profili_json_completi/PERSONA_{partecipante_id}.json",
        f"Dati/profili_json_completi/{partecipante_id}.json",
        "Dati/profili_json_completi/PERSONA_ESEMPIO.json",
    ]
    for percorso in candidati:
        try:
            return storage_leggi_json(percorso)
        except Exception:
            continue

    raise FileNotFoundError(
        f"Nessun profilo trovato su Storage per '{partecipante_id}'. "
        f"Percorsi cercati: {candidati}"
    )

CFG_MODELLO_SPERIMENTALE = {
    "controllo": {
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash",
        "api_key_env": "OPENROUTER_API_KEY",
        "temperature": 0.5,
        "max_tokens":  1200,
    },
    "velato": {
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash",
        "api_key_env": "OPENROUTER_API_KEY",
        "temperature": 0.7,
        "max_tokens":  1400,
    },
    "diretto": {
        "provider":    "openrouter",
        "model":       "google/gemini-2.5-flash",
        "api_key_env": "OPENROUTER_API_KEY",
        "temperature": 0.6,
        "max_tokens":  1400,
    },
}

class SessioneChat:

    def __init__(
        self,
        partecipante_id: str,
        modalita: str,
        dominio: str,
        nfc_score: float,
        frequenza_ai: str,
        numero_chat: int,
        modello_override: Optional[str] = None,
    ):
        self.partecipante_id = partecipante_id
        self.modalita = modalita.lower().strip()
        self.dominio = dominio.lower().strip()
        self.nfc_score = nfc_score
        self.frequenza_ai = frequenza_ai
        self.numero_chat = numero_chat

        # Stato conversazione
        self.messaggi_storia: list[dict] = []
        self.messaggi_visibili: list[dict] = []
        self.metriche_turni: list[dict] = []
        self.turni_utente: int = 0

        # Metriche aggregate
        self.primo_persuasivo: Optional[int] = None
        self.rifiuto_modello:  str = "nessuno"

        # Profilo e dati T0 (caricati in inizia())
        self.profilo_json: dict = {}
        self._riassunto_t0: str  = ""
        self._prompt_sistema: str  = ""

        # Sessione DB
        self.sessione_id: Optional[str] = None

        # Client LLM
        self._client = None

        # Override modello (per assegnamento sperimentale)
        self._modello_override = modello_override


    def inizia(self) -> str:

        from clients import get_client

        self.profilo_json = carica_profilo_json(self.partecipante_id)

        risposte_t0 = leggi_risposte_questionario(self.partecipante_id, "t0")
        self._riassunto_t0 = sintetizza_t0_per_dominio(risposte_t0, self.dominio)

        self._prompt_sistema = costruisci_prompt_sperimentale(
            partecipante_id=self.partecipante_id,
            modalita=self.modalita,
            dominio=self.dominio,
            nfc_score=self.nfc_score,
            profilo_json=self.profilo_json,
            risposte_t0_summary=self._riassunto_t0,
            frequenza_ai=self.frequenza_ai,
        )

        cfg = dict(CFG_MODELLO_SPERIMENTALE[self.modalita])
        if self._modello_override:
            cfg["model"] = self._modello_override
        self._client = get_client(cfg)

        label_llm = (
            self._modello_override
            if self._modello_override
            else cfg["model"]
        )
        self.sessione_id = crea_sessione_chat(
            partecipante_id=self.partecipante_id,
            tipo=f"sperimentale_{self.modalita}_{self.dominio}",
            llm=label_llm,
        )

        self.messaggi_storia = [
            {"role": "system", "content": self._prompt_sistema},
            {"role": "user",   "content": "Ciao!"},
        ]

        risposta_raw   = self._chiama_modello()
        testo_visibile = estrai_testo_pulito_sperimentale(risposta_raw)
        metriche       = _parse_metriche(risposta_raw)

        self.messaggi_storia.append({"role": "assistant", "content": risposta_raw})

        salva_messaggio(self.sessione_id, self.partecipante_id, "utente", "Ciao!")
        salva_messaggio(self.sessione_id, self.partecipante_id, "assistente", testo_visibile)
        self._aggiorna_metriche(metriche, turno=0)

        self.messaggi_visibili.append({"ruolo": "assistente", "contenuto": testo_visibile})
        return testo_visibile


    def invia_messaggio(self, testo_utente: str) -> str:

        if self.turni_utente >= TURNI_MASSIMI_UTENTE:
            return ""

        self.turni_utente += 1

        self.messaggi_storia.append({"role": "user", "content": testo_utente})

        risposta_raw = self._chiama_modello()
        testo_visibile = estrai_testo_pulito_sperimentale(risposta_raw)
        metriche = _parse_metriche(risposta_raw)

        self.messaggi_storia.append({"role": "assistant", "content": risposta_raw})
        self._aggiorna_metriche(metriche, turno=self.turni_utente)

        salva_messaggio(self.sessione_id, self.partecipante_id, "utente",     testo_utente)
        salva_messaggio(self.sessione_id, self.partecipante_id, "assistente", testo_visibile)

        self.messaggi_visibili.append({"ruolo": "utente",     "contenuto": testo_utente})
        self.messaggi_visibili.append({"ruolo": "assistente", "contenuto": testo_visibile})

        return testo_visibile


    @property
    def completabile(self) -> bool:

        return self.turni_utente >= TURNI_MINIMI_UTENTE

    @property
    def chiusura_automatica(self) -> bool:

        return self.turni_utente >= TURNI_MASSIMI_UTENTE


    def chiudi(self) -> None:
        if self.sessione_id is None:
            return

        metriche_aggregate = self._calcola_metriche_aggregate()

        chiudi_sessione_chat(
            sessione_id=self.sessione_id,
            n_turni_utente=self.turni_utente,
            durata_minuti=0.0,          # calcolato lato DB dai timestamp
            rifiuto_modello=self.rifiuto_modello,
            metriche=metriche_aggregate,
        )


    def _chiama_modello(self) -> str:

        if hasattr(self._client, "send_chat"):
            risposta = self._client.send_chat(self.messaggi_storia)
        else:
            prompt_fallback = "\n\n".join(
                f"[{m['role'].upper()}]\n{m['content']}"
                for m in self.messaggi_storia
            )
            risposta = self._client.send_prompt(prompt_fallback)
        return risposta.text

    def _aggiorna_metriche(self, metriche: Optional[dict], turno: int) -> None:

        if metriche is None:
            return

        metriche["turno_effettivo"] = turno
        self.metriche_turni.append(metriche)

        if (
            self.primo_persuasivo is None
            and metriche.get("primo_elemento_persuasivo") is True
        ):
            self.primo_persuasivo = turno

    def _calcola_metriche_aggregate(self) -> dict:

        if not self.metriche_turni:
            return {
                "versione_prompt": VERSIONE_PROMPT_SPERIMENTALE,
                "modalita": self.modalita,
                "dominio": self.dominio,
                "nfc_score": self.nfc_score,
                "n_turni_primo_persuasivo": None,
                "intensita_media": 0.0,
            }

        intensita_values = [
            float(m.get("intensita_persuasiva", 0.0))
            for m in self.metriche_turni
        ]
        toni = [m.get("tono_emotivo", "neutro") for m in self.metriche_turni]
        campi = [
            m["campo_profilo_usato"]
            for m in self.metriche_turni
            if m.get("campo_profilo_usato") and m["campo_profilo_usato"] != "null"
        ]
        obiezioni = sum(
            1 for m in self.metriche_turni if m.get("obiezione_rilevata") is True
        )

        return {
            "versione_prompt": VERSIONE_PROMPT_SPERIMENTALE,
            "modalita": self.modalita,
            "dominio": self.dominio,
            "nfc_score": self.nfc_score,
            "n_turni_primo_persuasivo": self.primo_persuasivo,
            "intensita_media": round(sum(intensita_values) / len(intensita_values), 3),
            "distribuzione_toni": {t: toni.count(t) for t in set(toni)},
            "campi_profilo_usati": list(set(campi)),
            "n_obiezioni_rilevate": obiezioni,
            "rifiuto_modello": self.rifiuto_modello,
        }