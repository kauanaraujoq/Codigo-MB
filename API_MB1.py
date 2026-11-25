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

# Retry / divisão de janelas
MAX_TENTATIVAS = 6            # tentativas por requisição
ESPERA_INICIAL = 15           # segundos (dobra a cada tentativa)
ESPERA_MAXIMA = 240           # teto da espera
NIVEL_MAX_DIVISAO = 5         # 30d -> 15d -> 8d -> 4d -> 2d -> 1d
STATUS_RETENTAVEIS = {429, 500, 502, 503, 504}
PERMITIR_PARCIAL = os.environ.get("PERMITIR_PARCIAL", "0") == "1"


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
# ROTINA: POWER CRM (RETRY COM BACKOFF + DIVISÃO DE JANELA)
# ============================================================
class FalhaCRM(Exception):
    pass


URL_CRM = "https://api.powercrm.com.br/api/report/db"


def chamar_crm(session, headers, inicio, fim):
    """Uma janela, com retry e backoff exponencial. Levanta FalhaCRM se esgotar."""
    payload = {
        "from": inicio.strftime("%Y-%m-%d"),
        "to": fim.strftime("%Y-%m-%d"),
        "stringFilterTypeDate": 1
    }
    espera = ESPERA_INICIAL

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            res = session.post(URL_CRM, headers=headers, json=payload, timeout=120)
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, list) else []

            print(f"⚠️ Erro {res.status_code} no CRM ({payload['from']} a {payload['to']}, "
                  f"tentativa {tentativa}/{MAX_TENTATIVAS}): {res.text[:150]}")
            if res.status_code not in STATUS_RETENTAVEIS:
                # 401/403/400 etc.: repetir não adianta
                raise SystemExit(f"❌ Erro não retentável {res.status_code}: {res.text[:200]}")
        except requests.RequestException as e:
            print(f"⚠️ Erro de rede no CRM ({payload['from']} a {payload['to']}, "
                  f"tentativa {tentativa}/{MAX_TENTATIVAS}): {e}")

        if tentativa < MAX_TENTATIVAS:
            time.sleep(espera)
            espera = min(espera * 2, ESPERA_MAXIMA)

    raise FalhaCRM(f"{payload['from']} a {payload['to']}")


def buscar_janela(session, headers, inicio, fim, nivel=0):
    """Tenta a janela inteira; se falhar, divide ao meio e tenta cada metade."""
    try:
        dados = chamar_crm(session, headers, inicio, fim)
        print(f"✅ CRM ({inicio:%Y-%m-%d} a {fim:%Y-%m-%d}): {len(dados)} registros")
        return dados, []
    except FalhaCRM:
        dias = (fim - inicio).days
        if dias < 1 or nivel >= NIVEL_MAX_DIVISAO:
            print(f"❌ Janela {inicio:%Y-%m-%d} a {fim:%Y-%m-%d} não recuperada.")
            return [], [(inicio, fim)]

        meio = inicio + timedelta(days=dias // 2)
        print(f"✂️ Dividindo {inicio:%Y-%m-%d} a {fim:%Y-%m-%d} em duas partes...")
        d1, f1 = buscar_janela(session, headers, inicio, meio, nivel + 1)
        d2, f2 = buscar_janela(session, headers, meio + timedelta(days=1), fim, nivel + 1)
        return d1 + d2, f1 + f2


def rotina_crm():
    print("\n🚀 POWER CRM - CRIAÇÃO")

    headers_crm = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {TOKEN_CRM}"
    }

    end_date = datetime.today()
    current_start = datetime(2023, 1, 1)
    all_crm_data = []
    janelas_falhas = []

    session_crm = requests.Session()

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=29), end_date)

        dados, falhas = buscar_janela(session_crm, headers_crm, current_start, current_end)
        all_crm_data.extend(dados)
        janelas_falhas.extend(falhas)
        print(f"   acumulado: {len(all_crm_data)}")

        current_start = current_end + timedelta(days=1)
        time.sleep(1.5)

    if janelas_falhas:
        lista = "\n".join(f"  - {a:%Y-%m-%d} a {b:%Y-%m-%d}" for a, b in janelas_falhas)
        print(f"\n⚠️ Janelas que falharam:\n{lista}")
        if not PERMITIR_PARCIAL:
            raise RuntimeError(
                "Há janelas sem dados. A planilha NÃO foi alterada para não perder histórico. "
                "Rode de novo mais tarde ou defina PERMITIR_PARCIAL=1 para enviar mesmo assim."
            )

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
