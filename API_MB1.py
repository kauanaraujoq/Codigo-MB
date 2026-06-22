import os
import requests
import json
import pandas as pd

# === 1 CONFIGURAÇÕES ===
url_autenticacao = "https://api.hinova.com.br/api/sga/v2/usuario/autenticar"

# O código vai buscar os valores na "caixa forte" (Secrets) que você criará no GitHub
token_sga = os.environ.get('TOKEN_SGA')
usuario = os.environ.get('USUARIO_API')
senha = os.environ.get('SENHA_API')


# === 2️⃣ CABEÇALHO ===
headers = {
    "Authorization": f"Bearer {token_sga}",
    "Content-Type": "application/json"
}

# === 3️⃣ CORPO (BODY) DA REQUISIÇÃO ===
payload = {
    "usuario": usuario,
    "senha": senha
}

# === 4️⃣ FAZER REQUISIÇÃO POST PARA GERAR TOKEN_USUARIO ===
resposta = requests.post(url_autenticacao, headers=headers, json=payload)

# === 5️⃣ TRATAR RETORNO ===
if resposta.status_code == 200:
    dados = resposta.json()
    print("✅ Autenticação bem-sucedida!")
    print(json.dumps(dados, indent=2, ensure_ascii=False))
    token_usuario = dados.get("token_usuario") or dados.get("token_usuário")  # depende do campo exato
    print("\n🔑 Seu token de acesso (use nas próximas requisições):")
    print(token_usuario)
else:
    print(f"❌ Erro {resposta.status_code}: {resposta.text}")

# %%
# ==============================
# EXTRAÇÃO API - EVENTOS (SGA) - LISTAR
# ==============================

import requests
import pandas as pd
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- CONFIG GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SHEET_NAME = "EVENTOS SGA - LISTAR"

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("sheets", "v4", credentials=creds)

# ---------------- CONFIG API ----------------
URL = "https://api.hinova.com.br/api/sga/v2/listar/evento"
TOKEN = token_usuario

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

# ---------------- FUNÇÃO PAGINAÇÃO ----------------
def get_eventos(data_inicio, data_fim):
    eventos = []
    inicio_paginacao = 0
    quantidade_por_pagina = 100

    while True:
        payload = {
            "data_cadastro": data_inicio,
            "data_cadastro_final": data_fim,
            "inicio_paginacao": inicio_paginacao,
            "quantidade_por_pagina": quantidade_por_pagina
        }

        response = requests.post(URL, headers=headers, json=payload, timeout=(30,120))

        if response.status_code == 406:
            break

        if response.status_code != 200:
            print(f"❌ Erro {response.status_code}: {response.text}")
            break

        dados = response.json()

        if not isinstance(dados, list) or len(dados) == 0:
            break

        eventos.extend(dados)
        inicio_paginacao += quantidade_por_pagina

    return eventos

# ---------------- TRANSFORMAÇÃO ----------------
def transformar_em_dataframe(eventos):
    linhas = []

    for e in eventos:
        linha = {
            # --- EVENTO ---
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

            # --- LOCAL ---
            "cidade": e.get("cidade"),
            "estado": e.get("estado"),
            "bairro": e.get("bairro"),
            "logradouro": e.get("logradouro"),
            "cep": e.get("cep"),

            # --- ASSOCIADO ---
            "associado_nome": e.get("associado", {}).get("nome"),
            "associado_cpf": e.get("associado", {}).get("cpf"),
            "associado_email": e.get("associado", {}).get("email"),
            "associado_telefone": e.get("associado", {}).get("telefone"),

            # --- VEÍCULO ---
            "veiculo_placa": e.get("veiculo", {}).get("placa"),
            "veiculo_modelo": e.get("veiculo", {}).get("modelo"),
            "veiculo_marca": e.get("veiculo", {}).get("marca"),
            "veiculo_ano_modelo": e.get("veiculo", {}).get("ano_modelo"),
            "veiculo_ano_fabricacao": e.get("veiculo", {}).get("ano_fabricacao"),
            "veiculo_valor_fipe": e.get("veiculo", {}).get("valor_fipe"),

            # --- CONDUTOR ---
            "condutor_nome": e.get("condutor", {}).get("nome"),
            "condutor_cpf": e.get("condutor", {}).get("cpf"),
            "condutor_cidade": e.get("condutor", {}).get("cidade"),
            "condutor_estado": e.get("condutor", {}).get("estado"),

            # --- ORGANIZACIONAL ---
            "regional": e.get("regional", {}).get("descricao"),
            "cooperativa": e.get("cooperativa", {}).get("descricao"),
            "voluntario": e.get("voluntario", {}).get("descricao"),
        }

        linhas.append(linha)

    return pd.DataFrame(linhas)

