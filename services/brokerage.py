from __future__ import annotations

import pandas as pd


def calculate_brokerage(orders_detail: pd.DataFrame) -> dict[str, float]:
    if orders_detail.empty:
        total_compras = 0.0
        total_vendas = 0.0
    else:
        compras = orders_detail[orders_detail["lado"] == "COMPRA"]
        vendas = orders_detail[orders_detail["lado"] == "VENDA"]
        total_compras = float(compras["financeiro_ordem"].sum())
        total_vendas = float(vendas["financeiro_ordem"].sum())

    movimentacao_total = abs(total_compras) + abs(total_vendas)
    corretagem = movimentacao_total * 0.005
    custos_adicionais = movimentacao_total * 0.002
    custo_total = corretagem + custos_adicionais

    return {
        "total_compras": total_compras,
        "total_vendas": total_vendas,
        "movimentacao_total": movimentacao_total,
        "corretagem": corretagem,
        "custos_adicionais": custos_adicionais,
        "custo_total": custo_total,
    }
