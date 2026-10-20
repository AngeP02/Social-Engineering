import os
import sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client
import streamlit as st

load_dotenv()

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except (Exception, ImportError):
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

BASE_DIR = Path(__file__).resolve().parent.parent
PERCORSO_EXCEL = BASE_DIR / "Dati" / "Partecipanti.xlsx"


def connetti() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERRORE: SUPABASE_URL e SUPABASE_KEY devono essere impostati nel file .env")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def pulisci_testo(valore) -> str:
    if pd.isna(valore):
        return ""
    return str(valore).strip()

def genera_id_partecipante(cognome: str, nome: str, indice: int) -> str:
    cognome_clean = cognome.upper().replace(" ", "_")
    nome_clean = nome.upper().replace(" ", "_")
    if cognome_clean and nome_clean:
        return f"{cognome_clean}_{nome_clean}"
    elif cognome_clean:
        return cognome_clean
    else:
        return f"PARTECIPANTE_{indice + 1}"

def importa_da_excel(client: Client, file_path: Path) -> None:
    if not file_path.exists():
        print(f"ERRORE: Impossibile trovare il file Excel in '{file_path}'")
        sys.exit(1)

    print(f"Lettura del file Excel: {file_path.name}...")
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        print(f"ERRORE durante la lettura del file Excel: {e}")
        sys.exit(1)
    colonne = [c.lower().strip() for c in df.columns]
    col_cognome = None
    col_nome = None

    for orig_col in df.columns:
        c_clean = orig_col.lower().strip()
        if c_clean == "cognome":
            col_cognome = orig_col
        elif c_clean == "nome":
            col_nome = orig_col

    if not col_cognome or not col_nome:
        print("ERRORE: Nel file Excel devono essere presenti le colonne 'Cognome' e 'Nome'.")
        print(f"Colonne trovate: {list(df.columns)}")
        sys.exit(1)

    print(f"Trovate {len(df)} righe nell'Excel. Inizio importazione su Supabase...\n")

    for idx, row in df.iterrows():
        cognome = pulisci_testo(row[col_cognome])
        nome = pulisci_testo(row[col_nome])

        if not cognome and not nome:
            print(f" Riga {idx + 2}: vuota o priva di Nome e Cognome. Salto...")
            continue

        pid = genera_id_partecipante(cognome, nome, idx)
        nome_visualizzato = f"{cognome} {nome}".strip() if (cognome or nome) else pid

        profilo_json = {
            "cognome": cognome,
            "nome": nome,
            "dettagli_extra": {col: str(val) for col, val in row.items() if not pd.isna(val)}
        }
        try:
            client.table("partecipanti").upsert(
                {
                    "id": pid,
                    "nome_visualizzato": nome_visualizzato,
                    "fase_corrente": "non_iniziato",
                },
                on_conflict="id",
            ).execute()
        except Exception as e:
            print(f"  ✗ Riga {idx + 2} ({nome_visualizzato}): Errore inserimento 'partecipanti' — {e}")
            continue
        try:
            client.table("profili").upsert(
                {
                    "partecipante_id": pid,
                    "profilo_json": profilo_json,
                    "nome_file_origine": file_path.name,
                },
                on_conflict="partecipante_id",
            ).execute()
            print(f"  ✓ Riga {idx + 2}: '{nome_visualizzato}' caricato con ID '{pid}'")
        except Exception as e:
            print(f"  ✗ Riga {idx + 2} ({nome_visualizzato}): Errore inserimento 'profili' — {e}")

    print("\nImportazione completata!")
    print("Verifica su Supabase -> Table Editor -> tabelle 'partecipanti' e 'profili'")


if __name__ == "__main__":
    client = connetti()
    importa_da_excel(client, PERCORSO_EXCEL)