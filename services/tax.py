from __future__ import annotations

import numpy as np
import pandas as pd


FISCAL_NOTICE = (
    "Estimativa fiscal meramente informativa. O cálculo de IR/DARF depende do histórico completo de operações "
    "do cliente no mês, compensações acumuladas, tipo de ativo, day trade, custos operacionais, IRRF e demais "
    "regras fiscais aplicáveis. Validar com contador ou responsável fiscal antes do recolhimento."
)


def _is_probably_common_stock(ticker: str) -> bool:
    clean = str(ticker).strip().upper()
    if clean.endswith(("34", "35")):
        return False
    if clean.endswith("11"):
        return False
    return True


def calculate_tax_estimate(
    rebalance_detail: pd.DataFrame,
    vendas_ja_realizadas_mes: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, float | str]]:
    sales = rebalance_detail[
        (rebalance_detail["lado"] == "VENDA") & (rebalance_detail["quantidade_ordem"] > 0)
    ].copy()

    columns = [
        "ativo",
        "quantidade_vendida",
        "preco_medio",
        "preco_venda_estimado",
        "valor_venda",
        "custo_medio_vendido",
        "lucro_prejuizo",
        "resultado",
        "ir_estimado",
        "prejuizo_compensavel",
        "observacao",
    ]

    if sales.empty:
        empty = pd.DataFrame(columns=columns)
        summary = {
            "vendas_ja_realizadas_mes": float(vendas_ja_realizadas_mes),
            "vendas_rebalanceamento": 0.0,
            "total_vendas_mes": float(vendas_ja_realizadas_mes),
            "lucro_total": 0.0,
            "prejuizo_total": 0.0,
            "lucro_liquido": 0.0,
            "ir_estimado_total": 0.0,
            "prejuizo_compensavel": 0.0,
            "observacao": "Sem vendas geradas pelo rebalanceamento.",
        }
        return empty, summary

    sales["ativo"] = sales["ticker"]
    sales["quantidade_vendida"] = sales["quantidade_ordem"].astype(int)
    sales["preco_venda_estimado"] = sales["preco"].astype(float)
    sales["preco_medio"] = pd.to_numeric(sales.get("preco_medio"), errors="coerce")
    sales["valor_venda"] = sales["quantidade_vendida"] * sales["preco_venda_estimado"]
    vendas_rebalanceamento = float(sales["valor_venda"].sum())
    total_vendas_mes = float(vendas_ja_realizadas_mes) + vendas_rebalanceamento
    isento_20k = total_vendas_mes <= 20000

    sales["custo_medio_vendido"] = sales["quantidade_vendida"] * sales["preco_medio"]
    sales["lucro_prejuizo"] = sales["valor_venda"] - sales["custo_medio_vendido"]
    sales["resultado"] = np.select(
        [sales["lucro_prejuizo"] > 0, sales["lucro_prejuizo"] < 0, sales["lucro_prejuizo"] == 0],
        ["LUCRO", "PREJUÍZO", "NEUTRO"],
        default="SEM PREÇO MÉDIO",
    )
    sales["prejuizo_compensavel"] = np.where(sales["lucro_prejuizo"] < 0, sales["lucro_prejuizo"].abs(), 0.0)
    sales["ir_estimado"] = np.where((~isento_20k) & (sales["lucro_prejuizo"] > 0), sales["lucro_prejuizo"] * 0.15, 0.0)

    sales["observacao"] = ""
    if isento_20k:
        sales["observacao"] = "Potencialmente isento pela regra de vendas até R$ 20.000 no mês"
    sales.loc[sales["preco_medio"].isna(), "observacao"] = "Preço médio ausente; IR não estimado para este ativo"
    excluded_mask = ~sales["ativo"].map(_is_probably_common_stock)
    sales.loc[excluded_mask, ["ir_estimado", "prejuizo_compensavel"]] = 0.0
    sales.loc[excluded_mask, "observacao"] = "Não estimado automaticamente: pode ser FII, ETF, BDR, unit ou outro ativo fora da regra de ações comuns"

    taxable_sales = sales[(sales["preco_medio"].notna()) & (~excluded_mask)].copy()
    lucro_total = float(taxable_sales.loc[taxable_sales["lucro_prejuizo"] > 0, "lucro_prejuizo"].sum())
    prejuizo_total = float(taxable_sales.loc[taxable_sales["lucro_prejuizo"] < 0, "lucro_prejuizo"].abs().sum())
    lucro_liquido = lucro_total - prejuizo_total
    ir_estimado_total = lucro_liquido * 0.15 if total_vendas_mes > 20000 and lucro_liquido > 0 else 0.0
    prejuizo_compensavel_total = abs(lucro_liquido) if lucro_liquido < 0 else 0.0

    summary = {
        "vendas_ja_realizadas_mes": float(vendas_ja_realizadas_mes),
        "vendas_rebalanceamento": vendas_rebalanceamento,
        "total_vendas_mes": total_vendas_mes,
        "lucro_total": lucro_total,
        "prejuizo_total": prejuizo_total,
        "lucro_liquido": lucro_liquido,
        "ir_estimado_total": ir_estimado_total,
        "prejuizo_compensavel": prejuizo_compensavel_total,
        "observacao": "Estimativa restrita a operações comuns de ações; ativos com final 11, 34 ou 35 foram destacados como fora do cálculo automático.",
    }

    return sales[columns].reset_index(drop=True), summary
