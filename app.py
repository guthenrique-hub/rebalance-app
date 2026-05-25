from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from services.brokerage import calculate_brokerage
from services.email_template import generate_email
from services.pricing import fetch_prices
from services.rebalance import build_orders_table, calculate_rebalance
from services.tax import FISCAL_NOTICE, calculate_tax_estimate
from utils.excel_export import build_excel_export
from utils.tombamento_export import build_tombamento_export
from utils.validators import normalize_origin, normalize_target, validate_prices, validate_run_inputs


BASE_DIR = Path(__file__).parent
DEFAULT_PORTFOLIO_PATH = BASE_DIR / "default_portfolio.json"
ORIGIN_TEMPLATE_PATH = BASE_DIR / "assets" / "modelo_carteira_origem.xlsx"
TARGET_TEMPLATE_PATH = BASE_DIR / "assets" / "modelo_carteira_destino.xlsx"
TOMBAMENTO_TEMPLATE_PATH = BASE_DIR / "assets" / "CR_Tombamento_Modelo.xlsx"
SAVED_TARGET_PORTFOLIOS_PATH = BASE_DIR / "saved_target_portfolios.json"
DISCLAIMER = (
    "Este sistema é uma ferramenta de apoio operacional. Os resultados devem ser conferidos antes da execução "
    "das ordens. A responsabilidade pela validação final é do usuário."
)


st.set_page_config(page_title="Rebalanceamento de Carteira", page_icon="📊", layout="wide")


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def load_default_portfolio() -> pd.DataFrame:
    with DEFAULT_PORTFOLIO_PATH.open("r", encoding="utf-8") as file:
        return pd.DataFrame(json.load(file))


def load_saved_target_portfolios() -> dict[str, list[dict[str, object]]]:
    if not SAVED_TARGET_PORTFOLIOS_PATH.exists():
        return {}
    try:
        with SAVED_TARGET_PORTFOLIOS_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_target_portfolio(name: str, portfolio: pd.DataFrame) -> None:
    saved_portfolios = load_saved_target_portfolios()
    saved_portfolios[name.strip()] = portfolio[["ticker", "peso"]].to_dict(orient="records")
    with SAVED_TARGET_PORTFOLIOS_PATH.open("w", encoding="utf-8") as file:
        json.dump(saved_portfolios, file, ensure_ascii=False, indent=2)


def target_portfolio_from_saved(name: str, saved_portfolios: dict[str, list[dict[str, object]]]) -> pd.DataFrame:
    return pd.DataFrame(saved_portfolios.get(name, []), columns=["ticker", "peso"])


def read_uploaded_file(uploaded_file) -> pd.DataFrame | None:
    if uploaded_file is None:
        return None
    suffix = Path(uploaded_file.name).suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(uploaded_file)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(uploaded_file)
    except Exception as exc:
        st.error(f"Não foi possível ler o arquivo {uploaded_file.name}: {exc}")
        return None

    st.error("Formato não suportado. Envie arquivo CSV, XLS ou XLSX.")
    return None


def default_origin() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "VALE3", "quantidade": 100},
            {"ticker": "PETR4", "quantidade": 50},
            {"ticker": "ITUB4", "quantidade": 200},
        ]
    )


