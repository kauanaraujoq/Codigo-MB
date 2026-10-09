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

TOKEN_SGA = os.environ.get("TOKEN_SGA")
USUARIO_API = os.environ.get("USUARIO_API")
SENHA_API = os.environ.get("SENHA_API")
TOKEN_CRM = os.environ.get("TOKEN_CRM")

if not all([TOKEN_SGA, USUARIO_API, SENHA_API]):
    raise SystemExit("❌ Variáveis TOKEN_SGA, USUARIO_API ou SENHA_API ausentes.")

print("🔐 Autenticando na API Hinova...")
res_auth = requests.post(
    "https://api.hinova.com.br/api/sga/v2/usuario/autenticar",
    headers={"Authorization": f"Bearer {TOKEN_SGA}", "Content-Type": "application/json"},
    json={"usuario": USUARIO_API, "senha": SENHA_API},
    timeout=30
)

if res_auth.status_code != 200:
    print(f"❌ Erro {res_auth.status_code} na autenticação:\n{res_auth.text}")
    raise SystemExit(1)

dados_auth = res_auth.json()
token_usuario = dados_auth.get("token_usuario") or dados_auth.get("token_usuário")
if not token_usuario:
    print("❌ Token de usuário não retornado pela API.")
    print("Resposta recebida:", res_auth.text)
    raise SystemExit(1)

print("✅ Autenticação realizada com sucesso!")

headers_sga = {
    "Authorization": f"Bearer {token_usuario}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}


def hinova_request(method, url, **kwargs):
    """Chamada à Hinova. Se o token estiver bloqueado, encerra o script na hora."""
    kwargs.setdefault("timeout", 30)
    r = None
    for tentativa in range(1, 4):
        try:
            r = requests.request(method, url, headers=headers_sga, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as e:
            print(f"⚠️ Erro de rede (tentativa {tentativa}/3): {e}")
            time.sleep(10 * tentativa)
            continue

        if r.status_code == 403 and "BLOQUEADO" in r.text.upper():
            raise SystemExit("❌ Token BLOQUEADO pela Hinova. Execução interrompida. Aguarde ~1h.")
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"⚠️ HTTP {r.status_code} (tentativa {tentativa}/3). Aguardando...")
            time.sleep(10 * tentativa)
            continue
        return r

    if r is None:
        raise RuntimeError(f"Sem resposta da API após 3 tentativas: {url}")
    return r


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
# ROTINA 1: DIM_SITUACAO
# ============================================================
def rotina_situacao():
    print("\n🚀 ROTINA 1: DIM_SITUACAO")
    res = hinova_request("GET", "https://api.hinova.com.br/api/sga/v2/listar/situacao/todos")
    if res.status_code != 200:
        raise RuntimeError(f"Erro {res.status_code} ao buscar situações: {res.text}")

    dados = res.json()
    if isinstance(dados, dict):
        dados = [dados]
    df = pd.DataFrame(dados)
    if not df.empty and "codigo_situacao" in df.columns:
        df = df.sort_values("codigo_situacao")
    print(f"✅ Situações coletadas: {len(df)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "DIM_SITUACAO", df)


# ============================================================
# ROTINA 2: VOLUNTÁRIOS ATIVOS
# ============================================================
def get_voluntarios():
    url = "https://api.hinova.com.br/api/sga/v2/listar/voluntario/ativo"
    voluntarios = []
    pagina = 0
    registros_por_pagina = 5000

    while True:
        res = hinova_request("GET", f"{url}?pagina={pagina}")
        if res.status_code != 200:
            raise RuntimeError(f"Erro {res.status_code} na página {pagina}: {res.text}")

        dados = res.json()
        qtd = len(dados) if isinstance(dados, list) else 0
        if qtd == 0:
            break

        voluntarios.extend(dados)
        print(f"✅ Página {pagina} coletada ({qtd} registros, total: {len(voluntarios)})")

        if qtd < registros_por_pagina:
            break
        pagina += 1
        time.sleep(1)

    return voluntarios


def transformar_voluntarios_df(voluntarios):
    linhas = []
    for v in voluntarios:
        cooperativas = ", ".join(
            (c.get("nome_cooperativa") or "") for c in (v.get("cooperativas") or []) if isinstance(c, dict)
        )
        linhas.append({
            "codigo_voluntario": v.get("codigo_voluntario"),
            "nome": v.get("nome"),
            "cpf": v.get("cpf"),
            "cep": v.get("cep"),
            "telefone": v.get("telefone"),
            "celular": v.get("celular"),
            "email": v.get("email"),
            "logradouro": v.get("logradouro"),
            "numero": v.get("numero"),
            "complemento": v.get("complemento"),
            "bairro": v.get("bairro"),
            "cidade": v.get("cidade"),
            "estado": v.get("estado"),
            "situacao": v.get("situacao"),
            "formato_pagamento": v.get("formato_pagamento"),
            "valor_pagamento": v.get("valor_pagamento"),
            "formato_pagamento_residual": v.get("formato_pagamento_residual"),
            "valor_pagamento_residual": v.get("valor_pagamento_residual"),
            "codigo_classificacao": v.get("codigo_classificacao"),
            "obs": v.get("obs"),
            "cooperativas": cooperativas
        })
    return pd.DataFrame(linhas)


def rotina_voluntarios():
    print("\n🚀 ROTINA 2: VOLUNTÁRIOS SGA")
    df = transformar_voluntarios_df(get_voluntarios())
    print(f"✅ Total de voluntários: {len(df)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "Voluntarios SGA", df)


# ============================================================
# ROTINA 3: SITUAÇÃO DE EVENTO ATIVOS
# ============================================================
def rotina_situacao_evento():
    print("\n🚀 ROTINA 3: SITUAÇÃO DE EVENTO ATIVOS")
    res = hinova_request("GET", "https://api.hinova.com.br/api/sga/v2/situacao-evento/listar/ativo")
    if res.status_code != 200:
        raise RuntimeError(f"Erro {res.status_code}: {res.text}")

    df = pd.DataFrame(res.json())
    print(f"✅ Registros encontrados: {len(df)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "SITUAÇÃO DE EVENTO ATIVOS SGA", df)


# ============================================================
# ROTINA 4: POWER CRM (RESILIENTE COM SESSION E RETRY)
# ============================================================
def rotina_crm():
    print("\n🚀 ROTINA 4: POWER CRM - CRIAÇÃO")
    if not TOKEN_CRM:
        print("⚠️ TOKEN_CRM ausente. Pulando extração do Power CRM.")
        return

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
falhas = []
for nome, func in [
    ("DIM_SITUACAO", rotina_situacao),
    ("Voluntários SGA", rotina_voluntarios),
    ("Situação de Evento", rotina_situacao_evento),
    ("Power CRM", rotina_crm),
]:
    try:
        func()
    except Exception as e:  # SystemExit (token bloqueado) não é capturado, de propósito
        print(f"❌ Rotina '{nome}' falhou: {e}")
        falhas.append(nome)

if falhas:
    print(f"\n⚠️ Finalizado com falhas em: {', '.join(falhas)}")
    raise SystemExit(1)

print("\n🎉 Todas as rotinas foram executadas com sucesso!")
