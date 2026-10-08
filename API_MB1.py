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
# 0. CONFIGURAÇÕES GERAIS
# ============================================================
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1og7UWrfw0kJ2ju53gtP44F3X97q5vLIiQh2GPpLz_Xo")
SERVICE_ACCOUNT_FILE = "teste-477018-5cb1426a435b.json"

DATA_INICIO_HISTORICO = "01/01/2023"
JANELA_DIAS = int(os.environ.get("JANELA_DIAS", "30"))              # tamanho de cada janela de busca
DIAS_INCREMENTAL = int(os.environ.get("DIAS_INCREMENTAL", "90"))    # quantos dias reprocessar no modo incremental
MODO_EVENTOS = os.environ.get("MODO_EVENTOS", "incremental").lower()  # "incremental" ou "completo"
PAUSA_ENTRE_REQUISICOES = 1.0
TAMANHO_LOTE_SHEETS = 2000

headers_sga = {}  # preenchido após obter o token


# ============================================================
# 1. REQUISIÇÃO PROTEGIDA PARA A API HINOVA
# ============================================================
def hinova_request(method, url, **kwargs):
    """Faz a chamada à Hinova. Se o token estiver bloqueado, ENCERRA o script na hora."""
    kwargs.setdefault("timeout", (30, 120))
    r = None
    for tentativa in range(1, 4):
        try:
            r = requests.request(method, url, headers=headers_sga, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as e:
            print(f"⚠️ Erro de rede (tentativa {tentativa}/3): {e}")
            time.sleep(10 * tentativa)
            continue

        if r.status_code == 403 and "BLOQUEADO" in r.text.upper():
            raise SystemExit(
                "❌ Token BLOQUEADO pela Hinova. Execução interrompida para não piorar o bloqueio. "
                "Aguarde ~1h antes de rodar novamente."
            )
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"⚠️ HTTP {r.status_code} (tentativa {tentativa}/3). Aguardando...")
            time.sleep(10 * tentativa)
            continue
        return r

    if r is None:
        raise RuntimeError(f"Sem resposta da API após 3 tentativas: {url}")
    return r


# ============================================================
# 2. FUNÇÕES DO GOOGLE SHEETS
# ============================================================
def _a1(sheet_name, cell=None):
    nome = f"'{sheet_name}'"
    return f"{nome}!{cell}" if cell else nome


def ler_aba_como_df(service, spreadsheet_id, sheet_name):
    """Lê a aba inteira como DataFrame de strings. Retorna None se vazia ou com erro."""
    try:
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=_a1(sheet_name)
        ).execute()
    except Exception as e:
        print(f"⚠️ Não foi possível ler a aba '{sheet_name}': {e}")
        return None

    valores = res.get("values", [])
    if len(valores) < 2:
        return None

    cab = valores[0]
    n = len(cab)
    linhas = [(l + [""] * (n - len(l)))[:n] for l in valores[1:]]
    return pd.DataFrame(linhas, columns=cab)


def enviar_para_sheets_em_lotes(service, spreadsheet_id, sheet_name, df, tamanho_lote=TAMANHO_LOTE_SHEETS):
    if df.empty:
        print(f"⚠️ DataFrame vazio para a aba '{sheet_name}'. Nada enviado (aba preservada).")
        return

    df = df.fillna("")
    df = df.astype(str)
    df = df.apply(lambda x: x.str.encode("utf-8", "ignore").str.decode("utf-8"))

    print(f"🧹 Limpando aba '{sheet_name}'...")
    for tentativa in range(1, 4):
        try:
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=_a1(sheet_name)
            ).execute()
            print("✅ Aba limpa com sucesso.")
            break
        except Exception as e:
            print(f"⚠️ Erro ao limpar aba (tentativa {tentativa}/3): {e}")
            if tentativa == 3:
                raise Exception(f"❌ Não foi possível limpar a aba '{sheet_name}'.")
            time.sleep(5)

    dados = [df.columns.tolist()] + df.values.tolist()
    total_lotes = math.ceil(len(dados) / tamanho_lote)

    print(f"📊 Total de linhas: {len(dados)} | Total de lotes: {total_lotes}")

    for i in range(0, len(dados), tamanho_lote):
        lote = dados[i:i + tamanho_lote]
        linha_inicial = i + 1
        numero_lote = (i // tamanho_lote) + 1

        for tentativa in range(1, 6):
            try:
                print(f"📤 Enviando lote {numero_lote}/{total_lotes} - linhas {linha_inicial} até {linha_inicial + len(lote) - 1}")
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=_a1(sheet_name, f"A{linha_inicial}"),
                    valueInputOption="RAW",
                    body={"values": lote}
                ).execute()
                print(f"✅ Lote {numero_lote}/{total_lotes} enviado.")
                break
            except Exception as e:
                print(f"⚠️ Erro no lote {numero_lote}: {e}")
                if tentativa == 5:
                    raise Exception(f"❌ Falha ao enviar lote {numero_lote}: {e}")
                time.sleep(10 * tentativa)
        time.sleep(1)  # respeita a cota de escrita do Sheets

    print(f"✅ Envio para a aba '{sheet_name}' concluído com sucesso.\n")