# ---------------- COLETA EM BLOCOS DE 30 DIAS ----------------
def coletar_periodo_total(data_inicio_str):
    data_inicio = datetime.strptime(data_inicio_str, "%d/%m/%Y")
    data_fim = datetime.today()
    delta_dias = 30

    all_eventos = []
    current_start = data_inicio

    while current_start <= data_fim:
        current_end = min(current_start + timedelta(days=delta_dias-1), data_fim)
        print(f"⏳ {current_start.strftime('%d/%m/%Y')} -> {current_end.strftime('%d/%m/%Y')}")

        bloco = get_eventos(
            current_start.strftime("%d/%m/%Y"),
            current_end.strftime("%d/%m/%Y")
        )

        all_eventos.extend(bloco)
        current_start = current_end + timedelta(days=1)

    return all_eventos

# ---------------- EXECUÇÃO ----------------
eventos_totais = coletar_periodo_total("01/01/2023")
df = transformar_em_dataframe(eventos_totais)

print(f"\n✅ Total de eventos: {len(df)}")

# ---------------- LIMPEZA ----------------
if not df.empty:
    df = df.fillna('')
    df = df.astype(str)
    df = df.apply(lambda x: x.str.encode('utf-8', 'ignore').str.decode('utf-8'))

    values_to_write = [df.columns.to_list()] + df.values.tolist()

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=SHEET_NAME,
        valueInputOption="RAW",
        body={"values": values_to_write}
    ).execute()

    print("✅ Enviado ao Google Sheets com sucesso.")
else:
    print("⚠️ DataFrame vazio.")


# %%
# ==============================
# EXTRAÇÃO API - SITUAÇÕES (SGA)
# DIM_SITUACAO
# ==============================

import requests
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- CONFIG GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SHEET_NAME = "DIM_SITUACAO"

creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("sheets", "v4", credentials=creds)

# ---------------- CONFIG API ----------------
URL = "https://api.hinova.com.br/api/sga/v2/listar/situacao/todos"
TOKEN = token_usuario

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

# ---------------- EXTRAÇÃO ----------------
response = requests.get(URL, headers=headers, timeout=30)

if response.status_code != 200:
    raise Exception(f"Erro {response.status_code}: {response.text}")

dados = response.json()

# garante lista
if isinstance(dados, dict):
    dados = [dados]

# ---------------- TRANSFORMAÇÃO ----------------
df = pd.DataFrame(dados)

# ordena por código (boa prática)
df = df.sort_values("codigo_situacao")

# limpeza
df = df.fillna("")
df = df.astype(str)
df = df.apply(lambda x: x.str.encode("utf-8", "ignore").str.decode("utf-8"))

print(f"✅ Total de situações coletadas: {len(df)}")

# ---------------- CARGA GOOGLE SHEETS ----------------
values_to_write = [df.columns.to_list()] + df.values.tolist()

service.spreadsheets().values().update(
    spreadsheetId=SPREADSHEET_ID,
    range=SHEET_NAME,
    valueInputOption="RAW",
    body={"values": values_to_write}
).execute()

print("✅ DIM_SITUACAO enviada ao Google Sheets.")


# %%
## VOLUNTARIO - ATIVOS VINDOS DO SGA
import requests
import pandas as pd
from datetime import datetime, timedelta
import requests
import json
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- CONFIGURAÇÃO GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"  # JSON da conta de serviço
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SHEET_NAME = "Voluntarios SGA"  # nova aba para voluntários

# Credenciais e serviço
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("sheets", "v4", credentials=creds)

# ---------------- CONFIGURAÇÃO API ----------------
URL_SGA = "https://api.hinova.com.br/api/sga/v2/listar/voluntario/ativo"

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Bearer {token_usuario}"
}

# ---------------- FUNÇÃO PARA PAGINAÇÃO ----------------
def get_voluntarios():
    voluntarios = []
    pagina = 0
    registros_por_pagina = 5000  # padrão da API

    while True:
        url_paginada = f"{URL_SGA}?pagina={pagina}"
        response = requests.get(url_paginada, headers=headers)

        if response.status_code != 200:
            print(f"❌ Erro {response.status_code} na página {pagina}")
            break

        dados = response.json()
        qtd_retorno = len(dados) if isinstance(dados, list) else 0

        if qtd_retorno == 0:
            break

        voluntarios.extend(dados)
        print(f"✅ Página {pagina} coletada, registros nesta página: {qtd_retorno}, total acumulado: {len(voluntarios)}")

        # Se a quantidade retornada for menor que o máximo por página, acabou
        if qtd_retorno < registros_por_pagina:
            break

        pagina += 1

    return voluntarios


