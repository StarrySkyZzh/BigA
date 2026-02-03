import streamlit as st
import akshare as ak
import pandas as pd
import json
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import os

# --- 环境变量设置：防止代理导致连接中断 ---
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

# --- 页面配置 ---
st.set_page_config(
    page_title="MyStock 极简稳定版",
    page_icon="🛡️",
    layout="wide"
)


# --- 工具函数 ---

def load_holdings(file_path='holdings.json'):
    """加载持仓"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        st.error("❌ 找不到 holdings.json，请先创建。")
        return []


def get_stock_data_individual(code, name):
    """
    【方案三核心】
    单独获取某一只股票的最新数据。
    使用 K线接口 (daily) 获取最近几日数据，最后一行即为当前最新状态。
    """
    try:
        # 获取最近5天的日线数据
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")

        # 这个接口比全市场接口稳定得多
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")

        if df.empty:
            return None

        # 提取最新数据
        latest_row = df.iloc[-1]  # 最后一行（如果是盘中，这就是最新价）

        # 计算涨跌幅
        # 如果有昨天的数据，用 (今天最新 - 昨天收盘) / 昨天收盘
        if len(df) >= 2:
            prev_close = df.iloc[-2]['收盘']
            current_price = latest_row['收盘']
            pct_change = (current_price - prev_close) / prev_close * 100
            day_profit_per_share = current_price - prev_close
        else:
            # 如果是新股或数据不足，暂时无法计算涨跌
            current_price = latest_row['收盘']
            pct_change = 0.0
            day_profit_per_share = 0.0

        return {
            "code": code,
            "name": name,
            "current_price": float(current_price),
            "pct_change": float(pct_change),
            "day_profit_per_share": float(day_profit_per_share),
            "history_df": df  # 顺便把历史数据也返回，画图用
        }

    except Exception as e:
        print(f"获取 {code} 失败: {e}")
        return None


# --- 主逻辑 ---

def main():
    st.title("🛡️ MyStock 驾驶舱 (点对点查询版)")
    st.caption("方案三：采用单股轮询机制，彻底解决全市场接口连接中断问题。")

    # 1. 加载持仓
    holdings = load_holdings()
    if not holdings:
        st.stop()

    if st.button("🔄 刷新数据"):
        st.rerun()

    # 2. 循环获取数据 (带进度条)
    portfolio_data = []
    total_asset = 0.0
    total_profit = 0.0
    total_day_profit = 0.0

    # 进度条
    progress_bar = st.progress(0)
    status_text = st.empty()

    # 用字典存储每一只股票的历史数据，供下方画图使用，避免重复请求
    history_cache = {}

    for i, stock in enumerate(holdings):
        code = stock['code']
        name = stock['name']

        # 更新进度提示
        status_text.text(f"正在同步: {name} ({code})...")
        progress_bar.progress((i + 1) / len(holdings))

        # === 核心调用 ===
        data = get_stock_data_individual(code, name)

        if data:
            # 存入缓存供画图使用
            history_cache[code] = data['history_df']

            # 计算账户维度数据
            qty = stock['quantity']
            cost = stock['cost_price']
            current = data['current_price']

            market_val = current * qty
            profit = (current - cost) * qty
            profit_pct = (current - cost) / cost * 100
            day_profit = data['day_profit_per_share'] * qty

            # 累加总数
            total_asset += market_val
            total_profit += profit
            total_day_profit += day_profit

            # 风险判断
            risk_status = "安全"
            distance = (profit_pct / 100) - stock['stop_loss_pct']
            if distance < 0:
                risk_status = "⚠️ 触发止损"
            elif distance < 0.03:
                risk_status = "⚡ 接近止损"

            portfolio_data.append({
                "代码": code,
                "名称": name,
                "数量": qty,
                "成本": cost,
                "现价": current,
                "涨跌幅": f"{data['pct_change']:.2f}%",
                "持仓盈亏": profit,
                "盈亏率%": profit_pct,
                "当日盈亏": day_profit,
                "风险状态": risk_status,
                "止损线%": stock['stop_loss_pct'] * 100
            })

        # 礼貌性休眠，防止请求过快 (方案三的关键)
        time.sleep(0.2)

        # 循环结束，清理进度条
    status_text.empty()
    progress_bar.empty()

    if not portfolio_data:
        st.error("无法获取任何数据，请检查网络连接。")
        st.stop()

    # 3. 显示顶部卡片
    c1, c2, c3 = st.columns(3)
    c1.metric("💰 总资产", f"¥{total_asset:,.0f}")
    c2.metric("📈 总盈亏", f"¥{total_profit:,.0f}", delta=f"{total_profit:,.0f}")
    c3.metric("🔥 今日波动", f"¥{total_day_profit:,.0f}", delta=f"{total_day_profit:,.0f}", delta_color="normal")

    st.markdown("---")

    # 4. 显示表格
    df_display = pd.DataFrame(portfolio_data)

    def highlight(row):
        val = row['风险状态']
        if '触发止损' in val: return ['background-color: #ffcccc'] * len(row)
        if '接近止损' in val: return ['background-color: #fff4cc'] * len(row)
        return [''] * len(row)

    st.subheader("📋 持仓明细")
    st.dataframe(
        df_display.style.apply(highlight, axis=1).format({
            "成本": "{:.2f}",
            "现价": "{:.2f}",
            "持仓盈亏": "{:.0f}",
            "当日盈亏": "{:.0f}",
            "盈亏率%": "{:.2f}%",
            "止损线%": "{:.0f}%"
        }),
        use_container_width=True,
        hide_index=True
    )

    # 5. 画图 (直接使用刚才循环里取到的数据，不再重新请求)
    st.markdown("---")
    st.subheader("📊 个股趋势")

    col_sel, col_chart = st.columns([1, 3])
    with col_sel:
        sel_name = st.selectbox("选择股票", [s['名称'] for s in portfolio_data])
        sel_code = next(item['代码'] for item in portfolio_data if item['名称'] == sel_name)
        sel_cost = next(item['cost_price'] for item in holdings if item['code'] == sel_code)

    with col_chart:
        if sel_code in history_cache:
            df_hist = history_cache[sel_code]

            # 计算简单均线
            df_hist['MA5'] = df_hist['收盘'].rolling(5).mean()
            df_hist['MA10'] = df_hist['收盘'].rolling(10).mean()

            # 画图
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df_hist['日期'],
                open=df_hist['开盘'], high=df_hist['最高'],
                low=df_hist['最低'], close=df_hist['收盘'],
                name='K线'
            ))
            fig.add_trace(
                go.Scatter(x=df_hist['日期'], y=df_hist['MA5'], line=dict(color='orange', width=1), name='MA5'))
            fig.add_trace(
                go.Scatter(x=df_hist['日期'], y=df_hist['MA10'], line=dict(color='blue', width=1), name='MA10'))
            fig.add_hline(y=sel_cost, line_dash="dash", line_color="red", annotation_text="成本线")

            fig.update_layout(height=450, margin=dict(l=10, r=10, t=30, b=10), title=f"{sel_name} 走势图")
            st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