def prepare_target_for_editor(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if "peso" in data.columns:
        data["peso"] = data["peso"].map(lambda value: "" if pd.isna(value) else str(value))
    return data


def show_errors(errors: list[str]) -> None:
    for error in errors:
        st.error(error)


def pie_chart(df: pd.DataFrame, names: str, values: str, title: str):
    plot_df = df[df[values] > 0].copy()
    if plot_df.empty:
        return px.pie(title=title)
    return px.pie(plot_df, names=names, values=values, title=title, hole=0.35)


def calculate_origin_equity(origin: pd.DataFrame, prices: pd.DataFrame) -> float:
    origin_with_prices = origin.merge(prices[["ticker", "preco"]], on="ticker", how="left")
    calculated_position = origin_with_prices["quantidade"] * origin_with_prices["preco"]
    if "valor_financeiro" in origin_with_prices.columns:
        position = origin_with_prices["valor_financeiro"].where(origin_with_prices["valor_financeiro"].notna(), calculated_position)
        return float(position.sum())
    return float(calculated_position.sum())


def show_position_difference_alert(origin: pd.DataFrame, prices: pd.DataFrame) -> None:
    if "valor_financeiro" not in origin.columns:
        return

    comparison = origin.merge(prices[["ticker", "preco"]], on="ticker", how="left")
    comparison["posicao_calculada"] = comparison["quantidade"] * comparison["preco"]
    comparison = comparison[comparison["valor_financeiro"].notna()].copy()
    if comparison.empty:
        st.info("A coluna Posição está vazia. O app calculará a posição como Qtd. Total x preço atual.")
        return

    comparison["diferenca_posicao"] = comparison["valor_financeiro"] - comparison["posicao_calculada"]
    comparison["diferenca_abs"] = comparison["diferenca_posicao"].abs()
    divergent = comparison[comparison["diferenca_abs"] > 0.01]
    if divergent.empty:
        return

    st.warning(
        "Existe diferença entre a Posição informada no modelo e a posição calculada por Qtd. Total x preço atual. "
        "O rebalanceamento usará a Posição informada quando ela estiver preenchida."
    )
    st.dataframe(
        divergent[["ticker", "quantidade", "preco", "valor_financeiro", "posicao_calculada", "diferenca_posicao"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "preco": st.column_config.NumberColumn("preco", format="R$ %.2f"),
            "valor_financeiro": st.column_config.NumberColumn("posição informada", format="R$ %.2f"),
            "posicao_calculada": st.column_config.NumberColumn("posição calculada", format="R$ %.2f"),
            "diferenca_posicao": st.column_config.NumberColumn("diferença", format="R$ %.2f"),
        },
    )


st.title("App de Rebalanceamento de Carteira")
st.caption(DISCLAIMER)

saved_target_portfolios = load_saved_target_portfolios()
tombamento_container = st.container()

with st.sidebar:
    st.header("Dados do Cliente")
    nome_cliente = st.text_input("Nome do cliente")
    conta_cliente = st.text_input("Código/conta do cliente")
    assessor = st.text_input("Assessor responsável (opcional)")
    aporte = st.number_input("Aporte adicional em reais", min_value=0.0, value=0.0, step=100.0, format="%.2f")
    retirada = st.number_input("Retirada em reais", min_value=0.0, value=0.0, step=100.0, format="%.2f")
    vendas_ja_realizadas_mes = st.number_input(
        "Vendas já realizadas no mês",
        min_value=0.0,
        value=0.0,
        step=100.0,
        format="%.2f",
    )

    st.divider()
    st.header("Arquivos")
    if ORIGIN_TEMPLATE_PATH.exists():
        st.download_button(
            "Baixar modelo de Carteira Origem",
            data=ORIGIN_TEMPLATE_PATH.read_bytes(),
            file_name="modelo_carteira_origem.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    if TARGET_TEMPLATE_PATH.exists():
        st.download_button(
            "Baixar modelo de Carteira Destino",
            data=TARGET_TEMPLATE_PATH.read_bytes(),
            file_name="modelo_carteira_destino.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    origem_upload = st.file_uploader("Upload carteira origem", type=["csv", "xlsx", "xls"])
    destino_upload = st.file_uploader("Upload carteira destino", type=["csv", "xlsx", "xls"])
    saved_target_options = ["Carteira padrão"] + sorted(saved_target_portfolios)
    selected_saved_target = st.selectbox("Carteira destino salva", saved_target_options)
    sort_mode = st.selectbox("Ordenação das ordens", ["Compras depois vendas", "Vendas depois compras"])
    run_rebalance = st.button("Rodar rebalanceamento", type="primary", use_container_width=True)

with tombamento_container:
    st.header("Tombamento Pós-Rebalanceamento")
    if TOMBAMENTO_TEMPLATE_PATH.exists():
        st.download_button(
            "Baixar Modelo de Tombamento",
            data=TOMBAMENTO_TEMPLATE_PATH.read_bytes(),
            file_name="CR_Tombamento_Modelo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.warning("Modelo de tombamento não encontrado em assets/CR_Tombamento_Modelo.xlsx.")


origin_source = read_uploaded_file(origem_upload)
if origin_source is None:
    origin_source = default_origin()

target_source = read_uploaded_file(destino_upload)
if target_source is not None:
    st.info("Carteira destino carregada pelo upload. Ela pode ser salva com um nome na seção Carteira Destino.")
    target_source_key = f"upload_{destino_upload.name}"
elif selected_saved_target != "Carteira padrão":
    target_source = target_portfolio_from_saved(selected_saved_target, saved_target_portfolios)
    target_source_key = f"saved_{selected_saved_target}"
else:
    target_source = load_default_portfolio()
    target_source_key = "default"

st.header("1. Carteira Origem")
st.write("Formato simples: `ticker | quantidade`. O modelo disponível usa `Ativo` na coluna A, `Qtd. Total` na H e `Posição` na L.")
origin_edited = st.data_editor(
    origin_source,
    num_rows="dynamic",
    use_container_width=True,
    key="origin_editor",
    column_config={
        "ticker": st.column_config.TextColumn("ticker", required=True),
        "quantidade": st.column_config.NumberColumn("quantidade", min_value=0, step=1, required=True),
    },
)
origin_clean, origin_errors = normalize_origin(origin_edited)
if origin_errors:
    show_errors(origin_errors)
else:
    st.success("Carteira origem validada e consolidada.")
    st.dataframe(origin_clean, use_container_width=True, hide_index=True)
    if "valor_financeiro" in origin_clean.columns:
        if origin_clean["valor_financeiro"].notna().any():
            st.info(f"Valor total da carteira origem pelo modelo: {format_brl(float(origin_clean['valor_financeiro'].sum()))}")
        else:
            st.info("A coluna Posição está vazia. O valor total será calculado após a busca de preços.")

st.header("2. Carteira Destino")
st.write("Formato obrigatório: `ticker | peso`. Pesos aceitos como decimal (`0.10`) ou percentual (`10%`).")
target_edited = st.data_editor(
    prepare_target_for_editor(target_source),
    num_rows="dynamic",
    use_container_width=True,
    key=f"target_editor_{target_source_key}",
    column_config={
        "ticker": st.column_config.TextColumn("ticker", required=True),
        "peso": st.column_config.TextColumn("peso", required=True),
    },
)
target_clean, target_errors = normalize_target(target_edited)
if target_errors:
    show_errors(target_errors)
else:
    st.success(f"Carteira destino validada. Soma dos pesos: {target_clean['peso'].sum():.2%}.")
    st.dataframe(target_clean, use_container_width=True, hide_index=True)
    save_col_1, save_col_2 = st.columns([2, 1])
    with save_col_1:
        target_portfolio_name = st.text_input(
            "Nome da carteira destino",
            value="" if selected_saved_target == "Carteira padrão" else selected_saved_target,
            placeholder="Ex.: Carteira Dividendos 10 Ativos",
        )
    with save_col_2:
        st.write("")
        st.write("")
        if st.button("Salvar carteira destino", use_container_width=True):
            if not target_portfolio_name.strip():
                st.error("Informe um nome para salvar a carteira destino.")
            else:
                save_target_portfolio(target_portfolio_name, target_clean)
                st.success(f"Carteira destino '{target_portfolio_name.strip()}' salva.")
                st.rerun()

st.header("3. Preços dos Ativos")
can_fetch_prices = not origin_errors and not target_errors
all_tickers = sorted(set(origin_clean["ticker"]) | set(target_clean["ticker"])) if can_fetch_prices else []

if can_fetch_prices and all_tickers:
    with st.spinner("Buscando preços no YFinance..."):
        prices_source = fetch_prices(all_tickers)
    missing_prices = prices_source[prices_source["status"] != "OK"]["ticker"].tolist()
    if missing_prices:
        st.warning("Preço não encontrado para: " + ", ".join(missing_prices) + ". Edite manualmente antes de calcular.")

    prices_edited = st.data_editor(
        prices_source,
        use_container_width=True,
        hide_index=True,
        key="prices_editor",
        disabled=["ticker", "ticker_yfinance", "status"],
        column_config={
            "preco": st.column_config.NumberColumn("preco", min_value=0.0, step=0.01, format="%.2f"),
        },
    )
    if not validate_prices(prices_edited):
        show_position_difference_alert(origin_clean, prices_edited)
else:
    prices_edited = pd.DataFrame(columns=["ticker", "ticker_yfinance", "preco", "status"])
    st.info("Valide as carteiras para buscar os preços.")

price_errors = validate_prices(prices_edited) if can_fetch_prices else ["Preços ainda não disponíveis."]

if run_rebalance:
    st.session_state["run_requested"] = True

if st.session_state.get("run_requested"):
    st.header("4. Resultado do Rebalanceamento")

    estimated_current_equity = 0.0
    if not origin_errors and not price_errors:
        estimated_current_equity = calculate_origin_equity(origin_clean, prices_edited)

    patrimonio_ajustado_previo = estimated_current_equity + aporte - retirada
    run_errors = []
    run_errors.extend(origin_errors)
    run_errors.extend(target_errors)
    run_errors.extend(price_errors)
    run_errors.extend(validate_run_inputs(nome_cliente, conta_cliente, patrimonio_ajustado_previo))

    if run_errors:
        show_errors(run_errors)
        st.stop()

    detail, rebalance_summary = calculate_rebalance(
        carteira_origem=origin_clean,
        carteira_destino=target_clean,
        precos=prices_edited,
        aporte=aporte,
        retirada=retirada,
    )
    orders = build_orders_table(detail, conta_cliente, sort_mode)
    order_detail = detail[detail["quantidade_ordem"] > 0].copy()
    costs = calculate_brokerage(order_detail)
    fiscal_detail, fiscal_summary = calculate_tax_estimate(detail, vendas_ja_realizadas_mes)

    with tombamento_container:
        if TOMBAMENTO_TEMPLATE_PATH.exists():
            tombamento_bytes = build_tombamento_export(TOMBAMENTO_TEMPLATE_PATH, detail, conta_cliente)
            st.download_button(
                "Baixar Tombamento Pós-Rebalanceamento Preenchido",
                data=tombamento_bytes,
                file_name="tombamento_pos_rebalanceamento.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    metric_cols = st.columns(5)
    metric_cols[0].metric("Patrimônio atual", format_brl(rebalance_summary["valor_total_carteira_atual"]))
    metric_cols[1].metric("Patrimônio ajustado", format_brl(rebalance_summary["patrimonio_ajustado"]))
    metric_cols[2].metric("Aporte", format_brl(aporte))
    metric_cols[3].metric("Retirada", format_brl(retirada))
    metric_cols[4].metric("Número de ordens", f"{len(orders)}")

    metric_cols = st.columns(5)
    metric_cols[0].metric("Total compras", format_brl(costs["total_compras"]))
    metric_cols[1].metric("Total vendas", format_brl(costs["total_vendas"]))
    metric_cols[2].metric("Movimentação total", format_brl(costs["movimentacao_total"]))
    metric_cols[3].metric("Custo total estimado", format_brl(costs["custo_total"]))
    metric_cols[4].metric("Caixa estimado", format_brl(rebalance_summary["caixa_estimado"]))

    st.subheader("Tabela Detalhada de Rebalanceamento")
    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        column_config={
            "preco": st.column_config.NumberColumn("preco", format="R$ %.2f"),
            "valor_atual": st.column_config.NumberColumn("valor_atual", format="R$ %.2f"),
            "peso_atual": st.column_config.NumberColumn("peso_atual", format="%.2f%%"),
            "peso_meta": st.column_config.NumberColumn("peso_meta", format="%.2f%%"),
            "valor_meta": st.column_config.NumberColumn("valor_meta", format="R$ %.2f"),
            "valor_pos_rebalanceamento": st.column_config.NumberColumn("valor_pos_rebalanceamento", format="R$ %.2f"),
            "peso_pos_rebalanceamento": st.column_config.NumberColumn("peso_pos_rebalanceamento", format="%.2f%%"),
            "financeiro_ordem": st.column_config.NumberColumn("financeiro_ordem", format="R$ %.2f"),
        },
    )

    st.header("5. Ordens Geradas")
    st.dataframe(orders, use_container_width=True, hide_index=True)
    st.text_area("Tabela para copiar", orders.to_csv(index=False, sep="\t"), height=180)

    st.header("6. Custos Operacionais")
    costs_df = pd.DataFrame(
        [
            {"Item": "Total compras", "Valor": costs["total_compras"]},
            {"Item": "Total vendas", "Valor": costs["total_vendas"]},
            {"Item": "Movimentação total", "Valor": costs["movimentacao_total"]},
            {"Item": "Corretagem 0,5%", "Valor": costs["corretagem"]},
            {"Item": "Custos adicionais 0,2%", "Valor": costs["custos_adicionais"]},
            {"Item": "Custo total estimado 0,7%", "Valor": costs["custo_total"]},
        ]
    )
    st.dataframe(costs_df, use_container_width=True, hide_index=True)

    st.header("7. Estimativa Fiscal")
    st.warning(FISCAL_NOTICE)
    fiscal_cols = st.columns(4)
    fiscal_cols[0].metric("Vendas já realizadas no mês", format_brl(float(fiscal_summary["vendas_ja_realizadas_mes"])))
    fiscal_cols[1].metric("Vendas do rebalanceamento", format_brl(float(fiscal_summary["vendas_rebalanceamento"])))
    fiscal_cols[2].metric("Total de vendas no mês", format_brl(float(fiscal_summary["total_vendas_mes"])))
    fiscal_cols[3].metric("IR estimado DARF", format_brl(float(fiscal_summary["ir_estimado_total"])))

    fiscal_cols = st.columns(4)
    fiscal_cols[0].metric("Lucro bruto estimado", format_brl(float(fiscal_summary["lucro_total"])))
    fiscal_cols[1].metric("Prejuízo estimado", format_brl(float(fiscal_summary["prejuizo_total"])))
    fiscal_cols[2].metric("Lucro líquido estimado", format_brl(float(fiscal_summary["lucro_liquido"])))
    fiscal_cols[3].metric("Prejuízo potencialmente compensável", format_brl(float(fiscal_summary["prejuizo_compensavel"])))

    st.dataframe(
        fiscal_detail,
        use_container_width=True,
        hide_index=True,
        column_config={
            "preco_medio": st.column_config.NumberColumn("preco_medio", format="R$ %.2f"),
            "preco_venda_estimado": st.column_config.NumberColumn("preco_venda_estimado", format="R$ %.2f"),
            "valor_venda": st.column_config.NumberColumn("valor_venda", format="R$ %.2f"),
            "custo_medio_vendido": st.column_config.NumberColumn("custo_medio_vendido", format="R$ %.2f"),
            "lucro_prejuizo": st.column_config.NumberColumn("lucro_prejuizo", format="R$ %.2f"),
            "ir_estimado": st.column_config.NumberColumn("ir_estimado", format="R$ %.2f"),
            "prejuizo_compensavel": st.column_config.NumberColumn("prejuizo_compensavel", format="R$ %.2f"),
        },
    )
    if "preco_medio" not in origin_clean.columns or origin_clean["preco_medio"].isna().any():
        st.info("Para estimar IR em todas as vendas, use o modelo de Carteira Origem com a coluna Preço Médio preenchida.")

    st.header("8. Gráficos")
    chart_col_1, chart_col_2 = st.columns(2)
    with chart_col_1:
        st.plotly_chart(pie_chart(detail, "ticker", "valor_atual", "Carteira atual"), use_container_width=True)
    with chart_col_2:
        st.plotly_chart(
            pie_chart(detail, "ticker", "valor_pos_rebalanceamento", "Carteira pós-rebalanceamento"),
            use_container_width=True,
        )

    weights_plot = detail[["ticker", "peso_atual", "peso_meta", "peso_pos_rebalanceamento"]].melt(
        id_vars="ticker",
        var_name="Tipo",
        value_name="Peso",
    )
    st.plotly_chart(
        px.bar(weights_plot, x="ticker", y="Peso", color="Tipo", barmode="group", title="Peso atual, meta e pós-rebalanceamento"),
        use_container_width=True,
    )
    detail["diferenca_peso_pos_vs_meta"] = detail["peso_pos_rebalanceamento"] - detail["peso_meta"]
    st.plotly_chart(
        px.bar(detail, x="ticker", y="diferenca_peso_pos_vs_meta", title="Diferença de pesos: pós-rebalanceamento vs meta"),
        use_container_width=True,
    )

    st.header("9. E-mail para Cliente")
    email_text = generate_email(nome_cliente, orders, costs, assessor)
    st.text_area("Texto do e-mail", email_text, height=420)

    st.header("10. Download Excel")
    excel_bytes = build_excel_export(
        orders=orders,
        detail=detail.drop(columns=["diferenca_peso_pos_vs_meta"], errors="ignore"),
        costs=costs,
        origem=origin_clean,
        destino=target_clean,
        prices=prices_edited,
        fiscal_detail=fiscal_detail,
        fiscal_summary=fiscal_summary,
        fiscal_notice=FISCAL_NOTICE,
    )
    st.download_button(
        "Baixar ordens_rebalanceamento.xlsx",
        data=excel_bytes,
        file_name="ordens_rebalanceamento.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
else:
    st.info("Preencha os dados, revise as tabelas editáveis e clique em Rodar rebalanceamento.")
