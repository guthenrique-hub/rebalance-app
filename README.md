# App de Rebalanceamento de Carteira

Aplicativo em Python + Streamlit para apoiar o rebalanceamento operacional de carteiras de ações brasileiras. O app compara uma carteira origem com uma carteira destino/modelo, busca preços via YFinance, calcula quantidades alvo, gera ordens sugeridas de compra/venda, estima custos operacionais, monta um texto de e-mail para o cliente e exporta tudo para Excel.

> Este sistema é uma ferramenta de apoio operacional. Os resultados devem ser conferidos antes da execução das ordens. A responsabilidade pela validação final é do usuário.

## Funcionalidades

- Upload de carteira origem em CSV, XLS ou XLSX.
- Edição manual da carteira origem com `st.data_editor`.
- Carteira destino via modelo padrão, upload ou edição manual.
- Download de modelos em Excel para carteira origem e carteira destino.
- Download do modelo de tombamento e geração do tombamento pós-rebalanceamento preenchido.
- Carteiras destino salvas por nome em `saved_target_portfolios.json`.
- Busca de preços online pelo YFinance usando tickers brasileiros no padrão `.SA`.
- Edição manual de preços não encontrados.
- Rebalanceamento com quantidades inteiras e algoritmo de distribuição de caixa residual.
- Geração de ordens no formato `ATIVO | LADO | QTDD | PREÇO | CLIENTE`.
- Cálculo de custos: corretagem de 0,5%, custos adicionais de 0,2% e custo total estimado de 0,7%.
- Estimativa informativa de lucro/prejuízo e IR/DARF sobre vendas, usando o preço médio da carteira origem.
- Gráficos em Plotly.
- Texto padrão de e-mail para autorização do cliente.
- Download de Excel com abas de ordens, detalhe, custos, origem, destino e preços.

## Instalação local

```bash
cd rebalance_app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Em macOS/Linux:

```bash
cd rebalance_app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Como rodar

```bash
streamlit run app.py
```

## Estrutura do projeto

```text
rebalance_app/
├── app.py
├── requirements.txt
├── README.md
├── default_portfolio.json
├── saved_target_portfolios.json
├── services/
│   ├── pricing.py
│   ├── rebalance.py
│   ├── brokerage.py
│   └── email_template.py
├── utils/
│   ├── validators.py
│   └── excel_export.py
└── assets/
```

## Formato dos arquivos de entrada

Carteira origem:

```text
ticker,quantidade
VALE3,100
PETR4,50
ITUB4,200
```

Carteira destino:

```text
ticker,peso
ALOS3,0.10
BBDC4,0.10
CURY3,0.10
CXSE3,0.10
ITSA4,0.10
ITUB4,0.10
PETR4,0.10
PLPL3,0.10
POMO4,0.10
VALE3,0.10
```

Os pesos podem ser informados como decimal (`0.10`) ou percentual (`10%`). A soma precisa ser 100%.

Também é possível baixar o arquivo `modelo_carteira_destino.xlsx` pelo app, preencher a carteira modelo, fazer upload e salvar com um nome. Depois disso, a carteira fica disponível no seletor "Carteira destino salva".

## Streamlit Cloud

1. Suba a pasta `rebalance_app` para um repositório no GitHub.
2. No Streamlit Cloud, crie um novo app apontando para o repositório.
3. Defina o arquivo principal como `rebalance_app/app.py` se a pasta estiver dentro de um repositório maior, ou `app.py` se o repositório contiver apenas o app.
4. O Streamlit Cloud instalará as dependências a partir de `requirements.txt`.

## Limitações do YFinance

O YFinance é usado como fonte primária de preços e depende da disponibilidade dos dados no Yahoo Finance. Preços podem apresentar atraso, indisponibilidade temporária, divergência de fechamento ou falhas pontuais por ticker. Quando um preço não é encontrado, o app permite edição manual e bloqueia o cálculo se o preço continuar vazio ou menor ou igual a zero.

## Aviso operacional

O app não executa ordens reais. Ele apenas gera sugestões para conferência humana. Antes de qualquer execução, valide preços, quantidades, custos, enquadramento, suitability, regras internas e autorização do cliente.

## Aviso fiscal

A estimativa fiscal é meramente informativa e considera apenas uma aproximação para operações comuns de ações no mercado à vista. O cálculo de IR/DARF depende do histórico completo de operações do cliente no mês, compensações acumuladas, tipo de ativo, day trade, custos operacionais, IRRF e demais regras fiscais aplicáveis. Validar com contador ou responsável fiscal antes do recolhimento.
