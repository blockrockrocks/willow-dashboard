import streamlit as st
st.set_page_config(page_title="Willow Dashboard", layout="wide")

from streamlit_autorefresh import st_autorefresh
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import os
from tinyman.assets import AssetAmount
from tinyman.v2.client import TinymanV2MainnetClient
from algosdk.v2client.algod import AlgodClient

# === CONFIGURATION ===
ALGOD_TOKEN = ""
ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
WALLET_ADDRESS = "7WB2N523IRAVAXUD4HUGPKPDLIS3ZLXW22L4DSHFPMVDPYUKHFDTOUYUWA"

# === INIT CLIENTS ===
algod_client = AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
client = TinymanV2MainnetClient(algod_client=algod_client, user_address=WALLET_ADDRESS)

# === AUTORELOAD EVERY 5 MINUTES ===
st_autorefresh(interval=300000, key="refresh")

# === FETCH WALLET HOLDINGS ===
def get_wallet_holdings(wallet_address):
    info = algod_client.account_info(wallet_address)

    # Include all ASAs
    holdings = {
        a['asset-id']: a['amount']
        for a in info.get('assets', [])
        if a['amount'] > 0
    }

    # ✅ Add native ALGO balance (asset ID 0)
    algo_amount = info.get("amount", 0)
    holdings[0] = algo_amount

    return holdings


# === PORTFOLIO VALUE ===
def fetch_portfolio(wallet_address):
    holdings = get_wallet_holdings(wallet_address)
    breakdown = []
    total_value = 0

    for asset_id, amount in holdings.items():
        asset = client.fetch_asset(asset_id)
        if asset_id == 0:
            value = amount / 1_000_000
        else:
            try:
                pool = client.fetch_pool(client.fetch_asset(0), asset)
                quote = pool.fetch_fixed_input_swap_quote(AssetAmount(asset, amount), slippage=0.01)
                value = float(quote.amount_out.amount) / 1_000_000
            except:
                value = 0

        breakdown.append({
            "Asset": asset.name,
            "ID": asset.id,
            "Amount": amount / (10 ** asset.decimals),
            "Value (ALGO)": round(value, 4)
        })
        total_value += value

    df = pd.DataFrame(breakdown)
    df["% of Portfolio"] = df["Value (ALGO)"] / total_value * 100
    df = df.sort_values("Value (ALGO)", ascending=False)

    return total_value, df

# === LOG PORTFOLIO VALUE ===
def log_portfolio_value(value, filename="portfolio_history.csv"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df_new = pd.DataFrame([{"date": timestamp, "total_value_algo": value}])
    if os.path.exists(filename):
        df_old = pd.read_csv(filename)
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(filename, index=False)

# === CUSTOM STYLES ===
st.markdown("""
    <style>
    body { background-color: #f8f9fa; }
    .big-font { font-size:40px !important; font-weight:700; }
    .small-font { font-size:12px !important; color: #888; }
    .card {
        background-color: white;
        padding: 1.5rem;
        border-radius: 1rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        margin-bottom: 1.5rem;
    }
    </style>
""", unsafe_allow_html=True)

# === HEADER ===
st.title("Willow Portfolio")
st.markdown("<div class='small-font'>Real-time Algorand portfolio tracking</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# === DATA ===
st.markdown("<div class='card'>", unsafe_allow_html=True)
total_value, df = fetch_portfolio(WALLET_ADDRESS)
log_portfolio_value(total_value)

now = datetime.now()
st.markdown(f"<div class='big-font'>Total Value: {total_value:,.2f} ALGO</div>", unsafe_allow_html=True)
st.markdown(f"<div class='small-font'>Updated: {now.strftime('%Y-%m-%d %H:%M:%S')}</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# === LAYOUT ===
col1, col2 = st.columns(2)

with col1:
    st.markdown("<div class='card'><h4>Performance</h4>", unsafe_allow_html=True)
    try:
        hist_df = pd.read_csv("portfolio_history.csv")
        hist_df["date"] = pd.to_datetime(hist_df["date"])

        # Resample to 60-minute intervals using the latest value in each interval
        hist_df.set_index("date", inplace=True)
        hist_df_resampled = hist_df.resample("60min").last().dropna()
        hist_df_resampled.reset_index(inplace=True)

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(hist_df_resampled["date"], hist_df_resampled["total_value_algo"], marker='o', linewidth=2, color="#00b894")
        ax.set_xlabel("Date")
        ax.set_ylabel("Total Value (ALGO)")

        ymin = hist_df_resampled["total_value_algo"].min() * 0.97
        ymax = hist_df_resampled["total_value_algo"].max() * 1.03
        ax.set_ylim(ymin, ymax)

        ax.grid(True, linestyle='--', alpha=0.3)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        fig.autofmt_xdate()

        st.pyplot(fig)
    except Exception as e:
        st.warning(f"Could not load history: {e}")
    st.markdown("</div>", unsafe_allow_html=True)

with col2:
    st.markdown("<div class='card'><h4>Allocation</h4>", unsafe_allow_html=True)
    top_n = 5
    top_assets = df.head(top_n).copy()
    rest = df.iloc[top_n:]
    rest_value = rest["Value (ALGO)"].sum()

    if rest_value > 0:
        top_assets = pd.concat([
            top_assets,
            pd.DataFrame([{"Asset": "Others", "Value (ALGO)": rest_value}])
        ], ignore_index=True)

    fig, ax = plt.subplots(figsize=(6, 6))
    wedges, texts = ax.pie(
        top_assets["Value (ALGO)"],
        labels=top_assets["Asset"],
        startangle=90,
        wedgeprops={"width": 0.4, "edgecolor": "w"},
        pctdistance=0.85,
        labeldistance=1.05
    )

    total = sum(top_assets["Value (ALGO)"])
    for i, p in enumerate(wedges):
        ang = (p.theta2 - p.theta1)/2. + p.theta1
        y = np.sin(np.deg2rad(ang))
        x = np.cos(np.deg2rad(ang))
        percentage = top_assets["Value (ALGO)"].iloc[i] / total * 100
        ax.annotate(f"{percentage:.1f}%", xy=(x*0.75, y*0.75), ha='center', va='center', fontsize=10, color="white", weight="bold")

    ax.axis("equal")
    st.pyplot(fig)
    st.markdown("</div>", unsafe_allow_html=True)

# === TABLE ===
st.markdown("<div class='card'><h4>Portfolio Details</h4>", unsafe_allow_html=True)
st.dataframe(df, use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)