# ============================================================
# 3. AUTENTICAÇÃO
# ============================================================
def obter_token_usuario():
    """Prioriza o secret TOKEN_USUARIO (não expira). Só autentica se ele não existir."""
    token = os.environ.get("TOKEN_USUARIO")
    if token:
        print("🔐 Usando TOKEN_USUARIO do ambiente (sem chamada de autenticação).")
        return token

    print("⚠️ TOKEN_USUARIO ausente. Autenticando UMA vez como fallback...")
    token_sga = os.environ.get("TOKEN_SGA")
    usuario = os.environ.get("USUARIO_API")
    senha = os.environ.get("SENHA_API")
    if not all([token_sga, usuario, senha]):
        raise SystemExit("❌ Defina TOKEN_USUARIO, ou TOKEN_SGA + USUARIO_API + SENHA_API.")

    res = requests.post(
        "https://api.hinova.com.br/api/sga/v2/usuario/autenticar",
        headers={"Authorization": f"Bearer {token_sga}", "Content-Type": "application/json"},
        json={"usuario": usuario, "senha": senha},
        timeout=30
    )
    if res.status_code != 200:
        print(f"❌ Erro {res.status_code} na autenticação:\n{res.text}")
        raise SystemExit(1)

    dados = res.json()
    token = dados.get("token_usuario") or dados.get("token_usuário")
    if not token:
        print("❌ Token de usuário não retornado pela API.")
        print("Resposta recebida:", res.text)
        raise SystemExit(1)

    print("✅ Autenticação realizada. Salve este token como secret TOKEN_USUARIO para não autenticar mais.")
    return token


print("🔎 Iniciando...")
TOKEN_USUARIO = obter_token_usuario()
TOKEN_CRM = os.environ.get("TOKEN_CRM")

headers_sga = {
    "Authorization": f"Bearer {TOKEN_USUARIO}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if os.path.exists(SERVICE_ACCOUNT_FILE):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
else:
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not google_creds_json:
        raise SystemExit("❌ Credenciais do Google não encontradas.")
    info = json.loads(google_creds_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)

service = build("sheets", "v4", credentials=creds)

falhas = []


# ============================================================
# ROTINA 1: EVENTOS SGA (INCREMENTAL)
# ============================================================
def sub(d, chave):
    """Retorna o sub-dicionário com segurança (a API pode devolver null)."""
    v = d.get(chave)
    return v if isinstance(v, dict) else {}


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

        response = hinova_request("POST", url, json=payload)

        if response.status_code == 406:  # sem registros no período
            break
        if response.status_code != 200:
            # NÃO engolir o erro: abortar evita sobrescrever a planilha com dados parciais
            raise RuntimeError(f"Erro {response.status_code} ao buscar eventos "
                               f"({data_inicio} a {data_fim}): {response.text}")

        dados = response.json()
        if not isinstance(dados, list) or len(dados) == 0:
            break

        eventos.extend(dados)

        if len(dados) < quantidade_por_pagina:  # última página: evita requisição extra
            break

        inicio_paginacao += quantidade_por_pagina
        time.sleep(PAUSA_ENTRE_REQUISICOES)

    return eventos


def transformar_eventos_df(eventos):
    linhas = []
    for e in eventos:
        assoc = sub(e, "associado")
        veic = sub(e, "veiculo")
        cond = sub(e, "condutor")
        reg = sub(e, "regional")
        coop = sub(e, "cooperativa")
        vol = sub(e, "voluntario")
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
            "associado_nome": assoc.get("nome"),
            "associado_cpf": assoc.get("cpf"),
            "associado_email": assoc.get("email"),
            "associado_telefone": assoc.get("telefone"),
            "veiculo_placa": veic.get("placa"),
            "veiculo_modelo": veic.get("modelo"),
            "veiculo_marca": veic.get("marca"),
            "veiculo_ano_modelo": veic.get("ano_modelo"),
            "veiculo_ano_fabricacao": veic.get("ano_fabricacao"),
            "veiculo_valor_fipe": veic.get("valor_fipe"),
            "condutor_nome": cond.get("nome"),
            "condutor_cpf": cond.get("cpf"),
            "condutor_cidade": cond.get("cidade"),
            "condutor_estado": cond.get("estado"),
            "regional": reg.get("descricao"),
            "cooperativa": coop.get("descricao"),
            "voluntario": vol.get("descricao")
        }
        linhas.append(linha)
    return pd.DataFrame(linhas)


