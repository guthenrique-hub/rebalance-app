from __future__ import annotations

from io import BytesIO

import pandas as pd


def build_excel_export(
    orders: pd.DataFrame,
    detail: pd.DataFrame,
    costs: dict[str, float],
    origem: pd.DataFrame,
    destino: pd.DataFrame,
    prices: pd.DataFrame,
    fiscal_detail: pd.DataFrame | None = None,
    fiscal_summary: dict[str, float | str] | None = None,
    fiscal_notice: str | None = None,
) -> bytes:
    output = BytesIO()
    costs_df = pd.DataFrame(
        [
            {"Métrica": "Total compras", "Valor": costs["total_compras"]},
            {"Métrica": "Total vendas", "Valor": costs["total_vendas"]},
            {"Métrica": "Movimentação total", "Valor": costs["movimentacao_total"]},
            {"Métrica": "Corretagem 0,5%", "Valor": costs["corretagem"]},
            {"Métrica": "Custos adicionais 0,2%", "Valor": costs["custos_adicionais"]},
            {"Métrica": "Custo total estimado 0,7%", "Valor": costs["custo_total"]},
        ]
    )

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheets = {
            "Ordens": orders,
            "Rebalanceamento Detalhado": detail,
            "Custos": costs_df,
            "Carteira Origem": origem,
            "Carteira Destino": destino,
            "Preços": prices,
        }

        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        money_format = workbook.add_format({"num_format": 'R$ #,##0.00'})
        percent_format = workbook.add_format({"num_format": "0.00%"})
        title_format = workbook.add_format({"bold": True, "font_size": 13, "bg_color": "#EAF4EA"})
        wrap_format = workbook.add_format({"text_wrap": True, "valign": "top"})

        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            df.to_excel(writer, index=False, sheet_name=safe_name)
            worksheet = writer.sheets[safe_name]
            for col_num, value in enumerate(df.columns):
                worksheet.write(0, col_num, value, header_format)
                width = max(12, min(35, max(len(str(value)), *(len(str(x)) for x in df[value].head(200).fillna(""))) + 2))
                worksheet.set_column(col_num, col_num, width)

            for col_num, value in enumerate(df.columns):
                lowered = str(value).lower()
                if "valor" in lowered or "preco" in lowered or "financeiro" in lowered or "total" in lowered or value == "Valor":
                    worksheet.set_column(col_num, col_num, 16, money_format)
                if "peso" in lowered:
                    worksheet.set_column(col_num, col_num, 14, percent_format)

        if fiscal_detail is not None and fiscal_summary is not None:
            sheet_name = "Estimativa Fiscal"
            fiscal_detail.to_excel(writer, index=False, sheet_name=sheet_name, startrow=1)
            worksheet = writer.sheets[sheet_name]
            worksheet.write(0, 0, "Resultado fiscal por ativo vendido", title_format)

            for col_num, value in enumerate(fiscal_detail.columns):
                worksheet.write(1, col_num, value, header_format)
                width = max(12, min(35, max(len(str(value)), *(len(str(x)) for x in fiscal_detail[value].head(200).fillna(""))) + 2))
                worksheet.set_column(col_num, col_num, width)
                lowered = str(value).lower()
                if (
                    "valor" in lowered
                    or "preco" in lowered
                    or "custo" in lowered
                    or "lucro" in lowered
                    or "ir" in lowered
                    or "prejuizo" in lowered
                ):
                    worksheet.set_column(col_num, col_num, 16, money_format)

            summary_df = pd.DataFrame(
                [{"Métrica": key, "Valor": value} for key, value in fiscal_summary.items()]
            )
            start_row = len(fiscal_detail) + 5
            worksheet.write(start_row, 0, "Resumo fiscal", title_format)
            summary_df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=start_row + 1)
            for col_num, value in enumerate(summary_df.columns):
                worksheet.write(start_row + 1, col_num, value, header_format)
            worksheet.set_column(0, 0, 34)
            worksheet.set_column(1, 1, 24, money_format)

            notice_row = start_row + len(summary_df) + 4
            worksheet.write(notice_row, 0, "Avisos fiscais", title_format)
            worksheet.write(notice_row + 1, 0, fiscal_notice or "", wrap_format)
            worksheet.set_column(0, max(len(fiscal_detail.columns) - 1, 1), 20)
            worksheet.set_row(notice_row + 1, 70)

    return output.getvalue()