# ---------------- FUNÇÃO PARA TRANSFORMAR EM DATAFRAME ----------------
def transformar_em_dataframe(voluntarios):
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

# ---------------- EXECUÇÃO ----------------
voluntarios_totais = get_voluntarios()
df = transformar_em_dataframe(voluntarios_totais)

print(f"\n✅ Total de voluntários coletados: {len(df)}")
print(df.head())


# %%
## SITUAÇÃO DE EVENTO - ATIVOS VINDOS DO SGA

import requests
import json
import pandas as pd
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- CONFIGURAÇÃO GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"  # JSON da conta de serviço
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SHEET_NAME = "SITUAÇÃO DE EVENTO ATIVOS SGA"  # aba da planilha

# Credenciais e serviço
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("sheets", "v4", credentials=creds)

situacao = "situacao-evento/listar/ativo"
URL_base = "https://api.hinova.com.br/api/sga/v2/"


headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token_usuario}"
}

resposta = requests.get(URL_base + situacao, headers=headers)

if resposta.status_code == 200:
    print("Requisição bem-sucedida!\n")
    
    dados = resposta.json()
    
    # Converte em DataFrame
    df = pd.DataFrame(dados)
    
    print("\n📊 DataFrame gerado:")
    print(df.head())
else:
    print(f"❌ Erro {resposta.status_code}: {resposta.text}")

if not df.empty:
    df = df.fillna('')  # substitui NaN por string vazia
    df = df.astype(str)  # garante que tudo seja string
    df = df.apply(lambda x: x.str.encode('utf-8', 'ignore').str.decode('utf-8'))  # remove caracteres problemáticos

    # ---------------- ENVIO PARA GOOGLE SHEETS ----------------
    values_to_write = [df.columns.to_list()] + df.values.tolist()

    # Sobrescreve a aba com os novos dados (sem clear)
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=SHEET_NAME,
        valueInputOption="RAW",
        body={"values": values_to_write}
    ).execute()

    print("✅ Dados enviados para o Google Sheets com conta de serviço!")
else:
    print("⚠️ DataFrame vazio, nada enviado para o Google Sheets.")


# %%
# ==============================
# EXTRAÇÃO DE VEÍCULOS (SGA)
# LISTAGEM_VEICULOS_SGA
# CÓDIGO INICIAL DO CODIGO DE CIMA, É PRA SALVAR PQ A API ESTÁ COM PROBLEMAS
# ==============================

import requests
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- CONFIG GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SHEET_NAME = "LISTAGEM_VEICULOS_SGA"

creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES
)

service = build("sheets", "v4", credentials=creds)

# ---------------- CONFIG API ----------------
URL = "https://api.hinova.com.br/api/sga/v2/listar/veiculo"
TOKEN = token_usuario

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

# ---------------- FUNÇÃO DE PAGINAÇÃO ----------------
def get_veiculos_por_situacao(codigo_situacao):
    veiculos = []
    inicio_paginacao = 0
    quantidade_por_pagina = 1000

    while True:
        payload = {
            "codigo_situacao": codigo_situacao,
            "inicio_paginacao": inicio_paginacao,
            "quantidade_por_pagina": quantidade_por_pagina
        }

        response = requests.post(
            URL,
            headers=headers,
            json=payload,
            timeout=(30, 120)
        )

        if response.status_code == 406:
            break

        if response.status_code != 200:
            print(f"❌ Erro {response.status_code}: {response.text}")
            break

        dados = response.json()
        lista = dados.get("veiculos", [])

        if not lista:
            break

        veiculos.extend(lista)
        inicio_paginacao += quantidade_por_pagina

    return veiculos