def coletar_eventos_periodo(data_inicio_str):
    data_inicio = datetime.strptime(data_inicio_str, "%d/%m/%Y")
    data_fim = datetime.today()
    all_eventos = []
    current_start = data_inicio

    while current_start <= data_fim:
        current_end = min(current_start + timedelta(days=JANELA_DIAS - 1), data_fim)
        print(f"⏳ Buscando eventos de {current_start.strftime('%d/%m/%Y')} até {current_end.strftime('%d/%m/%Y')}...")
        bloco = get_eventos(current_start.strftime("%d/%m/%Y"), current_end.strftime("%d/%m/%Y"))
        all_eventos.extend(bloco)
        current_start = current_end + timedelta(days=1)
        time.sleep(PAUSA_ENTRE_REQUISICOES)

    return all_eventos


def rotina_eventos():
    print("\n============================================================")
    print("🚀 ROTINA 1: EVENTOS SGA")
    print("============================================================")
    aba = "EVENTOS SGA - LISTAR"

    existente = None
    if MODO_EVENTOS == "incremental":
        existente = ler_aba_como_df(service, SPREADSHEET_ID, aba)
        if existente is not None and "codigo_evento" not in existente.columns:
            existente = None

    if existente is not None:
        data_inicio = (datetime.today() - timedelta(days=DIAS_INCREMENTAL)).strftime("%d/%m/%Y")
        print(f"♻️ Modo INCREMENTAL: {len(existente)} linhas na aba. Buscando desde {data_inicio}.")
    else:
        data_inicio = DATA_INICIO_HISTORICO
        print(f"📚 Modo COMPLETO: buscando desde {data_inicio}.")

    eventos = coletar_eventos_periodo(data_inicio)
    df_novo = transformar_eventos_df(eventos)
    print(f"✅ Eventos coletados nesta execução: {len(df_novo)}")

    if df_novo.empty:
        print("⚠️ Nenhum evento retornado. Aba preservada sem alterações.")
        return

    if existente is not None:
        df_novo_str = df_novo.fillna("").astype(str)
        existente = existente.reindex(columns=df_novo_str.columns, fill_value="")
        df_final = pd.concat([existente, df_novo_str], ignore_index=True)
        df_final = df_final.drop_duplicates(subset="codigo_evento", keep="last")
        print(f"🔀 Total após mesclar: {len(df_final)} linhas.")
    else:
        df_final = df_novo

    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, aba, df_final)


