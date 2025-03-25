# %%
import pandas as pd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import yfinance as yf
from sodapy import Socrata
from datetime import datetime, timedelta
import plotly.graph_objects as go
from dash import Dash, dcc, html
import os
import platform

# Anpassad temporär katalog beroende på operativsystem
if platform.system() == "Windows":
    tmp_dir = "tmp"
else:
    tmp_dir = "/tmp"

# Skapa katalogen om den inte finns
os.makedirs(tmp_dir, exist_ok=True)

# Färdiga sökvägar för användning i koden
data_path = os.path.join(tmp_dir, "silver_dashboard.parquet")
timestamp_path = os.path.join(tmp_dir, "last_updated.txt")


# %%
# Funktion för att hämta data från Socrata API
def fetch_cftc_data(contract_code, start_date, end_date, limit=5000):
    """
    Hämtar data från CFTC:s Socrata API baserat på kontraktskod och datumintervall.

    :param contract_code: (str) CFTC kontraktskod
    :param start_date: (str) Startdatum i format YYYY-MM-DD
    :param end_date: (str) Slutdatum i format YYYY-MM-DD
    :param limit: (int) Max antal rader att hämta (default 5000)
    :return: DataFrame med hämtad data
    """
    # Anslut till API
    client = Socrata("publicreporting.cftc.gov", None)

    # Bygg SoQL-query
    query = f"(cftc_contract_market_code == '{contract_code}') AND \
               (report_date_as_yyyy_mm_dd >= '{start_date}T00:00:00.000' AND \
               report_date_as_yyyy_mm_dd <= '{end_date}T00:00:00.000')"

    # Hämta data
    results = client.get("6dca-aqww", where=query, order="report_date_as_yyyy_mm_dd", limit=limit)

    # Konvertera till DataFrame
    df = pd.DataFrame.from_records(results)

    return df


