from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _weight_error(quantities: pd.Series, prices: pd.Series, target_weights: pd.Series) -> float:
    values = quantities * prices
    total = float(values.sum())
    if total <= 0:
        return float(target_weights.abs().sum())
    weights = values / total
    return float((weights - target_weights).abs().sum())


def optimize_integer_targets(
    target_df: pd.DataFrame,
    adjusted_equity: float,
) -> pd.Series:
    if adjusted_equity <= 0 or target_df.empty:
        return pd.Series(dtype=int)

    target_df = target_df.copy()
    target_df["quantidade_meta_bruta"] = target_df["valor_meta"] / target_df["preco"]
    quantities = np.floor(target_df["quantidade_meta_bruta"]).astype(int)
    prices = target_df["preco"].astype(float)
    target_weights = target_df["peso_meta"].astype(float)
    residual_cash = adjusted_equity - float((quantities * prices).sum())

    min_price = float(prices.min()) if not prices.empty else math.inf
    current_error = _weight_error(quantities, prices, target_weights)
    max_iterations = 10000
    iterations = 0

    while residual_cash + 1e-9 >= min_price and iterations < max_iterations:
        best_idx = None
        best_error = current_error

        affordable = target_df.index[prices <= residual_cash + 1e-9]
        for idx in affordable:
            candidate = quantities.copy()
            candidate.loc[idx] += 1
            candidate_error = _weight_error(candidate, prices, target_weights)
            if candidate_error < best_error - 1e-10:
                best_error = candidate_error
                best_idx = idx

        if best_idx is None:
            break

        quantities.loc[best_idx] += 1
        residual_cash -= float(prices.loc[best_idx])
        current_error = best_error
        iterations += 1

    return quantities.astype(int)


def calculate_rebalance(
    carteira_origem: pd.DataFrame,
    carteira_destino: pd.DataFrame,
    precos: pd.DataFrame,
    aporte: float = 0.0,
    retirada: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, float]]:
    origem_columns = ["ticker", "quantidade"]
    if "preco_medio" in carteira_origem.columns:
        origem_columns.append("preco_medio")
    if "valor_financeiro" in carteira_origem.columns:
        origem_columns.append("valor_financeiro")

    origem = carteira_origem[origem_columns].copy()
    destino = carteira_destino[["ticker", "peso"]].copy()
    price_df = precos[["ticker", "preco"]].copy()

    universe = sorted(set(origem["ticker"]) | set(destino["ticker"]))
    base = pd.DataFrame({"ticker": universe})
    base = base.merge(origem, on="ticker", how="left")
    base = base.merge(destino.rename(columns={"peso": "peso_meta"}), on="ticker", how="left")
    base = base.merge(price_df, on="ticker", how="left")

    base["quantidade_atual"] = base["quantidade"].fillna(0).astype(int)
    base["peso_meta"] = base["peso_meta"].fillna(0.0).astype(float)
    base["preco"] = base["preco"].astype(float)
    if "valor_financeiro" in base.columns:
        base["valor_atual"] = np.where(
            base["valor_financeiro"].notna(),
            base["valor_financeiro"].astype(float),
            base["quantidade_atual"] * base["preco"],
        )
    else:
        base["valor_atual"] = base["quantidade_atual"] * base["preco"]

    valor_total_atual = float(base["valor_atual"].sum())
    patrimonio_ajustado = valor_total_atual + float(aporte) - float(retirada)
    base["peso_atual"] = np.where(valor_total_atual > 0, base["valor_atual"] / valor_total_atual, 0.0)
    base["valor_meta"] = base["peso_meta"] * patrimonio_ajustado
    base["quantidade_meta"] = 0

    target_mask = base["peso_meta"] > 0
    target_df = base.loc[target_mask, ["ticker", "peso_meta", "valor_meta", "preco"]].copy()
    if not target_df.empty:
        optimized = optimize_integer_targets(target_df.set_index("ticker"), patrimonio_ajustado)
        base.loc[target_mask, "quantidade_meta"] = base.loc[target_mask, "ticker"].map(optimized).fillna(0).astype(int)

    base["quantidade_meta"] = base["quantidade_meta"].astype(int)
    base["valor_pos_rebalanceamento"] = base["quantidade_meta"] * base["preco"]
    total_pos = float(base["valor_pos_rebalanceamento"].sum())
    base["peso_pos_rebalanceamento"] = np.where(total_pos > 0, base["valor_pos_rebalanceamento"] / total_pos, 0.0)
    base["diferenca_qtd"] = base["quantidade_meta"] - base["quantidade_atual"]
    base["lado"] = np.select(
        [base["diferenca_qtd"] > 0, base["diferenca_qtd"] < 0],
        ["COMPRA", "VENDA"],
        default="",
    )
    base["quantidade_ordem"] = base["diferenca_qtd"].abs().astype(int)
    base["financeiro_ordem"] = base["quantidade_ordem"] * base["preco"]

    detail_columns = [
        "ticker",
        "quantidade_atual",
        "preco",
        "preco_medio",
        "valor_atual",
        "peso_atual",
        "peso_meta",
        "valor_meta",
        "quantidade_meta",
        "valor_pos_rebalanceamento",
        "peso_pos_rebalanceamento",
        "diferenca_qtd",
        "lado",
        "quantidade_ordem",
        "financeiro_ordem",
    ]

    summary = {
        "valor_total_carteira_atual": valor_total_atual,
        "patrimonio_ajustado": patrimonio_ajustado,
        "valor_pos_rebalanceamento": total_pos,
        "caixa_estimado": patrimonio_ajustado - total_pos,
    }
    if "preco_medio" not in base.columns:
        base["preco_medio"] = np.nan

    return base[detail_columns].sort_values("ticker").reset_index(drop=True), summary


def build_orders_table(detail: pd.DataFrame, cliente: str, sort_mode: str = "Compras depois vendas") -> pd.DataFrame:
    orders = detail[detail["quantidade_ordem"] > 0].copy()
    if orders.empty:
        return pd.DataFrame(columns=["ATIVO", "LADO", "QTDD", "PREÇO", "CLIENTE"])

    side_order = {"COMPRA": 0, "VENDA": 1}
    if sort_mode == "Vendas depois compras":
        side_order = {"VENDA": 0, "COMPRA": 1}
    orders["_ordem_lado"] = orders["lado"].map(side_order).fillna(99)
    orders = orders.sort_values(["_ordem_lado", "ticker"])

    return pd.DataFrame(
        {
            "ATIVO": orders["ticker"],
            "LADO": orders["lado"],
            "QTDD": orders["quantidade_ordem"].astype(int),
            "PREÇO": "A MERCADO",
            "CLIENTE": str(cliente).strip(),
        }
    ).reset_index(drop=True)