# ---------------- TRANSFORMAÇÃO ----------------
def transformar_em_dataframe(veiculos):
    linhas = []

    for v in veiculos:
        linha = {
            # --- CHAVES ---
            "codigo_veiculo": v.get("codigo_veiculo"),
            "codigo_associado": v.get("codigo_associado"),

            # 🔴 CAMPO CORRIGIDO
            "codigo_situacao_veiculo": (
                v.get("codigo_situacao_veiculo")
                or v.get("codigo_situacao")
                or v.get("situacao")
            ),

            # --- VEÍCULO ---
            "placa": v.get("placa"),
            "chassi": v.get("chassi"),
            "renavam": v.get("renavam"),
            "marca": v.get("marca"),
            "modelo": v.get("modelo"),
            "categoria": v.get("categoria"),
            "tipo": v.get("tipo"),
            "ano_fabricacao": v.get("ano_fabricacao"),
            "ano_modelo": v.get("ano_modelo"),

            # --- VALORES ---
            "valor_fipe": v.get("valor_fipe"),
            "valor_fipe_protegido": v.get("valor_fipe_protegido"),
            "valor_adesao": v.get("valor_adesao"),

            # --- DATAS ---
            "data_cadastro": v.get("data_cadastro"),
            "data_contrato": v.get("data_contrato"),
            "data_contrato_final": v.get("data_contrato_final"),

            # --- ORGANIZACIONAL ---
            "codigo_regional": v.get("codigo_regional"),
            "codigo_cooperativa": v.get("codigo_cooperativa"),
            "codigo_voluntario": v.get("codigo_voluntario"),
            "nome_voluntario": v.get("nome_voluntario"),

            # --- ASSOCIADO ---
            "nome_associado": v.get("nome_associado"),
            "cpf_associado": v.get("cpf_associado"),
        }

        linhas.append(linha)

    return pd.DataFrame(linhas)

# ---------------- EXECUÇÃO ----------------
codigos_situacao = [1]

todos_veiculos = []

for codigo in codigos_situacao:
    print(f"⏳ Coletando veículos da situação {codigo}...")
    veiculos = get_veiculos_por_situacao(codigo)
    print(f"✅ {len(veiculos)} veículos encontrados")
    todos_veiculos.extend(veiculos)

df = transformar_em_dataframe(todos_veiculos)

print(f"\n✅ Total geral de veículos coletados: {len(df)}")

# ---------------- LIMPEZA ----------------
if not df.empty:
    df = df.fillna("")
    df = df.astype(str)
    df = df.apply(
        lambda x: x.str.encode("utf-8", "ignore").str.decode("utf-8")
    )

    values_to_write = [df.columns.tolist()] + df.values.tolist()

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=SHEET_NAME,
        valueInputOption="RAW",
        body={"values": values_to_write}
    ).execute()

    print("✅ LISTAGEM_VEICULOS_SGA enviada ao Google Sheets.")
else:
    print("⚠️ Nenhum veículo encontrado.")

# %%
## POWER CRM - TIPO 1 CRIAÇÃO

import requests
import pandas as pd
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import time

# ---------------- CONFIGURAÇÃO GOOGLE SHEETS ----------------
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"  # JSON da conta de serviço
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo"
SHEET_NAME = "Dados de Criação CRM"  # aba da planilha

# Credenciais e serviço
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("sheets", "v4", credentials=creds)

# -------- CONFIGURAÇÃO --------
# Buscando o token de forma segura do GitHub Secrets
Token_CRM = os.environ.get('TOKEN_CRM')
URL_CRM = "https://api.powercrm.com.br/api/report/db"

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Bearer {Token_CRM}"
}

# -------- LOOP DE DATAS --------
start_date = datetime(2023, 1, 1)   # Data inicial
end_date = datetime.today()          # Data final = hoje
delta_days = 30                      # Intervalo de dias por requisição (ex.: 3 meses)

all_data = []

current_start = start_date
while current_start < end_date:
    current_end = min(current_start + timedelta(days=delta_days-1), end_date)  # Calcula o fim do bloco
    payload = {
        "from": current_start.strftime("%Y-%m-%d"),
        "to": current_end.strftime("%Y-%m-%d"),
        "stringFilterTypeDate": 1
    }

    response = requests.post(URL_CRM, headers=headers, json=payload)

    if response.status_code == 200:
        data = response.json()
        all_data.extend(data)  # Adiciona os dados do bloco
        print(f"✅ Dados de {payload['from']} a {payload['to']} coletados. Total acumulado: {len(all_data)}")
    else:
        print(f"❌ Erro na requisição {response.status_code} de {payload['from']} a {payload['to']}")
        print(response.text)

        time.sleep(3)

    # Próximo bloco
    current_start = current_end + timedelta(days=1)

# -------- TRANSFORMANDO EM DATAFRAME --------
df = pd.DataFrame(all_data)
print(f"\n✅ Total de registros coletados: {len(df)}")
df = pd.DataFrame(all_data)
print(df.head())

