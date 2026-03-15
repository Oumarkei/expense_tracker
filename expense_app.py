import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

# ============================
#  CONFIGURATION
# ============================

st.set_page_config(page_title="Expense Tracker", layout="wide")
st.title("💰 Expense Tracker")

PROJECT_START_DATE = datetime(2024, 11, 1)

# ============================
#  DATABASE
# ============================

def get_connection():
    from urllib.parse import urlparse, unquote
    url = st.secrets["database"]["url"]
    p = urlparse(url)
    return psycopg2.connect(
        host=p.hostname,
        port=p.port or 6543,
        user=unquote(p.username),
        password=unquote(p.password),
        dbname=p.path.lstrip("/"),
        sslmode="require"
    )


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS expenses
                 (id SERIAL PRIMARY KEY,
                  description TEXT NOT NULL,
                  amount REAL NOT NULL,
                  category TEXT NOT NULL,
                  date TEXT NOT NULL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS budget
                 (id SERIAL PRIMARY KEY,
                  month TEXT NOT NULL UNIQUE,
                  amount REAL NOT NULL)''')

    conn.commit()
    conn.close()


def get_budget_for_month(year, month):
    conn = get_connection()
    c = conn.cursor()
    month_key = f"{year}-{month:02d}"
    c.execute("SELECT amount FROM budget WHERE month = %s", (month_key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 1000.0


def set_budget_for_month(year, month, amount):
    conn = get_connection()
    c = conn.cursor()
    month_key = f"{year}-{month:02d}"
    c.execute("""
        INSERT INTO budget (month, amount) VALUES (%s, %s)
        ON CONFLICT (month) DO UPDATE SET amount = EXCLUDED.amount
    """, (month_key, amount))
    conn.commit()
    conn.close()


def add_expense(description, amount, category, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO expenses (description, amount, category, date) VALUES (%s, %s, %s, %s)",
              (description, amount, category, date))
    conn.commit()
    conn.close()


def get_expenses_for_month(year, month):
    conn = get_connection()
    c = conn.cursor()
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-31"
    c.execute("""
        SELECT id, description, amount, category, date 
        FROM expenses 
        WHERE date >= %s AND date <= %s
        ORDER BY date DESC
    """, (start, end))
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_expenses():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, description, amount, category, date FROM expenses ORDER BY date DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def delete_expense(expense_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
    conn.commit()
    conn.close()


# ============================
#  INITIALIZE DB
# ============================

init_db()

# ============================
#  SESSION STATE
# ============================

now = datetime.now()

if "selected_year" not in st.session_state:
    st.session_state.selected_year = now.year

if "selected_month" not in st.session_state:
    st.session_state.selected_month = now.month

# ============================
#  SIDEBAR
# ============================

with st.sidebar:
    st.header("⚙️ Settings")

    # ---- Month Selector ----
    st.subheader("📅 Select Month")

    available_months = []
    check = PROJECT_START_DATE
    while check <= datetime(now.year + 1, 12, 31):
        available_months.append((check.year, check.month))
        check = check.replace(month=check.month % 12 + 1, year=check.year + (check.month == 12))

    labels = [f"{datetime(y, m, 1).strftime('%B %Y')}" for y, m in available_months]

    selected_label = st.selectbox(
        "Choose Month",
        options=labels,
        index=labels.index(f"{datetime(st.session_state.selected_year, st.session_state.selected_month, 1).strftime('%B %Y')}"),
    )

    idx = labels.index(selected_label)
    st.session_state.selected_year, st.session_state.selected_month = available_months[idx]

    st.divider()

    # ---- BUDGET FIX (FINAL & 100% RELIABLE) ----
    current_budget = get_budget_for_month(
        st.session_state.selected_year, 
        st.session_state.selected_month
    )

    # Key includes the current budget -> forces widget refresh
    budget_key = f"budget_{st.session_state.selected_year}_{st.session_state.selected_month}_{current_budget}"

    new_budget = st.number_input(
        f"Monthly Budget (MAD) - {selected_label}",
        min_value=0.0,
        value=current_budget,
        step=50.0,
        key=budget_key
    )

    if new_budget != current_budget:
        set_budget_for_month(st.session_state.selected_year, st.session_state.selected_month, new_budget)
        st.success("Budget updated!")
        st.rerun()  # FORCE FULL REFRESH

# ============================
#  LOAD EXPENSES
# ============================

expenses = get_expenses_for_month(st.session_state.selected_year, st.session_state.selected_month)
df = pd.DataFrame(expenses, columns=["id", "description", "amount", "category", "date"]) if expenses else pd.DataFrame()

# ============================
#  MAIN DASHBOARD
# ============================

st.subheader(f"📊 {datetime(st.session_state.selected_year, st.session_state.selected_month, 1).strftime('%B %Y')}")

col1, col2, col3 = st.columns(3)

total_spent = df["amount"].sum() if len(df) > 0 else 0
budget = get_budget_for_month(st.session_state.selected_year, st.session_state.selected_month)
remaining = budget - total_spent
percentage = (total_spent / budget * 100) if budget > 0 else 0

with col1:
    st.metric("Total Spending", f"{total_spent:.2f} MAD", f"{percentage:.1f}%")

with col2:
    st.metric("Monthly Budget", f"{budget:.2f} MAD")

with col3:
    st.metric("Budget Remaining", f"{remaining:.2f} MAD", "🟢" if remaining >= 0 else "🔴")

# ============================
#  BUDGET PROGRESS BAR
# ============================

st.subheader("📊 Budget Status")

if budget > 0:
    progress_value = min(percentage / 100, 1.0)
    col_bar, col_text = st.columns([3, 1])
    with col_bar:
        st.progress(progress_value)
    with col_text:
        if remaining >= 0:
            st.success(f"{remaining:.2f} MAD left", icon="✅")
        else:
            st.error(f"Over budget by {abs(remaining):.2f} MAD", icon="⚠️")
else:
    st.warning("Set a monthly budget first.")

# ============================
#  ADD EXPENSE
# ============================

st.subheader("➕ Add New Expense")
with st.form("add_expense"):
    c1, c2 = st.columns(2)

    with c1:
        desc = st.text_input("Description", placeholder="e.g., Coffee with friend")
        amt = st.number_input("Amount (MAD)", min_value=0.0, step=10.0)

    with c2:
        cat = st.selectbox("Category", ["Food", "Transport", "Shopping", "Entertainment", "Bills", "Health", "Other"])
        date = st.date_input("Date", value=datetime.now())

    if st.form_submit_button("Add"):
        if desc and amt > 0:
            add_expense(desc, amt, cat, date.strftime("%Y-%m-%d"))
            st.success("Expense added!")
            st.rerun()
        else:
            st.error("Fill all fields.")

# ============================
#  EXPENSE LIST
# ============================

st.subheader("📝 Recent Expenses")

if len(df) > 0:
    for _, row in df.iterrows():
        col1, col2, col3, col4, col5 = st.columns([2, 2, 1.5, 1, 0.5])
        col1.write(f"**{row['description']}**")
        col2.write(f"{row['amount']:.2f} MAD")
        col3.write(f"_{row['category']}_")
        col4.write(row["date"])
        if col5.button("🗑️", key=f"del_{row['id']}"):
            delete_expense(row["id"])
            st.rerun()
else:
    st.info("No expenses for this month.")

# ============================
#  VISUALIZATIONS
# ============================

st.subheader("📈 Spending Statistics")

if len(df) > 0:
    df["date"] = pd.to_datetime(df["date"])

    col1, col2 = st.columns(2)
    
    # Category bar chart
    category_spending = df.groupby("category")["amount"].sum().sort_values(ascending=False)
    
    with col1:
        fig1 = px.bar(
            x=category_spending.index,
            y=category_spending.values,
            labels={"x": "Category", "y": "Amount (MAD)"},
            title="💵 Spending by Category",
            color=category_spending.values,
            color_continuous_scale="Viridis"
        )
        fig1.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig1, use_container_width=True)

    # Pie chart
    with col2:
        fig2 = px.pie(
            values=category_spending.values,
            names=category_spending.index,
            title="🥧 Budget Distribution by Category",
            hole=0.3
        )
        fig2.update_layout(height=400)
        st.plotly_chart(fig2, use_container_width=True)

    # Daily trend
    st.subheader("📅 Daily Spending Trend")
    daily = df.groupby("date")["amount"].sum().reset_index()

    fig3 = px.line(
        daily,
        x="date",
        y="amount",
        title="Daily Spending Trend",
        markers=True,
        labels={"date": "Date", "amount": "Amount (MAD)"},
        color_discrete_sequence=["#1f77b4"]
    )
    fig3.update_layout(height=400)
    st.plotly_chart(fig3, use_container_width=True)

    # Cumulative spending
    st.subheader("📊 Cumulative Spending vs Budget")
    daily_sorted = daily.sort_values("date").reset_index(drop=True)
    daily_sorted["cumulative"] = daily_sorted["amount"].cumsum()

    days = len(daily_sorted)
    budget_per_day = budget / 30
    
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=daily_sorted["date"],
        y=daily_sorted["cumulative"],
        mode="lines",
        name="Cumulative Spending",
        line=dict(color="red", width=3)
    ))
    fig4.add_trace(go.Scatter(
        x=daily_sorted["date"],
        y=[budget_per_day * (i + 1) for i in range(days)],
        mode="lines",
        name="Budget Target",
        line=dict(color="green", width=3, dash="dash")
    ))

    fig4.update_layout(
        title="Cumulative Spending vs Budget Target",
        xaxis_title="Date",
        yaxis_title="Amount (MAD)",
        height=400,
        hovermode="x unified"
    )
    st.plotly_chart(fig4, use_container_width=True)

    # Summary stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Highest Expense", f"{df['amount'].max():.2f} MAD")
    with col2:
        st.metric("Average Expense", f"{df['amount'].mean():.2f} MAD")
    with col3:
        st.metric("Total Transactions", len(df))
    with col4:
        top_category = df.groupby("category")["amount"].sum().idxmax()
        st.metric("Top Category", top_category)

# ============================
#  EXPORT
# ============================

st.sidebar.divider()
with st.sidebar:
    st.header("📥 Export Data")

    if st.button("Download Current Month as CSV", width='stretch'):
        if len(df) > 0:
            csv = df[["description", "amount", "category", "date"]].to_csv(index=False)
            st.download_button(
                label="Click to download",
                data=csv,
                file_name=f"expenses_{st.session_state.selected_year}_{st.session_state.selected_month:02d}.csv",
                mime="text/csv"
            )

    if st.button("Download All Data as CSV", width='stretch'):
        all_expenses = get_all_expenses()
        if all_expenses:
            df_all = pd.DataFrame(all_expenses, columns=["id", "description", "amount", "category", "date"])
            csv = df_all[["description", "amount", "category", "date"]].to_csv(index=False)
            st.download_button(
                label="Click to download",
                data=csv,
                file_name=f"all_expenses_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )