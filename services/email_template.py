from __future__ import annotations

import pandas as pd


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def orders_to_text(orders: pd.DataFrame) -> str:
    if orders.empty:
        return "Nenhuma ordem gerada."
    return orders[["ATIVO", "LADO", "QTDD", "PREÇO", "CLIENTE"]].to_string(index=False)


def generate_email(
    nome_cliente: str,
    orders: pd.DataFrame,
    costs: dict[str, float],
    assessor: str | None = None,
) -> str:
    assinatura = f"\n{assessor.strip()}" if assessor and assessor.strip() else ""
    tabela_ordens = orders_to_text(orders)

    return f"""{nome_cliente}, tudo bem?

Identificamos a necessidade de realização de ajustes em sua carteira de investimentos, com a finalidade de reenquadramento e rebalanceamento das posições, buscando manter a alocação alinhada ao perfil, estratégia e objetivos definidos para a carteira.

{tabela_ordens}

Resumo financeiro do rebalanceamento:

Movimentação total: {_format_brl(costs["movimentacao_total"])}
Corretagem estimada (0,5%): {_format_brl(costs["corretagem"])}
Custos adicionais (0,2%): {_format_brl(costs["custos_adicionais"])}
Custo total estimado: {_format_brl(costs["custo_total"])}

Dessa forma, solicitamos sua autorização para execução das ordens necessárias para os devidos ajustes de posição.

Caso esteja de acordo, pedimos, por gentileza, que responda este e-mail com o seu "de acordo" para prosseguirmos com as movimentações.

Permanecemos à disposição para quaisquer esclarecimentos adicionais.

Atenciosamente,{assinatura}
"""