# ---------------- LIMPEZA DE CARACTERES ----------------
if not df.empty:
    df = df.fillna('')  # substitui NaN por string vazia
    df = df.astype(str)  # garante que tudo seja string
    df = df.apply(lambda x: x.str.encode('utf-8', 'ignore').str.decode('utf-8'))  # remove caracteres problemáticos

    # ---------------- ENVIO PARA GOOGLE SHEETS ----------------
    values_to_write = [df.columns.to_list()] + df.values.tolist()

    # Sobrescreve a aba com os novos dados (sem clear)
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=SHEET_NAME,
        valueInputOption="RAW",
        body={"values": values_to_write}
    ).execute()

    print("✅ Dados enviados para o Google Sheets com conta de serviço!")
else:
    print("⚠️ DataFrame vazio, nada enviado para o Google Sheets.")

# %%
#token_ContaAzul = "eyJraWQiOiJUa1BRbWs0UlR3M3RuWlZXcDdEanBURFhcL2RTajNvMU5SckI0R3I3ZzFTMD0iLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxYjBiZTlmMy0yNzcxLTRlYzAtODlhMy1iZjdmN2ZiZDE1YTEiLCJkZXZpY2Vfa2V5Ijoic2EtZWFzdC0xX2IxMjQwN2YzLTg3ZTYtNGMzYi1iYmI0LTEzYjk4YTU3ZTY5OSIsImlzcyI6Imh0dHBzOlwvXC9jb2duaXRvLWlkcC5zYS1lYXN0LTEuYW1hem9uYXdzLmNvbVwvc2EtZWFzdC0xX1ZwODNKMTF3QSIsImNsaWVudF9pZCI6IjM2bHNnaDhtY29tOGZkamtyc3RkdXJpMW9hIiwib3JpZ2luX2p0aSI6IjliNGVmZTg2LWFhMmQtNDAyYi04YzkyLTk3ZjMxNDkwNzRjMiIsImV2ZW50X2lkIjoiNjMyZDNiMzktZjM4Ny00YmQ3LWIyZWItNjgwNmZmMjU5ZjEzIiwidG9rZW5fdXNlIjoiYWNjZXNzIiwic2NvcGUiOiJhd3MuY29nbml0by5zaWduaW4udXNlci5hZG1pbiIsImF1dGhfdGltZSI6MTc3NjgwMzM0MywiZXhwIjoxNzc2ODA2OTQzLCJpYXQiOjE3NzY4MDMzNDMsImp0aSI6ImQxNDgxOTk1LWRkMDItNDNlOC05MjRjLWUzMTg5MmZjYWYwNCIsInVzZXJuYW1lIjoiYjg1NWZlY2ItYmJhYy00NmQzLWJkNTMtNGQ1MjE0NmRjOWNlQGRldnBvcnRhbC5jb20ifQ.bLXhrh9oTFEU9a9Kmz6FAYUx3SRacEtvQLDjdjaoCpQZcAfky2iDQrbKdHhapOwhYIpthHgF52EQdBCMZxfggN4WBMislZSVp1Gr_XxDrgaUqs3N-sVWUpdDBD6uYEjl9EeKRzAZLQjiWJRZ9Hc4JxJMGTlGWoAK8WdTYMmJ8WmTHaGhV0bd-vXqh_8grOjRKifP00sRZxT9Vu6Ci99RxnpMRJSaqKT7okh0G5VZYUXE4PxysxOIr-Rh6gFFYZ9G_4yfsxKTuRg1fnC8P2fqINUWdS2cbioKwGqfWJZggWK6goKPVXaKOH_kJFli_O_fkoFnF1KYKZf0iwXGbOiSMw"

#url_CA = "curl -i -X GET 'https://api-v2.contaazul.com/v1/categorias' -H 'Authorization: Bearer <ACCESS_TOKEN_GERADO>'"

#CLIENT_ID     = "3hm2fopnqpqpti90mt7vdqg2sl"
#CLIENT_SECRET = "1q8tjtfjk17qbfmg85e0mbser0ria3e2mv0vd4a2j96jk22oqkri"
#REDIRECT_URI  = "http://localhost:8080/callback"
#AUTH_URL      = "https://auth.contaazul.com/oauth2/auth"
#TOKEN_URL     = "https://auth.contaazul.com/oauth2/token"


#1697c9e3-6d91-4862-8e66-e11d45f24a86


