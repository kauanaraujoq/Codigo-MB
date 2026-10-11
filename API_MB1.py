import os
import json
import time
import math
import requests
import pandas as pd
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"
TAMANHO_LOTE_SHEETS = 2000


# ============================================================
# 1. ENVIO EM LOTES PARA O GOOGLE SHEETS
# ============================================================
def enviar_para_sheets_em_lotes(service, spreadsheet_id, sheet_name, df, tamanho_lote=TAMANHO_LOTE_SHEETS):
    if df.empty:
        print(f"⚠️ DataFrame vazio para a aba '{sheet_name}'. Nada enviado (aba preservada).")
        return

    df = df.fillna("").astype(str)
    df = df.apply(lambda x: x.str.encode("utf-8", "ignore").str.decode("utf-8"))

    print(f"🧹 Limpando aba '{sheet_name}'...")
    for tentativa in range(1, 4):
        try:
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_name}'"
            ).execute()
            break
        except Exception as e:
            print(f"⚠️ Erro ao limpar aba (tentativa {tentativa}/3): {e}")
            if tentativa == 3:
                raise Exception(f"Não foi possível limpar a aba '{sheet_name}'.")
            time.sleep(5)

    dados = [df.columns.tolist()] + df.values.tolist()
    total_lotes = math.ceil(len(dados) / tamanho_lote)
    print(f"📊 Linhas: {len(dados)} | Lotes: {total_lotes}")

    for i in range(0, len(dados), tamanho_lote):
        lote = dados[i:i + tamanho_lote]
        linha_inicial = i + 1
        numero_lote = (i // tamanho_lote) + 1

        for tentativa in range(1, 6):
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{sheet_name}'!A{linha_inicial}",
                    valueInputOption="RAW",
                    body={"values": lote}
                ).execute()
                print(f"✅ Lote {numero_lote}/{total_lotes} enviado.")
                break
            except Exception as e:
                print(f"⚠️ Erro no lote {numero_lote}: {e}")
                if tentativa == 5:
                    raise Exception(f"Falha ao enviar lote {numero_lote}: {e}")
                time.sleep(10 * tentativa)
        time.sleep(1)

    print(f"✅ Aba '{sheet_name}' atualizada.\n")


# ============================================================
# 2. CONFIGURAÇÕES E AUTENTICAÇÃO
# ============================================================
print("🔎 Verificando variáveis de ambiente...")

TOKEN_CRM = os.environ.get("TOKEN_CRM")
if not TOKEN_CRM:
    raise SystemExit("❌ Variável TOKEN_CRM ausente.")

# ---------------- CONEXÃO GOOGLE SHEETS ----------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if os.path.exists(SERVICE_ACCOUNT_FILE):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
else:
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not google_creds_json:
        raise SystemExit("❌ Credenciais do Google não encontradas.")
    creds = Credentials.from_service_account_info(json.loads(google_creds_json), scopes=SCOPES)

service = build("sheets", "v4", credentials=creds)


# ============================================================
# ROTINA: POWER CRM (RESILIENTE COM SESSION E RETRY)
# ============================================================
def rotina_crm():
    print("\n🚀 POWER CRM - CRIAÇÃO")

    url_crm = "https://api.powercrm.com.br/api/report/db"
    headers_crm = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {TOKEN_CRM}"
    }

    end_date = datetime.today()
    current_start = datetime(2023, 1, 1)
    all_crm_data = []

    session_crm = requests.Session()

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=29), end_date)
        payload = {
            "from": current_start.strftime("%Y-%m-%d"),
            "to": current_end.strftime("%Y-%m-%d"),
            "stringFilterTypeDate": 1
        }

        ok = False
        for tentativa in range(1, 4):
            try:
                res = session_crm.post(url_crm, headers=headers_crm, json=payload, timeout=60)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list):
                        all_crm_data.extend(data)
                    print(f"✅ CRM ({payload['from']} a {payload['to']}): {len(all_crm_data)} acumulados")
                    ok = True
                    break
                print(f"⚠️ Erro {res.status_code} no CRM (tentativa {tentativa}/3): {res.text[:200]}")
            except requests.RequestException as e:
                print(f"⚠️ Desconexão/Erro de rede no CRM na janela {payload['from']} a {payload['to']} (tentativa {tentativa}/3): {e}")

            time.sleep(5 * tentativa)

        if not ok:
            raise RuntimeError(f"Falha no CRM na janela {payload['from']} a {payload['to']}")

        current_start = current_end + timedelta(days=1)
        time.sleep(1.5)

    df_crm = pd.DataFrame(all_crm_data)
    print(f"✅ Total de registros CRM: {len(df_crm)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "Dados de Criação CRM", df_crm)


# ============================================================
# EXECUÇÃO
# ============================================================
try:
    rotina_crm()
except Exception as e:
    print(f"❌ Rotina 'Power CRM' falhou: {e}")
    raise SystemExit(1)

print("\n🎉 Execução concluída com sucesso!")
