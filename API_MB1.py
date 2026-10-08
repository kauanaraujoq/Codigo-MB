import os
import json
import time
import math
import requests
import pandas as pd
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ============================================================
# 1. FUNÇÃO AUXILIAR: CARGA EM LOTES NO GOOGLE SHEETS
# ============================================================
def enviar_para_sheets_em_lotes(
    service,
    spreadsheet_id,
    sheet_name,
    df,
    tamanho_lote=200
):
    """
    Limpa a aba informada e envia o DataFrame para o Google Sheets em blocos.
    """
    if df.empty:
        print(f"⚠️ DataFrame vazio para a aba '{sheet_name}'. Nada enviado.")
        return

    # Limpeza e padronização UTF-8
    df = df.fillna("")
    df = df.astype(str)
    df = df.apply(
        lambda x: x.str.encode("utf-8", "ignore").str.decode("utf-8")
    )

    # ---------------- LIMPAR ABA ----------------
    print(f"🧹 Limpando aba '{sheet_name}'...")
    for tentativa in range(1, 4):
        try:
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=sheet_name
            ).execute()
            print("✅ Aba limpa com sucesso.")
            break
        except Exception as e:
            print(f"⚠️ Erro ao limpar aba (tentativa {tentativa}/3): {e}")
            if tentativa == 3:
                raise Exception(f"❌ Não foi possível limpar a aba '{sheet_name}'.")
            time.sleep(5)

    # ---------------- PREPARAR E ENVIAR DADOS ----------------
    dados = [df.columns.tolist()] + df.values.tolist()
    total_lotes = math.ceil(len(dados) / tamanho_lote)

    print(f"📊 Total de linhas: {len(dados)} | Total de lotes: {total_lotes}")

    for i in range(0, len(dados), tamanho_lote):
        lote = dados[i:i + tamanho_lote]
        linha_inicial = i + 1
        numero_lote = (i // tamanho_lote) + 1

        for tentativa in range(1, 6):
            try:
                print(
                    f"📤 Enviando lote {numero_lote}/{total_lotes} "
                    f"- linhas {linha_inicial} até {linha_inicial + len(lote) - 1} "
                    f"(tentativa {tentativa}/5)"
                )
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_name}!A{linha_inicial}",
                    valueInputOption="RAW",
                    body={"values": lote}
                ).execute()
                print(f"✅ Lote {numero_lote}/{total_lotes} enviado.")
                break
            except TimeoutError:
                print(f"⏱️ Timeout no lote {numero_lote}. Tentativa {tentativa}/5.")
                if tentativa == 5:
                    raise Exception(f"❌ Timeout persistente no lote {numero_lote}.")
                time.sleep(5 * tentativa)
            except Exception as e:
                print(f"⚠️ Erro no lote {numero_lote}: {e}")
                if tentativa == 5:
                    raise Exception(f"❌ Falha ao enviar lote {numero_lote}: {e}")
                time.sleep(5 * tentativa)

    print(f"✅ Envio para a aba '{sheet_name}' concluído com sucesso.\n")


# ============================================================
# 2. CONFIGURAÇÕES INICIAIS E AUTENTICAÇÃO GOOGLE
# ============================================================
print("🔎 Verificando variáveis de ambiente...")

TOKEN_SGA = os.environ.get("TOKEN_SGA")
TOKEN_CRM = os.environ.get("TOKEN_CRM")
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"

print("TOKEN_SGA:", "OK" if TOKEN_SGA else "AUSENTE")
print("TOKEN_CRM:", "OK" if TOKEN_CRM else "AUSENTE")

if not TOKEN_SGA:
    raise SystemExit("❌ TOKEN_SGA não foi encontrado nas variáveis de ambiente.")

# Inicializa credenciais do Google Sheets (prioriza ficheiro local, fallback para Secret JSON)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if os.path.exists(SERVICE_ACCOUNT_FILE):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
else:
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not google_creds_json:
        raise SystemExit("❌ Credenciais do Google não encontradas (ficheiro JSON ou secret GOOGLE_CREDENTIALS).")
    info = json.loads(google_creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)

service = build("sheets", "v4", credentials=creds)

headers_sga = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN_SGA}"
}


# ============================================================
# ROTINA 1: EVENTOS SGA (LISTAR)
# ============================================================
print("\n============================================================")
print("🚀 ROTINA 1: EVENTOS SGA")
print("============================================================")

