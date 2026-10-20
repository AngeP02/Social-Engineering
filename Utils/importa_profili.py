import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BASE_DIR = Path(__file__).resolve().parent.parent

CARTELLA_PROFILI = BASE_DIR / "Dati" / "Profili_json_completi"

def connetti() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERRORE: SUPABASE_URL e SUPABASE_KEY devono essere in .env")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def deriva_id_partecipante(nome_file: str) -> str:
    stem = Path(nome_file).stem
    stem = stem.replace("PERSONA_", "")
    return stem.upper()


def deriva_nome_visualizzato(partecipante_id: str) -> str:
    try:
        numero = int(partecipante_id)
        return f"Partecipante {numero}"
    except ValueError:
        return f"Partecipante {partecipante_id}"


def importa(client: Client) -> None:
    if not CARTELLA_PROFILI.exists():
        print(f"ERRORE: cartella {CARTELLA_PROFILI} non trovata.")
        sys.exit(1)

    file_json = sorted(CARTELLA_PROFILI.glob("*.json"))
    if not file_json:
        print(f"Nessun file .json trovato in {CARTELLA_PROFILI}")
        return

    print(f"Trovati {len(file_json)} file. Importazione in corso...\n")

    for percorso in file_json:
        pid = deriva_id_partecipante(percorso.name)
        nome = deriva_nome_visualizzato(pid)
        try:
            with open(percorso, encoding="utf-8") as f:
                profilo = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  ✗ {percorso.name}: JSON non valido — {e}")
            continue
        risposta_p = (
            client.table("partecipanti")
            .upsert(
                {
                    "id": pid,
                    "nome_visualizzato": nome,
                    "fase_corrente": "non_iniziato",
                },
                on_conflict="id",
            )
            .execute()
        )

        # Inserisci profilo JSON
        risposta_prof = (
            client.table("profili")
            .upsert(
                {
                    "partecipante_id": pid,
                    "profilo_json": profilo,
                    "nome_file_origine": percorso.name,
                },
                on_conflict="partecipante_id",
            )
            .execute()
        )

        print(f"  ✓ {percorso.name} → partecipante '{pid}' ({nome})")

    print(f"\nImportazione completata: {len(file_json)} profili caricati.")
    print("Verifica su Supabase → Table Editor → tabelle 'partecipanti' e 'profili'")


if __name__ == "__main__":
    client = connetti()
    importa(client)