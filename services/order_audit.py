from __future__ import annotations

import math

import numpy as np
import pandas as pd

from services.brokerage import calculate_brokerage


AUDIT_DISCLAIMER = (
    "A auditoria é uma camada de segurança operacional, mas não substitui conferência humana. "
    "Antes da execução, valide preços, quantidades, caixa disponível, limites operacionais, "
    "regras fiscais e suitability do cliente."
)

STATUS_APPROVED = "APROVADO"
STATUS_ALERT = "ALERTA"
STATUS_CRITICAL = "ERRO CRÍTICO"


def _orders_detail(detail: pd.DataFrame) -> pd.DataFrame:
    return detail[detail["quantidade_ordem"] > 0].copy()


def _recalculate_detail(detail: pd.DataFrame) -> pd.DataFrame:
    data = detail.copy()
    data["quantidade_atual"] = pd.to_numeric(data["quantidade_atual"], errors="coerce").fillna(0).astype(int)
    data["quantidade_meta"] = pd.to_numeric(data["quantidade_meta"], errors="coerce").fillna(0)
    data["quantidade_meta"] = np.floor(data["quantidade_meta"]).clip(lower=0).astype(int)
    data["preco"] = pd.to_numeric(data["preco"], errors="coerce").fillna(0.0).astype(float)

    data["valor_pos_rebalanceamento"] = data["quantidade_meta"] * data["preco"]
    total_pos = float(data["valor_pos_rebalanceamento"].sum())
    data["peso_pos_rebalanceamento"] = np.where(
        total_pos > 0,
        data["valor_pos_rebalanceamento"] / total_pos,
        0.0,
    )
    data["diferenca_qtd"] = data["quantidade_meta"] - data["quantidade_atual"]
    data["lado"] = np.select(
        [data["diferenca_qtd"] > 0, data["diferenca_qtd"] < 0],
        ["COMPRA", "VENDA"],
        default="",
    )
    data["quantidade_ordem"] = data["diferenca_qtd"].abs().astype(int)
    data["financeiro_ordem"] = data["quantidade_ordem"] * data["preco"]
    return data


def _cash_summary(detail: pd.DataFrame, aporte: float, retirada: float) -> dict[str, float]:
    costs = calculate_brokerage(_orders_detail(detail))
    total_vendas = float(costs["total_vendas"])
    total_compras = float(costs["total_compras"])
    custo_total = float(costs["custo_total"])
    caixa_disponivel = total_vendas + float(aporte) - float(retirada) - custo_total
    caixa_final = caixa_disponivel - total_compras
    return {
        "total_vendas": total_vendas,
        "total_compras": total_compras,
        "custo_total": custo_total,
        "caixa_disponivel_para_compras": caixa_disponivel,
        "caixa_final": caixa_final,
        **costs,
    }


def _fix_sales_above_position(detail: pd.DataFrame) -> pd.DataFrame:
    data = detail.copy()
    sales_too_large = data["quantidade_meta"] < 0
    data.loc[sales_too_large, "quantidade_meta"] = 0
    sales_mask = data["quantidade_atual"] > data["quantidade_meta"]
    over_position = sales_mask & ((data["quantidade_atual"] - data["quantidade_meta"]) > data["quantidade_atual"])
    data.loc[over_position, "quantidade_meta"] = 0
    return _recalculate_detail(data)


def _reduce_excess_buys(detail: pd.DataFrame, aporte: float, retirada: float, max_iterations: int = 100000) -> pd.DataFrame:
    data = _recalculate_detail(detail)
    iterations = 0

    while iterations < max_iterations:
        summary = _cash_summary(data, aporte, retirada)
        if summary["total_compras"] <= max(summary["caixa_disponivel_para_compras"], 0.0) + 1e-9:
            break

        buys = data[(data["lado"] == "COMPRA") & (data["quantidade_meta"] > data["quantidade_atual"])].copy()
        if buys.empty:
            break

        buys["underallocation"] = buys["peso_meta"].astype(float) - buys["peso_pos_rebalanceamento"].astype(float)
        buys = buys.sort_values(["underallocation", "preco"], ascending=[True, False])
        idx = buys.index[0]
        data.loc[idx, "quantidade_meta"] = int(data.loc[idx, "quantidade_meta"]) - 1
        data = _recalculate_detail(data)
        iterations += 1

    return data


