# === 5️⃣ TRATAR RETORNO ===

if resposta.status_code == 200:
    dados = resposta.json()
    token_usuario = dados.get("token_usuario") or dados.get("token_usuário")

    if token_usuario:
        print(
            f"✅ Autenticação bem-sucedida! "
            f"Token obtido ({len(token_usuario)} caracteres)."
        )
    else:
        print("❌ Autenticação retornou 200, mas nenhum token foi encontrado.")
        print("Resposta da API:", resposta.text)
        raise SystemExit(1)

else:
    print(f"❌ Erro {resposta.status_code} na autenticação.")
    print("Resposta da API:", resposta.text)
    raise SystemExit(1)