# %%
def process_cot_index(raw_df, rolling_window=26):

    raw_df['noncomm_positions_long_all'] = pd.to_numeric(raw_df['noncomm_positions_long_all'], errors='coerce')
    raw_df['noncomm_positions_short_all'] = pd.to_numeric(raw_df['noncomm_positions_short_all'], errors='coerce')
    raw_df['report_date_as_yyyy_mm_dd'] = pd.to_datetime(raw_df['report_date_as_yyyy_mm_dd'])

    df = raw_df.copy()
    df['Net_Position'] = df['noncomm_positions_long_all'] - df['noncomm_positions_short_all']
    df['Min_Net'] = df['Net_Position'].rolling(window=rolling_window, min_periods=1).min()
    df['Max_Net'] = df['Net_Position'].rolling(window=rolling_window, min_periods=1).max()
    df['COT_Index'] = ((df['Net_Position'] - df['Min_Net']) / (df['Max_Net'] - df['Min_Net'])) * 100
    df['COT_Index'] = df['COT_Index'].fillna(50)

    df = df[['report_date_as_yyyy_mm_dd', 'Net_Position', 'Min_Net', 'Max_Net', 'COT_Index']]
    df.rename(columns={'report_date_as_yyyy_mm_dd': 'Date'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

    return df

# %%
def fetch_silver_price_data(years=2):
# Define the ticker
    silver = yf.Ticker("SI=F")
    silver_data = silver.history(period=f"{years}y")

    # Ta bort tidszon från index
    silver_data.index = silver_data.index.tz_localize(None)

    # Lägg till en Date-kolumn med endast datum (ingen tid)
    silver_data["Date"] = silver_data.index.normalize()

    # Filtrera efter önskat antal år (igen, för säkerhets skull)
    start_date = datetime.today() - timedelta(weeks=years*52)
    silver_data = silver_data[silver_data["Date"] >= start_date]

    # Behåll bara det vi behöver
    df_price = silver_data[["Date", "Close"]].copy()

    return df_price


# %%
def merge_and_prepare_data(silver_df, cotindex_df, years=2, save_path=None):
    import pandas as pd
    from datetime import datetime, timedelta
    
    silver_df = silver_df.reset_index(drop=True)
    cotindex_df = cotindex_df.reset_index(drop=True)

    silver_df["Date"] = pd.to_datetime(silver_df["Date"])
    cotindex_df["Date"] = pd.to_datetime(cotindex_df["Date"])

    df_merged = silver_df.merge(cotindex_df, on="Date", how="left")
    df_merged["COT_Index"] = df_merged["COT_Index"].ffill()
    df_merged["Net_Position"] = df_merged["Net_Position"].ffill()

    cutoff_date = datetime.today() - timedelta(weeks=years*52)
    df_filtered = df_merged[df_merged["Date"] >= cutoff_date].copy()

    df_filtered["COT_Index"] = pd.to_numeric(df_filtered["COT_Index"], errors='coerce')
    df_filtered["Net_Position"] = pd.to_numeric(df_filtered["Net_Position"], errors='coerce')

    min_val = df_filtered["Net_Position"].min()
    max_val = df_filtered["Net_Position"].max()
    df_filtered["Net_Position_Scaled"] = ((df_filtered["Net_Position"] - min_val) / (max_val - min_val)) * 99 + 1

    if save_path:
        df_filtered.to_excel(save_path, index=False)
        print(f"Saved to {save_path}")

    return df_filtered


# %%

def load_or_update_data(force_update=False, refresh_interval_hours=4):

    global data_path, timestamp_path

    if not force_update and os.path.exists(data_path) and os.path.exists(timestamp_path):
        with open(timestamp_path, "r") as f:
            last_update = datetime.strptime(f.read().strip(), "%Y-%m-%d %H:%M")

        if datetime.now() - last_update < timedelta(hours=refresh_interval_hours):
            print(f"✅ Cache används (uppdaterad {last_update.strftime('%Y-%m-%d %H:%M')})")
            return pd.read_parquet(data_path)

    # Annars – hämta ny data
    print("🔁 Hämtar ny data...")

# Tidsintervall: 3 år bakåt

    today = datetime.today()
    start_date = (today - timedelta(weeks=156)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

# 1. Hämta och bearbeta COT-data (084691=Silver)
    raw_cftc = fetch_cftc_data("084691", start_date, end_date)
# 2. Hämtar datarmen för COT_Index 
    cotindex = process_cot_index(raw_cftc)
# 3. Hämta silverpris   
    silver = fetch_silver_price_data(years=2)
# 4. Kombinerar datan
    final_df = merge_and_prepare_data(silver, cotindex, years=2)

    # Spara ny data
    final_df.to_parquet(data_path, index=False)
    with open(timestamp_path, "w") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M"))

    print("✅ Ny data sparad")
    return final_df





# %%
def create_dashboard(df, run=True):

    df["Date"] = pd.to_datetime(df["Date"])

    fig = go.Figure()

    # Silver Price
    fig.add_trace(go.Scatter(
        x=df["Date"],
        y=df["Close"],
        mode="lines",
        line=dict(color='#4A90E2', width=2, dash="dot"),
        name="Silver Price (Close)",
        hovertemplate="<br><b>Silver Price:</b> %{y:.2f} USD<extra></extra>"
    ))

    # COT Index
    fig.add_trace(go.Scatter(
        x=df["Date"],
        y=df["COT_Index"],
        mode="lines",
        line=dict(color='#E74C3C', width=2),
        name="COT Index",
        yaxis="y2",
        hovertemplate="<b>COT Index:</b> %{y:.2f}<extra></extra>"
    ))

    # Net Position
    fig.add_trace(go.Scatter(
        x=df["Date"],
        y=df["Net_Position_Scaled"],
        mode="lines",
        line=dict(color='#27AE60', width=2),
        name="Net Position",
        opacity=0.5,
        yaxis="y2",
        hovertemplate="<b>Net Position:</b> %{y:.2f}<extra></extra>"
    ))

    fig.update_layout(
        plot_bgcolor="#1C1C1C",
        paper_bgcolor="#262626",
        annotations=[
            dict(
                text="<-ℹ️ Click on the legend to hide/show lines",
                x=0.3,
                y=1.4,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=14, color="white"),
                align="left",
                bgcolor="rgba(50, 50, 50, 0.7)",
                bordercolor="white",
                borderwidth=1,
                borderpad=5
            )
        ],
        xaxis=dict(
            title="Zoom",
            showgrid=True,
            gridcolor="rgba(200, 200, 200, 0.2)",
            showline=True,
            tickformat="%Y-%m",
            showspikes=True,
            spikemode="across",
            spikedash="dot",
            spikecolor="gray",
            spikethickness=1,
            hoverformat="%Y-%m-%d",
            rangeslider=dict(visible=True, thickness=0.05),
            color="white"
        ),
        yaxis=dict(
            title=dict(text="Silver Price (USD)", font=dict(color="#4A90E2", size=14, family="Arial")),
            showgrid=True,
            gridcolor="rgba(200, 200, 200, 0.2)",
            zeroline=False,
            tickfont=dict(color="#4A90E2", size=13, family="Arial"),
            showspikes=True,
            spikecolor="#4A90E2",
            spikethickness=1,
        ),
        yaxis2=dict(
            title=dict(text="COT Index", font=dict(color="#E74C3C", size=14, family="Arial")),
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
            tickfont=dict(color="#E74C3C", size=13, family="Arial"),
            showspikes=True,
            spikecolor="#E74C3C",
            spikethickness=1,
            range=[0, 100],
            fixedrange=False,
        ),
        hovermode="x",
        hoverlabel=dict(
            align="left",
            font=dict(color="white"),
            bgcolor="rgba(40, 40, 40, 0.8)"
        ),
        legend=dict(
            x=-0.05,
            y=1.4,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(40, 40, 40, 0.7)",
            bordercolor="white",
            font=dict(color="white"),
            borderwidth=1
        )
    )

    app = Dash(__name__)
    app.layout = html.Div([
        html.H1("COT Index for Silver – Non-Commercial Positions", style={
            "textAlign": "center",
            "color": "white",
            "fontFamily": "Arial, sans-serif"
        }),
        dcc.Graph(figure=fig, config={
            "displayModeBar": True,
            "modeBarButtonsToRemove": ["zoom", "zoomIn", "zoomOut", "pan", "resetScale"]
        })
    ], style={
        "backgroundColor": "#181818",
        "padding": "20px",
        "borderRadius": "10px",
        "maxWidth": "1200px",
        "margin": "auto"
    })
    
    if run:
        app.run(debug=True)
    return app

final_df = load_or_update_data()

if __name__ == '__main__':
    my_app = create_dashboard(final_df, run=False)
    port = int(os.environ.get("PORT", 8050))
    my_app.run(debug=True, host="0.0.0.0", port=port)