def _increase_sales_for_cash(detail: pd.DataFrame, aporte: float, retirada: float, max_iterations: int = 100000) -> pd.DataFrame:
    data = _recalculate_detail(detail)
    iterations = 0

    while iterations < max_iterations:
        summary = _cash_summary(data, aporte, retirada)
        if summary["caixa_final"] >= -1e-9:
            break

        sellable = data[(data["quantidade_meta"] > 0) & (data["quantidade_atual"] > 0)].copy()
        if sellable.empty:
            break

        sellable["overallocation"] = sellable["peso_pos_rebalanceamento"].astype(float) - sellable["peso_meta"].astype(float)
        sellable = sellable.sort_values(["overallocation", "preco"], ascending=[False, False])
        idx = sellable.index[0]
        data.loc[idx, "quantidade_meta"] = int(data.loc[idx, "quantidade_meta"]) - 1
        data = _recalculate_detail(data)
        iterations += 1

    return data


def _check_row(item: str, status: str, expected, calculated, difference, message: str) -> dict[str, object]:
    return {
        "item_auditoria": item,
        "status": status,
        "valor_esperado": expected,
        "valor_calculado": calculated,
        "diferença": difference,
        "mensagem": message,
    }


def _audit_checks(
    detail: pd.DataFrame,
    aporte: float,
    retirada: float,
    patrimonio_ajustado: float,
    summary: dict[str, float],
) -> pd.DataFrame:
    checks: list[dict[str, object]] = []
    orders = _orders_detail(detail)
    quantity_series = pd.to_numeric(orders["quantidade_ordem"], errors="coerce")

    integer_ok = bool(quantity_series.dropna().map(lambda value: float(value).is_integer()).all()) if not quantity_series.empty else True
    checks.append(
        _check_row(
            "Quantidades são inteiras",
            STATUS_APPROVED if integer_ok else STATUS_CRITICAL,
            "inteiro",
            "inteiro" if integer_ok else "fracionário",
            "",
            "Todas as ordens estão em múltiplos unitários." if integer_ok else "Há quantidade fracionária nas ordens.",
        )
    )

    no_negative = bool((quantity_series >= 0).all()) if not quantity_series.empty else True
    checks.append(
        _check_row(
            "Não há quantidade negativa",
            STATUS_APPROVED if no_negative else STATUS_CRITICAL,
            ">= 0",
            float(quantity_series.min()) if not quantity_series.empty else 0,
            "",
            "Nenhuma ordem possui quantidade negativa." if no_negative else "Existe ordem com quantidade negativa.",
        )
    )

    no_zero = bool((quantity_series > 0).all()) if not quantity_series.empty else True
    checks.append(
        _check_row(
            "Não há ordem com quantidade zero",
            STATUS_APPROVED if no_zero else STATUS_CRITICAL,
            "> 0",
            int((quantity_series <= 0).sum()) if not quantity_series.empty else 0,
            "",
            "Ordens zeradas foram removidas." if no_zero else "Existe ordem zerada na tabela final.",
        )
    )

    sales = detail[detail["lado"] == "VENDA"].copy()
    sold_qty = sales["quantidade_ordem"]
    available_qty = sales["quantidade_atual"]
    sales_ok = bool((sold_qty <= available_qty).all()) if not sales.empty else True
    checks.append(
        _check_row(
            "Nenhuma venda supera a posição disponível",
            STATUS_APPROVED if sales_ok else STATUS_CRITICAL,
            "vendido <= disponível",
            "ok" if sales_ok else "excesso",
            "",
            "Todas as vendas respeitam a quantidade atual." if sales_ok else "Há venda acima da posição disponível.",
        )
    )

    buys_cash_ok = summary["total_compras"] <= max(summary["caixa_disponivel_para_compras"], 0.0) + 1e-9
    checks.append(
        _check_row(
            "Compras não superam caixa disponível",
            STATUS_APPROVED if buys_cash_ok else STATUS_CRITICAL,
            summary["caixa_disponivel_para_compras"],
            summary["total_compras"],
            summary["total_compras"] - summary["caixa_disponivel_para_compras"],
            "Compras respeitam o caixa disponível." if buys_cash_ok else "Compras superam o caixa disponível.",
        )
    )

    final_position_value = float(detail["valor_pos_rebalanceamento"].sum())
    expected_equity = float(patrimonio_ajustado) - summary["custo_total"]
    calculated_equity = final_position_value + summary["caixa_final"]
    equity_diff = calculated_equity - expected_equity
    equity_ok = abs(equity_diff) <= max(1.0, float(detail["preco"].max() if not detail.empty else 0.0))
    checks.append(
        _check_row(
            "Patrimônio final estimado confere",
            STATUS_APPROVED if equity_ok else STATUS_ALERT,
            expected_equity,
            calculated_equity,
            equity_diff,
            "Diferença dentro do erro esperado de arredondamento." if equity_ok else "Diferença acima do erro esperado de arredondamento.",
        )
    )

    cash_ok = summary["caixa_final"] >= -1e-9
    checks.append(
        _check_row(
            "Caixa residual final não é negativo",
            STATUS_APPROVED if cash_ok else STATUS_CRITICAL,
            ">= 0",
            summary["caixa_final"],
            summary["caixa_final"],
            "Caixa residual final positivo." if cash_ok else "Caixa residual final negativo.",
        )
    )

    orders_buy = float(orders.loc[orders["lado"] == "COMPRA", "financeiro_ordem"].sum()) if not orders.empty else 0.0
    orders_sell = float(orders.loc[orders["lado"] == "VENDA", "financeiro_ordem"].sum()) if not orders.empty else 0.0
    totals_ok = math.isclose(orders_buy, summary["total_compras"], abs_tol=0.01) and math.isclose(orders_sell, summary["total_vendas"], abs_tol=0.01)
    checks.append(
        _check_row(
            "Total de compras e vendas confere",
            STATUS_APPROVED if totals_ok else STATUS_CRITICAL,
            f"compras={summary['total_compras']}; vendas={summary['total_vendas']}",
            f"compras={orders_buy}; vendas={orders_sell}",
            "",
            "Totais conferem com a tabela de ordens." if totals_ok else "Totais divergem da tabela de ordens.",
        )
    )

    final_qty_ok = bool((detail["quantidade_meta"] >= 0).all()) if not detail.empty else True
    checks.append(
        _check_row(
            "Quantidade final de cada ativo não é negativa",
            STATUS_APPROVED if final_qty_ok else STATUS_CRITICAL,
            ">= 0",
            int(detail["quantidade_meta"].min()) if not detail.empty else 0,
            "",
            "Nenhum ativo fica com posição negativa." if final_qty_ok else "Há ativo com quantidade final negativa.",
        )
    )

    outside = detail[(detail["peso_meta"] <= 0) & (detail["quantidade_meta"] > 0)]
    outside_ok = outside.empty
    checks.append(
        _check_row(
            "Ativos fora da carteira destino",
            STATUS_APPROVED if outside_ok else STATUS_ALERT,
            "zerados",
            ", ".join(outside["ticker"].astype(str).tolist()) if not outside.empty else "zerados",
            "",
            "Ativos fora da carteira destino foram zerados." if outside_ok else "Há ativos fora da carteira destino mantidos por restrição de caixa/lote.",
        )
    )

    costs_considered = summary["custo_total"] >= -1e-9
    checks.append(
        _check_row(
            "Custos foram considerados no caixa",
            STATUS_APPROVED if costs_considered else STATUS_CRITICAL,
            "custo >= 0",
            summary["custo_total"],
            "",
            "Custos operacionais foram abatidos do caixa disponível.",
        )
    )

    withdrawal_ok = True
    if retirada > 0:
        withdrawal_ok = summary["total_vendas"] + float(aporte) >= float(retirada) + summary["custo_total"] - 1e-9
    checks.append(
        _check_row(
            "Retirada solicitada preservada no caixa",
            STATUS_APPROVED if withdrawal_ok else STATUS_CRITICAL,
            float(retirada),
            summary["total_vendas"] + float(aporte) - summary["custo_total"],
            summary["total_vendas"] + float(aporte) - summary["custo_total"] - float(retirada),
            "Retirada preservada." if withdrawal_ok else "Vendas e aporte não geram caixa suficiente para preservar a retirada.",
        )
    )

    return pd.DataFrame(checks)


