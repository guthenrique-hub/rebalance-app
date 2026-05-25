from __future__ import annotations

import unicodedata

import pandas as pd


def normalize_ticker(value: object) -> str:
    return str(value).strip().upper()


def canonical_column(value: object) -> str:
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.replace("\n", " ").split())


def parse_localized_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    text = text.replace("R$", "").replace("%", "").replace(" ", "")

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def standardize_origin_columns(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    canonical_map = {canonical_column(column): column for column in data.columns}

    model_candidates = {
        "ativo": "ticker",
        "qtd. total": "quantidade",
        "qtd total": "quantidade",
        "preco medio": "preco_medio",
        "posicao": "valor_financeiro",
    }
    rename_map = {}
    for source, target in model_candidates.items():
        if source in canonical_map:
            rename_map[canonical_map[source]] = target

    if {"ticker", "quantidade"}.issubset(rename_map.values()):
        return data.rename(columns=rename_map)

    if {"ticker", "quantidade"}.issubset(canonical_map):
        rename_map = {
            canonical_map["ticker"]: "ticker",
            canonical_map["quantidade"]: "quantidade",
        }
        if "valor_financeiro" in canonical_map:
            rename_map[canonical_map["valor_financeiro"]] = "valor_financeiro"
        return data.rename(columns=rename_map)

    return data.rename(columns=rename_map)


def normalize_origin(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "quantidade", "valor_financeiro"]), ["Carteira origem não pode estar vazia."]

    data = standardize_origin_columns(df)
    data.columns = [str(c).strip().lower() for c in data.columns]
    if not {"ticker", "quantidade"}.issubset(data.columns):
        return pd.DataFrame(columns=["ticker", "quantidade", "valor_financeiro"]), [
            "Carteira origem deve conter as colunas ticker e quantidade, ou o modelo com Ativo na coluna A e Qtd. Total na coluna H."
        ]

    keep_columns = ["ticker", "quantidade"]
    if "preco_medio" in data.columns:
        keep_columns.append("preco_medio")
    if "valor_financeiro" in data.columns:
        keep_columns.append("valor_financeiro")

    data = data[keep_columns].copy()
    data["ticker"] = data["ticker"].map(normalize_ticker)
    data = data[data["ticker"] != ""]
    data["quantidade"] = data["quantidade"].map(parse_localized_number)

    if data["quantidade"].isna().any():
        errors.append("Carteira origem contém quantidades vazias ou inválidas.")
    if (data["quantidade"].dropna() < 0).any():
        errors.append("Carteira origem não pode conter quantidade negativa.")
    if not (data["quantidade"].dropna() % 1 == 0).all():
        errors.append("Carteira origem deve conter apenas quantidades inteiras.")

    data = data.dropna(subset=["quantidade"])
    data["quantidade"] = data["quantidade"].astype(int)

    if "preco_medio" in data.columns:
        data["preco_medio"] = data["preco_medio"].map(parse_localized_number)
        if (data["preco_medio"].dropna() < 0).any():
            errors.append("Preço médio da carteira origem não pode ser negativo.")

    if "valor_financeiro" in data.columns:
        data["valor_financeiro"] = data["valor_financeiro"].map(parse_localized_number)
        if (data["valor_financeiro"].dropna() < 0).any():
            errors.append("Valor financeiro da carteira origem não pode ser negativo.")

    grouped_rows = []
    for ticker, group in data.groupby("ticker", sort=True):
        total_quantity = int(group["quantidade"].sum())
        row = {"ticker": ticker, "quantidade": total_quantity}

        if "preco_medio" in group.columns:
            valid_cost = group.dropna(subset=["preco_medio"])
            if not valid_cost.empty and valid_cost["quantidade"].sum() > 0:
                row["preco_medio"] = float((valid_cost["preco_medio"] * valid_cost["quantidade"]).sum() / valid_cost["quantidade"].sum())
            else:
                row["preco_medio"] = pd.NA

        if "valor_financeiro" in group.columns:
            row["valor_financeiro"] = group["valor_financeiro"].sum(min_count=1)

        grouped_rows.append(row)

    data = pd.DataFrame(grouped_rows)
    if data.empty:
        errors.append("Carteira origem não pode estar vazia.")
    return data, errors


def normalize_weight(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", ".")
    try:
        if text.endswith("%"):
            return float(text[:-1].strip()) / 100
        number = float(text)
        return number / 100 if number > 1 else number
    except ValueError:
        return None


def normalize_target(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    errors: list[str] = []
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "peso"]), ["Carteira destino não pode estar vazia."]

    data = df.copy()
    data.columns = [str(c).strip().lower() for c in data.columns]
    if not {"ticker", "peso"}.issubset(data.columns):
        return pd.DataFrame(columns=["ticker", "peso"]), ["Carteira destino deve conter as colunas ticker e peso."]

    data = data[["ticker", "peso"]].copy()
    data["ticker"] = data["ticker"].map(normalize_ticker)
    if (data["ticker"] == "").any():
        errors.append("Carteira destino não pode conter ticker vazio.")

    data = data[data["ticker"] != ""]
    data["peso"] = data["peso"].map(normalize_weight)

    if data["peso"].isna().any():
        errors.append("Carteira destino contém pesos vazios ou inválidos.")
    if (data["peso"].dropna() < 0).any():
        errors.append("Carteira destino não pode conter peso negativo.")

    data = data.dropna(subset=["peso"])
    data = data.groupby("ticker", as_index=False)["peso"].sum()
    total_weight = float(data["peso"].sum()) if not data.empty else 0.0
    if abs(total_weight - 1.0) > 0.0001:
        errors.append(f"A soma dos pesos da carteira destino deve ser 100%. Soma atual: {total_weight:.2%}.")
    if data.empty:
        errors.append("Carteira destino não pode estar vazia.")
    return data, errors


def validate_prices(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if df is None or df.empty:
        return ["Tabela de preços não pode estar vazia."]
    required = {"ticker", "preco"}
    if not required.issubset(df.columns):
        return ["Tabela de preços deve conter as colunas ticker e preco."]

    prices = pd.to_numeric(df["preco"], errors="coerce")
    invalid = df.loc[prices.isna() | (prices <= 0), "ticker"].astype(str).tolist()
    if invalid:
        errors.append("Preços devem ser maiores que zero para: " + ", ".join(invalid))
    return errors


def validate_run_inputs(
    nome_cliente: str,
    conta_cliente: str,
    patrimonio_ajustado: float,
) -> list[str]:
    errors: list[str] = []
    if not str(nome_cliente).strip():
        errors.append("Nome do cliente deve ser preenchido.")
    if not str(conta_cliente).strip():
        errors.append("Código/conta do cliente deve ser preenchido.")
    if patrimonio_ajustado <= 0:
        errors.append("Patrimônio ajustado deve ser maior que zero.")
    return errors