def get_eventos(data_inicio, data_fim):
    url = "https://api.hinova.com.br/api/sga/v2/listar/evento"
    eventos = []
    inicio_paginacao = 0
    quantidade_por_pagina = 1500

    while True:
        payload = {
            "data_cadastro": data_inicio,
            "data_cadastro_final": data_fim,
            "inicio_paginacao": inicio_paginacao,
            "quantidade_por_pagina": quantidade_por_pagina
        }

        response = requests.post(url, headers=headers_sga, json=payload, timeout=(30, 120))

        if response.status_code == 406:
            break
        if response.status_code != 200:
            print(f"❌ Erro {response.status_code} ao buscar eventos: {response.text}")
            break

        dados = response.json()
        if not isinstance(dados, list) or len(dados) == 0:
            break

        eventos.extend(dados)
        inicio_paginacao += quantidade_por_pagina
        time.sleep(0.3)

    return eventos

def transformar_eventos_df(eventos):
    linhas = []
    for e in eventos:
        linha = {
            "codigo_evento": e.get("codigo_evento"),
            "codigo_classificacao": e.get("codigo_classificacao"),
            "codigo_veiculo": e.get("codigo_veiculo"),
            "codigo_associado": e.get("codigo_associado"),
            "valor_reparo": e.get("valor_reparo"),
            "participacao": e.get("participacao"),
            "passivel_ressarcimento": e.get("passivel_ressarcimento"),
            "evento_tipo": e.get("evento_tipo"),
            "motivo": e.get("motivo"),
            "envolvimento": e.get("envolvimento"),
            "situacao_evento": e.get("situacao_evento"),
            "data_evento": e.get("data_evento"),
            "hora_evento": e.get("hora_evento"),
            "data_cadastro": e.get("data_cadastro"),
            "hora_cadastro": e.get("hora_cadastro"),
            "protocolo": e.get("protocolo"),
            "cidade": e.get("cidade"),
            "estado": e.get("estado"),
            "bairro": e.get("bairro"),
            "logradouro": e.get("logradouro"),
            "cep": e.get("cep"),
            "associado_nome": e.get("associado", {}).get("nome"),
            "associado_cpf": e.get("associado", {}).get("cpf"),
            "associado_email": e.get("associado", {}).get("email"),
            "associado_telefone": e.get("associado", {}).get("telefone"),
            "veiculo_placa": e.get("veiculo", {}).get("placa"),
            "veiculo_modelo": e.get("veiculo", {}).get("modelo"),
            "veiculo_marca": e.get("veiculo", {}).get("marca"),
            "veiculo_ano_modelo": e.get("veiculo", {}).get("ano_modelo"),
            "veiculo_ano_fabricacao": e.get("veiculo", {}).get("ano_fabricacao"),
            "veiculo_valor_fipe": e.get("veiculo", {}).get("valor_fipe"),
            "condutor_nome": e.get("condutor", {}).get("nome"),
            "condutor_cpf": e.get("condutor", {}).get("cpf"),
            "condutor_cidade": e.get("condutor", {}).get("cidade"),
            "condutor_estado": e.get("condutor", {}).get("estado"),
            "regional": e.get("regional", {}).get("descricao"),
            "cooperativa": e.get("cooperativa", {}).get("descricao"),
            "voluntario": e.get("voluntario", {}).get("descricao")
        }
        linhas.append(linha)
    return pd.DataFrame(linhas)

def coletar_eventos_periodo(data_inicio_str):
    data_inicio = datetime.strptime(data_inicio_str, "%d/%m/%Y")
    data_fim = datetime.today()
    delta_dias = 30
    all_eventos = []
    current_start = data_inicio

    while current_start <= data_fim:
        current_end = min(current_start + timedelta(days=delta_dias - 1), data_fim)
        print(f"⏳ Buscando eventos de {current_start.strftime('%d/%m/%Y')} até {current_end.strftime('%d/%m/%Y')}...")
        bloco = get_eventos(current_start.strftime("%d/%m/%Y"), current_end.strftime("%d/%m/%Y"))
        all_eventos.extend(bloco)
        current_start = current_end + timedelta(days=1)

    return all_eventos

eventos_totais = coletar_eventos_periodo("01/01/2023")
df_eventos = transformar_eventos_df(eventos_totais)
print(f"✅ Total de eventos coletados: {len(df_eventos)}")

enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "EVENTOS SGA - LISTAR", df_eventos)


# ============================================================
# ROTINA 2: DIMENSÃO SITUAÇÃO (SGA)
# ============================================================
print("\n============================================================")
print("🚀 ROTINA 2: DIM_SITUACAO")
print("============================================================")

url_situacao = "https://api.hinova.com.br/api/sga/v2/listar/situacao/todos"
res_sit = requests.get(url_situacao, headers=headers_sga, timeout=30)

if res_sit.status_code == 200:
    dados_sit = res_sit.json()
    if isinstance(dados_sit, dict):
        dados_sit = [dados_sit]
    df_situacao = pd.DataFrame(dados_sit)
    if not df_situacao.empty and "codigo_situacao" in df_situacao.columns:
        df_situacao = df_situacao.sort_values("codigo_situacao")
    print(f"✅ Total de situações coletadas: {len(df_situacao)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "DIM_SITUACAO", df_situacao)
else:
    print(f"❌ Erro {res_sit.status_code} ao buscar situações: {res_sit.text}")


# ============================================================
# ROTINA 3: VOLUNTÁRIOS ATIVOS (SGA)
# ============================================================
print("\n============================================================")
print("🚀 ROTINA 3: VOLUNTÁRIOS SGA")
print("============================================================")

def get_voluntarios():
    url_voluntario = "https://api.hinova.com.br/api/sga/v2/listar/voluntario/ativo"
    voluntarios = []
    pagina = 0
    registros_por_pagina = 5000

    while True:
        url_paginada = f"{url_voluntario}?pagina={pagina}"
        response = requests.get(url_paginada, headers=headers_sga, timeout=30)

        if response.status_code != 200:
            print(f"❌ Erro {response.status_code} na página {pagina}: {response.text}")
            break

        dados = response.json()
        qtd = len(dados) if isinstance(dados, list) else 0
        if qtd == 0:
            break

        voluntarios.extend(dados)
        print(f"✅ Página {pagina} coletada ({qtd} registros, total: {len(voluntarios)})")

        if qtd < registros_por_pagina:
            break
        pagina += 1
        time.sleep(0.3)

    return voluntarios

def transformar_voluntarios_df(voluntarios):
    linhas = []
    for v in voluntarios:
        cooperativas = ", ".join([c.get("nome_cooperativa", "") for c in v.get("cooperativas", [])])
        linha = {
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
        }
        linhas.append(linha)
    return pd.DataFrame(linhas)

voluntarios_totais = get_voluntarios()
df_voluntarios = transformar_voluntarios_df(voluntarios_totais)
print(f"✅ Total de voluntários: {len(df_voluntarios)}")

enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "Voluntarios SGA", df_voluntarios)


# ============================================================
# ROTINA 4: SITUAÇÃO DE EVENTO ATIVOS (SGA)
# ============================================================
print("\n============================================================")
print("🚀 ROTINA 4: SITUAÇÃO DE EVENTO ATIVOS")
print("============================================================")

url_sit_evento = "https://api.hinova.com.br/api/sga/v2/situacao-evento/listar/ativo"
res_sit_ev = requests.get(url_sit_evento, headers=headers_sga, timeout=30)