# ============================================================
# ROTINA 2: DIMENSÃO SITUAÇÃO (SGA)
# ============================================================
def rotina_situacao():
    print("\n============================================================")
    print("🚀 ROTINA 2: DIM_SITUACAO")
    print("============================================================")

    res = hinova_request("GET", "https://api.hinova.com.br/api/sga/v2/listar/situacao/todos", timeout=30)
    if res.status_code != 200:
        raise RuntimeError(f"Erro {res.status_code} ao buscar situações: {res.text}")

    dados = res.json()
    if isinstance(dados, dict):
        dados = [dados]
    df = pd.DataFrame(dados)
    if not df.empty and "codigo_situacao" in df.columns:
        df = df.sort_values("codigo_situacao")
    print(f"✅ Total de situações coletadas: {len(df)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "DIM_SITUACAO", df)


# ============================================================
# ROTINA 3: VOLUNTÁRIOS ATIVOS (SGA)
# ============================================================
def get_voluntarios():
    url_voluntario = "https://api.hinova.com.br/api/sga/v2/listar/voluntario/ativo"
    voluntarios = []
    pagina = 0
    registros_por_pagina = 5000

    while True:
        res = hinova_request("GET", f"{url_voluntario}?pagina={pagina}", timeout=30)
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
        time.sleep(PAUSA_ENTRE_REQUISICOES)

    return voluntarios


def transformar_voluntarios_df(voluntarios):
    linhas = []
    for v in voluntarios:
        cooperativas = ", ".join(
            [(c.get("nome_cooperativa") or "") for c in (v.get("cooperativas") or []) if isinstance(c, dict)]
        )
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


def rotina_voluntarios():
    print("\n============================================================")
    print("🚀 ROTINA 3: VOLUNTÁRIOS SGA")
    print("============================================================")
    df = transformar_voluntarios_df(get_voluntarios())
    print(f"✅ Total de voluntários: {len(df)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "Voluntarios SGA", df)


# ============================================================
# ROTINA 4: SITUAÇÃO DE EVENTO ATIVOS (SGA)
# ============================================================
def rotina_situacao_evento():
    print("\n============================================================")
    print("🚀 ROTINA 4: SITUAÇÃO DE EVENTO ATIVOS")
    print("============================================================")

    res = hinova_request("GET", "https://api.hinova.com.br/api/sga/v2/situacao-evento/listar/ativo", timeout=30)
    if res.status_code != 200:
        raise RuntimeError(f"Erro {res.status_code}: {res.text}")

    df = pd.DataFrame(res.json())
    print(f"✅ Registros encontrados: {len(df)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "SITUAÇÃO DE EVENTO ATIVOS SGA", df)


# ============================================================
# ROTINA 5: POWER CRM (DADOS DE CRIAÇÃO)
# ============================================================
def rotina_crm():
    print("\n============================================================")
    print("🚀 ROTINA 5: POWER CRM - CRIAÇÃO")
    print("============================================================")

    if not TOKEN_CRM:
        print("⚠️ TOKEN_CRM ausente. Pulando extração do Power CRM.")
        return

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

        ok = False
        for tentativa in range(1, 4):
            res_crm = requests.post(url_crm, headers=headers_crm, json=payload_crm, timeout=60)
            if res_crm.status_code == 200:
                data = res_crm.json()
                if isinstance(data, list):
                    all_crm_data.extend(data)
                print(f"✅ CRM ({payload_crm['from']} a {payload_crm['to']}): {len(all_crm_data)} acumulados")
                ok = True
                break
            print(f"⚠️ Erro {res_crm.status_code} no CRM (tentativa {tentativa}/3): {res_crm.text[:200]}")
            time.sleep(5 * tentativa)

        if not ok:
            # aborta para não sobrescrever a aba com dados incompletos
            raise RuntimeError(f"Falha no CRM na janela {payload_crm['from']} a {payload_crm['to']}")

        current_start = current_end + timedelta(days=1)
        time.sleep(0.5)

    df_crm = pd.DataFrame(all_crm_data)
    print(f"✅ Total de registros CRM: {len(df_crm)}")
    enviar_para_sheets_em_lotes(service, SPREADSHEET_ID, "Dados de Criação CRM", df_crm)


# ============================================================
# EXECUÇÃO
# ============================================================
rotinas = [
    ("Eventos SGA", rotina_eventos),
    ("DIM_SITUACAO", rotina_situacao),
    ("Voluntários SGA", rotina_voluntarios),
    ("Situação de Evento", rotina_situacao_evento),
    ("Power CRM", rotina_crm),
]

for nome, func in rotinas:
    try:
        func()
    except Exception as e:  # SystemExit (token bloqueado) NÃO é capturado aqui, de propósito
        print(f"❌ Rotina '{nome}' falhou: {e}")
        falhas.append(nome)

if falhas:
    print(f"\n⚠️ Finalizado com falhas em: {', '.join(falhas)}")
    raise SystemExit(1)

print("\n🎉 Todas as rotinas foram executadas com sucesso!")