def audit_and_adjust_orders(
    detail: pd.DataFrame,
    aporte: float,
    retirada: float,
    patrimonio_ajustado: float,
) -> dict[str, object]:
    adjusted = _recalculate_detail(detail)
    adjusted = _fix_sales_above_position(adjusted)
    adjusted = _reduce_excess_buys(adjusted, aporte, retirada)
    adjusted = _increase_sales_for_cash(adjusted, aporte, retirada)
    adjusted = _reduce_excess_buys(adjusted, aporte, retirada)
    adjusted = _recalculate_detail(adjusted)

    summary = _cash_summary(adjusted, aporte, retirada)
    checks = _audit_checks(adjusted, aporte, retirada, patrimonio_ajustado, summary)
    critical_count = int((checks["status"] == STATUS_CRITICAL).sum())
    alert_count = int((checks["status"] == STATUS_ALERT).sum())
    general_status = STATUS_CRITICAL if critical_count else (STATUS_ALERT if alert_count else STATUS_APPROVED)
    summary.update(
        {
            "aporte": float(aporte),
            "retirada": float(retirada),
            "caixa_residual_inicial": 0.0,
            "erros_criticos": critical_count,
            "alertas": alert_count,
            "status_geral": general_status,
        }
    )
    return {
        "detail": adjusted,
        "summary": summary,
        "checks": checks,
        "costs": calculate_brokerage(_orders_detail(adjusted)),
        "has_critical": critical_count > 0,
    }