if res_sit_ev.status_code == 200:
    dados_sit_ev = res_sit_ev.json()
    df_sit_evento = pd.DataFrame(dados_sit_ev)
    print(f"✅ Registros encontrados: {len(df_sit_evento)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "SITUAÇÃO DE EVENTO ATIVOS SGA", df_sit_evento)
else:
    print(f"❌ Erro {res_sit_ev.status_code}: {res_sit_ev.text}")


# ============================================================
# ROTINA 5: EXTRAÇÃO DE VEÍCULOS (SGA)
# ============================================================
print("\n============================================================")
print("🚀 ROTINA 5: LISTAGEM DE VEÍCULOS SGA")
print("============================================================")

def get_veiculos_por_situacao(codigo_situacao):
    url_veiculo = "https://api.hinova.com.br/api/sga/v2/listar/veiculo"
    veiculos = []
    inicio_paginacao = 0
    quantidade_por_pagina = 1500

    while True:
        payload = {
            "codigo_situacao": codigo_situacao,
            "inicio_paginacao": inicio_paginacao,
            "quantidade_por_pagina": quantidade_por_pagina
        }

        response = requests.post(url_veiculo, headers=headers_sga, json=payload, timeout=(30, 120))

        if response.status_code == 406:
            break
        if response.status_code != 200:
            print(f"❌ Erro {response.status_code} ao buscar veículos: {response.text}")
            break

        dados = response.json()
        lista = dados.get("veiculos", []) if isinstance(dados, dict) else []

        if not lista:
            break

        veiculos.extend(lista)
        inicio_paginacao += quantidade_por_pagina
        time.sleep(0.5)

    return veiculos

def transformar_veiculos_df(veiculos):
    linhas = []
    for v in veiculos:
        linha = {
            "codigo_veiculo": v.get("codigo_veiculo"),
            "codigo_associado": v.get("codigo_associado"),
            "codigo_situacao_veiculo": v.get("codigo_situacao_veiculo") or v.get("codigo_situacao") or v.get("situacao"),
            "placa": v.get("placa"),
            "chassi": v.get("chassi"),
            "renavam": v.get("renavam"),
            "marca": v.get("marca"),
            "modelo": v.get("modelo"),
            "categoria": v.get("categoria"),
            "tipo": v.get("tipo"),
            "ano_fabricacao": v.get("ano_fabricacao"),
            "ano_modelo": v.get("ano_modelo"),
            "valor_fipe": v.get("valor_fipe"),
            "valor_fipe_protegido": v.get("valor_fipe_protegido"),
            "valor_adesao": v.get("valor_adesao"),
            "data_cadastro": v.get("data_cadastro"),
            "data_contrato": v.get("data_contrato"),
            "data_contrato_final": v.get("data_contrato_final"),
            "codigo_regional": v.get("codigo_regional"),
            "codigo_cooperativa": v.get("codigo_cooperativa"),
            "codigo_voluntario": v.get("codigo_voluntario"),
            "nome_voluntario": v.get("nome_voluntario"),
            "nome_associado": v.get("nome_associado"),
            "cpf_associado": v.get("cpf_associado"),
        }
        linhas.append(linha)
    return pd.DataFrame(linhas)

codigos_situacao = [1]
todos_veiculos = []

for codigo in codigos_situacao:
    print(f"⏳ Coletando veículos da situação {codigo}...")
    veic = get_veiculos_por_situacao(codigo)
    print(f"✅ {len(veic)} veículos encontrados.")
    todos_veiculos.extend(veic)

df_veiculos = transformar_veiculos_df(todos_veiculos)
print(f"✅ Total geral de veículos: {len(df_veiculos)}")

enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "LISTAGEM_VEICULOS_SGA", df_veiculos)


# ============================================================
# ROTINA 6: POWER CRM (DADOS DE CRIAÇÃO)
# ============================================================
print("\n============================================================")
print("🚀 ROTINA 6: POWER CRM - CRIAÇÃO")
print("============================================================")

if TOKEN_CRM:
    url_crm = "https://api.powercrm.com.br/api/report/db"
    headers_crm = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {TOKEN_CRM}"
    }

    start_date = datetime(2023, 1, 1)
    end_date = datetime.today()
    delta_days = 30
    all_crm_data = []
    current_start = start_date

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=delta_days - 1), end_date)
        payload_crm = {
            "from": current_start.strftime("%Y-%m-%d"),
            "to": current_end.strftime("%Y-%m-%d"),
            "stringFilterTypeDate": 1
        }

        res_crm = requests.post(url_crm, headers=headers_crm, json=payload_crm, timeout=30)

        if res_crm.status_code == 200:
            data = res_crm.json()
            if isinstance(data, list):
                all_crm_data.extend(data)
            print(f"✅ CRM ({payload_crm['from']} a {payload_crm['to']}): {len(all_crm_data)} acumulados")
        else:
            print(f"❌ Erro {res_crm.status_code} no CRM ({payload_crm['from']} a {payload_crm['to']}): {res_crm.text}")
            time.sleep(3)

        current_start = current_end + timedelta(days=1)

    df_crm = pd.DataFrame(all_crm_data)
    print(f"✅ Total de registros CRM: {len(df_crm)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "Dados de Criação CRM", df_crm)
else:
    print("⚠️ TOKEN_CRM ausente. Pulando extração do Power CRM.")

print("\n🎉 Todas as rotinas foram executadas com sucesso!")
