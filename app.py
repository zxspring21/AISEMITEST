"""
Streamlit dashboard for STDF DB: lot-to-lot, wafer-to-wafer, die-to-die analysis,
fail pareto, TestSuite→TestItem mapping, wafer diff comparison, bin summary, equipment.
"""
import io
import tempfile
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date, timedelta

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from config import DATABASE_URL
from db_models import (
    get_engine, init_db,
    Lot, Wafer, Die, Bin, TestItem, TestProgram, TestSuite, TestDefinition, SiteEquipment,
    Company, Product, Stage,
)


def _safe_div(a, b, default=0.0):
    """Avoid division by zero."""
    if b is None or b == 0:
        return default
    try:
        return float(a) / float(b)
    except (TypeError, ZeroDivisionError):
        return default


def _stats_table(df, value_col, subgroup_col=None):
    """Return a summary stats DataFrame: count, mean, std, min, max, (optional) per subgroup."""
    if df is None or df.empty or value_col not in df.columns:
        return None
    try:
        if subgroup_col and subgroup_col in df.columns:
            agg = df.groupby(subgroup_col)[value_col].agg(["count", "mean", "std", "min", "max"])
            agg = agg.rename(columns={"count": "N", "mean": "Mean", "std": "Std", "min": "Min", "max": "Max"})
            agg["Std"] = agg["Std"].fillna(0)
            return agg.reset_index()
        else:
            s = df[value_col].dropna()
            if s.empty:
                return None
            return pd.DataFrame([{
                "N": len(s), "Mean": s.mean(), "Std": s.std() if len(s) > 1 else 0,
                "Min": s.min(), "Max": s.max(),
            }])
    except Exception:
        return None


def _p_chart(subgroup_labels, defect_counts, total_counts, title="p-Chart (Proportion Defective)"):
    """Plot p-chart: proportion defective per subgroup with UCL/LCL."""
    if not subgroup_labels or not defect_counts or not total_counts:
        return None
    n = len(subgroup_labels)
    if n != len(defect_counts) or n != len(total_counts):
        return None
    p_vals = [_safe_div(d, t) for d, t in zip(defect_counts, total_counts)]
    p_bar = sum(defect_counts) / max(sum(total_counts), 1)
    # UCL/LCL per subgroup (n varies)
    ucl = []
    lcl = []
    for i in range(n):
        ni = max(total_counts[i], 1)
        sigma = (p_bar * (1 - p_bar) / ni) ** 0.5
        ucl.append(min(1.0, p_bar + 3 * sigma))
        lcl.append(max(0.0, p_bar - 3 * sigma))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(n)), y=p_vals, mode="lines+markers", name="p", line=dict(color="blue")))
    fig.add_trace(go.Scatter(x=list(range(n)), y=ucl, mode="lines", name="UCL", line=dict(dash="dash", color="red")))
    fig.add_trace(go.Scatter(x=list(range(n)), y=lcl, mode="lines", name="LCL", line=dict(dash="dash", color="red")))
    fig.add_hline(y=p_bar, line_dash="dot", line_color="gray", annotation_text=f"p̄={p_bar:.4f}")
    fig.update_layout(
        title=title,
        xaxis=dict(tickvals=list(range(n)), ticktext=[str(l) for l in subgroup_labels], tickangle=-45),
        yaxis_title="Proportion defective",
        showlegend=True,
        height=400,
    )
    return fig


def _lots_query(session: Session, company_id=None, product_id=None, stage_id=None, test_program_id=None, time_start=None, time_end=None):
    """Build Lot query filtered by Company/Product/Stage/TestProgram and optional lot start_t time range."""
    q = session.query(Lot)
    if test_program_id is not None:
        q = q.filter(Lot.test_program_id == test_program_id)
    elif stage_id is not None:
        q = q.join(TestProgram).filter(TestProgram.stage_id == stage_id)
    elif product_id is not None:
        q = q.join(TestProgram).join(Stage).filter(Stage.product_id == product_id)
    elif company_id is not None:
        q = q.join(TestProgram).join(Stage).join(Product).filter(Product.company_id == company_id)
    if time_start is not None:
        if isinstance(time_start, date) and not isinstance(time_start, datetime):
            time_start = datetime.combine(time_start, datetime.min.time())
        q = q.filter(Lot.start_t >= time_start)
    if time_end is not None:
        if isinstance(time_end, date) and not isinstance(time_end, datetime):
            time_end = datetime.combine(time_end, datetime.max.time())
        q = q.filter(Lot.start_t <= time_end)
    return q


def _sidebar_filters(session: Session):
    """Render Company/Product/Stage/TestProgram and time range in sidebar; return filter dict and update session_state."""
    st.sidebar.markdown("---")
    st.sidebar.subheader("Filters (all pages)")
    for key in ["filter_company_id", "filter_product_id", "filter_stage_id", "filter_test_program_id", "filter_time_start", "filter_time_end"]:
        if key not in st.session_state:
            st.session_state[key] = None
    companies = session.query(Company).order_by(Company.name).all()
    company_options = [(None, "— All —")] + [(c.id, c.name) for c in companies]
    sel_company = st.sidebar.selectbox(
        "Company",
        range(len(company_options)),
        format_func=lambda i: company_options[i][1],
        key="sb_company",
    )
    company_id = company_options[sel_company][0] if company_options else None
    st.session_state["filter_company_id"] = company_id

    products = session.query(Product).filter(Product.company_id == company_id).order_by(Product.name).all() if company_id else session.query(Product).order_by(Product.name).all()
    product_options = [(None, "— All —")] + [(p.id, p.name) for p in products]
    sel_product = st.sidebar.selectbox("Product", range(len(product_options)), format_func=lambda i: product_options[i][1], key="sb_product")
    product_id = product_options[sel_product][0] if product_options else None
    st.session_state["filter_product_id"] = product_id

    stages = session.query(Stage).filter(Stage.product_id == product_id).order_by(Stage.name).all() if product_id else session.query(Stage).order_by(Stage.name).all()
    stage_options = [(None, "— All —")] + [(s.id, s.name) for s in stages]
    sel_stage = st.sidebar.selectbox("Stage", range(len(stage_options)), format_func=lambda i: stage_options[i][1], key="sb_stage")
    stage_id = stage_options[sel_stage][0] if stage_options else None
    st.session_state["filter_stage_id"] = stage_id

    progs = session.query(TestProgram).filter(TestProgram.stage_id == stage_id).order_by(TestProgram.name).all() if stage_id else session.query(TestProgram).order_by(TestProgram.name).all()
    prog_options = [(None, "— All —")] + [(p.id, f"{p.name} ({p.revision or '-'})") for p in progs]
    sel_prog = st.sidebar.selectbox("Test Program", range(len(prog_options)), format_func=lambda i: prog_options[i][1], key="sb_prog")
    test_program_id = prog_options[sel_prog][0] if prog_options else None
    st.session_state["filter_test_program_id"] = test_program_id

    st.sidebar.markdown("**Time range (lot start)**")
    use_time = st.sidebar.checkbox("Filter by time", value=False, key="sb_use_time")
    if use_time:
        ts = st.sidebar.date_input("Start date", value=date.today() - timedelta(days=30), key="sb_time_start")
        te = st.sidebar.date_input("End date", value=date.today(), key="sb_time_end")
        st.session_state["filter_time_start"] = ts
        st.session_state["filter_time_end"] = te
    else:
        st.session_state["filter_time_start"] = None
        st.session_state["filter_time_end"] = None

    return {
        "company_id": st.session_state["filter_company_id"],
        "product_id": st.session_state["filter_product_id"],
        "stage_id": st.session_state["filter_stage_id"],
        "test_program_id": st.session_state["filter_test_program_id"],
        "time_start": st.session_state["filter_time_start"],
        "time_end": st.session_state["filter_time_end"],
    }


def get_session():
    engine = get_engine()
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=engine)()


def load_stdf_ui():
    st.subheader("Load STDF file")
    stdf_file = st.file_uploader("Choose STDF file", type=["stdf", "std"])
    if stdf_file:
        company = st.text_input("Company (optional)", value="DefaultCompany")
        product = st.text_input("Product (optional)", value="")
        stage = st.text_input("Stage (optional)", value="")
        if st.button("Load into DB"):
            try:
                with tempfile.NamedTemporaryFile(suffix=".stdf", delete=False) as tmp:
                    tmp.write(stdf_file.getvalue())
                    tmp_path = tmp.name
                from stdf_loader import load_stdf
                load_stdf(tmp_path, company_name=company or None, product_name=product or None, stage_name=stage or None)
                Path(tmp_path).unlink(missing_ok=True)
                st.success("STDF loaded successfully.")
            except Exception as e:
                st.error(str(e))


def run_sql(df_placeholder, session: Session, sql: str):
    try:
        result = session.execute(text(sql))
        rows = result.fetchall()
        if result.keys():
            df = pd.DataFrame(rows, columns=list(result.keys()))
            df_placeholder.dataframe(df, use_container_width=True)
            return df
    except Exception as e:
        st.error(str(e))
    return None


def _get_filters():
    """Read current filter from session_state (set by sidebar)."""
    return {
        "company_id": st.session_state.get("filter_company_id"),
        "product_id": st.session_state.get("filter_product_id"),
        "stage_id": st.session_state.get("filter_stage_id"),
        "test_program_id": st.session_state.get("filter_test_program_id"),
        "time_start": st.session_state.get("filter_time_start"),
        "time_end": st.session_state.get("filter_time_end"),
    }


def dashboard_home(session: Session):
    st.subheader("Overview")
    try:
        filters = _get_filters()
        lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
        lots_list = lots_q.all()
        lots = len(lots_list)
        wafers = session.query(Wafer).filter(Wafer.lot_id.in_([l.id for l in lots_list])).count() if lots_list else 0
        dies = session.query(Die).filter(Die.lot_id.in_([l.id for l in lots_list])).count() if lots_list else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("Lots", lots)
        col2.metric("Wafers", wafers)
        col3.metric("Dies", dies)

        st.markdown("#### Hierarchy (Company → Product → Stage → Test Program)")
        companies = session.query(Company).order_by(Company.name).all()
        for c in companies:
            with st.expander(f"**{c.name}** (Company)"):
                products = session.query(Product).filter_by(company_id=c.id).order_by(Product.name).all()
                for p in products:
                    with st.expander(f"  {p.name} (Product)", expanded=False):
                        stages = session.query(Stage).filter_by(product_id=p.id).order_by(Stage.name).all()
                        for s in stages:
                            progs = session.query(TestProgram).filter_by(stage_id=s.id).order_by(TestProgram.name).all()
                            for prog in progs:
                                n_lot = session.query(Lot).filter_by(test_program_id=prog.id).count()
                                n_wafer = session.query(Wafer).join(Lot).filter(Lot.test_program_id == prog.id).count()
                                n_die = session.query(Die).join(Lot).filter(Lot.test_program_id == prog.id).count()
                                st.caption(f"  {s.name} → **{prog.name}** ({prog.revision or '-'}): {n_lot} lots, {n_wafer} wafers, {n_die} dies")

        st.markdown("#### Test time summary (filtered)")
        if lots_list:
            rows = []
            for l in lots_list[:50]:
                die_times = session.query(Die.test_t).filter_by(lot_id=l.id).all()
                total_ms = sum((d[0] or 0) for d in die_times)
                n_wafer = session.query(Wafer).filter_by(lot_id=l.id).count()
                rows.append({
                    "Lot": l.lot_id,
                    "Part type": l.part_typ or "-",
                    "Wafers": n_wafer,
                    "Dies": len(die_times),
                    "Total test time (ms)": total_ms,
                    "Lot start": l.start_t.strftime("%Y-%m-%d %H:%M") if l.start_t else "-",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)
            if len(lots_list) > 50:
                st.caption(f"Showing first 50 of {len(lots_list)} lots.")
        else:
            st.info("No lots match current filters.")
    except Exception as e:
        st.error(f"Dashboard: {e}")


def lot_to_lot(session: Session):
    st.subheader("Lot-to-Lot analysis")
    filters = _get_filters()
    lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
    lots = lots_q.all()
    if not lots:
        st.info("No lot data (or none match filters). Load STDF or adjust Company/Product/Stage/Test Program / Time range.")
        return
    lot_ids = [l.lot_id for l in lots]
    selected = st.multiselect("Select lots", lot_ids, default=lot_ids[: min(5, len(lot_ids))])
    if not selected:
        return
    rows = []
    for lot in session.query(Lot).filter(Lot.lot_id.in_(selected)):
        dies_in_lot = session.query(Die).filter_by(lot_id=lot.id)
        total = dies_in_lot.count()
        total_ms = session.query(func.coalesce(func.sum(Die.test_t), 0)).filter_by(lot_id=lot.id).scalar() or 0
        rows.append({"Lot": lot.lot_id, "Total dies": total, "Part type": lot.part_typ or "-", "Total test time (ms)": total_ms, "Lot start": lot.start_t.strftime("%Y-%m-%d %H:%M") if lot.start_t else "-"})
    df = pd.DataFrame(rows)
    if df.empty:
        return
    st.dataframe(df, use_container_width=True)
    fig = px.bar(df, x="Lot", y="Total dies", title="Die count per lot", color="Total dies")
    st.plotly_chart(fig, use_container_width=True)

    # p-Chart: fail rate per lot (proportion defective)
    st.markdown("#### p-Chart (Fail rate per lot)")
    try:
        lot_fail = []
        lot_total = []
        lot_labels = []
        for lot in session.query(Lot).filter(Lot.lot_id.in_(selected)):
            total = session.query(Die).filter_by(lot_id=lot.id).count()
            if total == 0:
                continue
            fails = session.query(Die.id).join(TestItem, TestItem.die_id == Die.id).filter(
                Die.lot_id == lot.id, TestItem.pass_fail == 1
            ).distinct().count()
            lot_labels.append(lot.lot_id)
            lot_total.append(total)
            lot_fail.append(fails)
        if lot_labels and lot_total:
            pfig = _p_chart(lot_labels, lot_fail, lot_total, title="p-Chart: Proportion defective per Lot")
            if pfig:
                st.plotly_chart(pfig, use_container_width=True)
        st.caption("UCL/LCL = p̄ ± 3σ (per subgroup n).")
    except Exception as e:
        st.warning(f"p-Chart (lot): {e}")

    # Test item dropdown: select which parametric test to compare
    ptr_tests = session.query(TestItem.test_num, TestItem.test_txt).filter(
        TestItem.test_type == "PTR", TestItem.result != None
    ).distinct().limit(200).all()
    if not ptr_tests:
        st.caption("No PTR test results for comparison.")
        return
    test_options = [(t[0], (t[1] or f"Test#{t[0]}").strip() or f"Test#{t[0]}") for t in ptr_tests]
    sel_test_idx = st.selectbox(
        "Select parametric test to compare (box plot & stats per lot)",
        range(len(test_options)),
        format_func=lambda i: test_options[i][1],
        help="Choose one PTR test; the chart shows its measured value distribution per selected lot.",
    )
    if sel_test_idx is None:
        return
    test_num, test_name = ptr_tests[sel_test_idx][0], test_options[sel_test_idx][1]
    try:
        q = session.query(Lot.lot_id.label("lot_id_str"), TestItem.result).join(Die, Die.lot_id == Lot.id).join(
            TestItem, TestItem.die_id == Die.id
        ).filter(
            TestItem.test_num == test_num, TestItem.test_type == "PTR", Lot.lot_id.in_(selected), TestItem.result != None
        )
        rows_pt = [(r.lot_id_str, r.result) for r in q]
        if not rows_pt:
            st.info(f"No data for {test_name} in selected lots.")
            return
        dfp = pd.DataFrame(rows_pt, columns=["Lot", "Result"])
        fig2 = px.box(dfp, x="Lot", y="Result", title=f"Lot-to-Lot: {test_name}")
        st.plotly_chart(fig2, use_container_width=True)
        # Statistics per lot for selected test
        st.markdown("#### Statistical summary (selected test per lot)")
        stats_df = _stats_table(dfp, "Result", "Lot")
        if stats_df is not None and not stats_df.empty:
            st.dataframe(stats_df, use_container_width=True)
        # Overall stats
        st.markdown("#### Overall statistics (all selected lots)")
        overall = _stats_table(dfp, "Result", None)
        if overall is not None:
            st.dataframe(overall, use_container_width=True)
    except Exception as e:
        st.error(f"Lot-to-Lot test plot: {e}")


# ---------- Fail Pareto ----------
def fail_pareto(session: Session):
    st.subheader("Fail Pareto Analysis")
    level = st.radio("Level", ["Die", "Wafer"], horizontal=True)
    filters = _get_filters()
    lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
    lots = lots_q.all()
    if not lots:
        st.info("No lot data (or none match filters). Adjust Company/Product/Stage/Test Program / Time range.")
        return
    lot_ids = [l.lot_id for l in lots]
    sel_lot = st.selectbox("Lot", lot_ids)
    lot = session.query(Lot).filter_by(lot_id=sel_lot).first()
    if not lot:
        return
    if level == "Die":
        # Pareto by failing test (test_txt + pass_fail=1)
        fails = session.query(TestItem.test_num, TestItem.test_txt, TestItem.test_type).filter(
            TestItem.pass_fail == 1
        ).join(Die).filter(Die.lot_id == lot.id).all()
        if not fails:
            st.info("No failing dies in this lot.")
            return
        cnt = defaultdict(int)
        for tn, tt, typ in fails:
            key = tt or f"Test#{tn}"
            cnt[key] += 1
        df = pd.DataFrame([{"Test": k, "Fail count": v} for k, v in sorted(cnt.items(), key=lambda x: -x[1])])
        st.dataframe(df, use_container_width=True)
        fig = px.bar(df.head(20), x="Test", y="Fail count", title="Die-level Fail Pareto (top 20)")
        fig.update_xaxes(tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
        # Pareto by bin
        bins = session.query(Die.hard_bin, Bin.hard_bin_name).select_from(Die).outerjoin(Bin, Bin.die_id == Die.id).filter(
            Die.lot_id == lot.id, Die.hard_bin != None
        ).all()
        bin_cnt = defaultdict(lambda: (0, ""))
        for hb, hn in bins:
            bin_cnt[hb] = (bin_cnt[hb][0] + 1, hn or f"Bin{hb}")
        dfb = pd.DataFrame([{"Bin": v[1] or f"Bin{k}", "Count": v[0]} for k, v in sorted(bin_cnt.items(), key=lambda x: -x[1][0])])
        if not dfb.empty:
            figb = px.bar(dfb.head(15), x="Bin", y="Count", title="Die-level Bin Pareto (top 15)")
            st.plotly_chart(figb, use_container_width=True)
    else:
        # Wafer-level: which tests fail most across wafers, which bins dominate
        wafers = session.query(Wafer).filter_by(lot_id=lot.id).all()
        if not wafers:
            st.info("No wafers.")
            return
        wafer_ids = [w.id for w in wafers]
        fail_by_test = defaultdict(int)
        fail_by_bin = defaultdict(int)
        for wid in wafer_ids:
            dies = session.query(Die.id, Die.hard_bin).filter_by(wafer_id=wid).all()
            die_ids = [d.id for d in dies]
            for ti in session.query(TestItem).filter(TestItem.die_id.in_(die_ids), TestItem.pass_fail == 1).all():
                fail_by_test[ti.test_txt or f"Test#{ti.test_num}"] += 1
            for d in dies:
                if d.hard_bin is not None:
                    fail_by_bin[f"Bin{d.hard_bin}"] += 1
        df = pd.DataFrame([{"Test": k, "Fail count": v} for k, v in sorted(fail_by_test.items(), key=lambda x: -x[1])]).head(20)
        if not df.empty:
            fig = px.bar(df, x="Test", y="Fail count", title="Wafer-level Fail Pareto (top 20)")
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        dfb = pd.DataFrame([{"Bin": k, "Count": v} for k, v in sorted(fail_by_bin.items(), key=lambda x: -x[1])]).head(15)
        if not dfb.empty:
            figb = px.bar(dfb, x="Bin", y="Count", title="Wafer-level Bin Pareto")
            st.plotly_chart(figb, use_container_width=True)


# ---------- TestSuite → TestItem mapping ----------
def test_suite_items(session: Session):
    st.subheader("TestSuite → TestItem mapping")
    suites = session.query(TestSuite).join(TestProgram).all()
    if not suites:
        st.info("No test suites. Load STDF with TSR records.")
        return
    suite_options = [(s.id, s.name, s.test_program.name) for s in suites]
    sel = st.selectbox("TestSuite", range(len(suite_options)), format_func=lambda i: f"{suite_options[i][1]} ({suite_options[i][2]})")
    if sel is None:
        return
    suite_id = suite_options[sel][0]
    defs = session.query(TestDefinition).filter_by(test_suite_id=suite_id).order_by(TestDefinition.test_num).all()
    if defs:
        df = pd.DataFrame([{
            "Test #": d.test_num, "Type": d.test_type or "-", "Name": d.test_nam or "-",
            "Exec cnt": d.exec_cnt, "Fail cnt": d.fail_cnt, "Alarm cnt": d.alrm_cnt
        } for d in defs])
        st.dataframe(df, use_container_width=True)
    # TestItems belonging to this suite (sample)
    items = session.query(TestItem).filter(TestItem.test_suite_id == suite_id).limit(500).all()
    st.caption(f"TestItem count in suite (sample 500): {len(items)}")
    if items:
        dfi = pd.DataFrame([{
            "Die id": ti.die_id, "Test #": ti.test_num, "Type": ti.test_type,
            "Result": ti.result, "Pass/Fail": "Fail" if ti.pass_fail == 1 else ("Pass" if ti.pass_fail == 0 else "-")
        } for ti in items[:50]])
        st.dataframe(dfi, use_container_width=True)


def _wafer_map_bin_fig(df_die, title, show_bin_label=True, highlight_xy=None):
    """Draw a single wafer map with bin color and optional bin labels / highlight."""
    if df_die is None or df_die.empty:
        return None
    try:
        df = df_die.copy()
        df["x"] = pd.to_numeric(df["x"], errors="coerce").fillna(0)
        df["y"] = pd.to_numeric(df["y"], errors="coerce").fillna(0)
        df["bin_str"] = df["hard_bin"].astype(str)
        fig = go.Figure()
        bins = df["hard_bin"].dropna().unique()
        colors = px.colors.qualitative.Set2 + px.colors.qualitative.Pastel
        if len(bins) == 0:
            fig.add_trace(go.Scatter(
                x=df["x"], y=df["y"], mode="markers", name="Die",
                marker=dict(size=8, symbol="square", color="lightblue"),
            ))
        else:
            for i, b in enumerate(bins):
                sub = df[df["hard_bin"] == b]
                if sub.empty:
                    continue
                fig.add_trace(go.Scatter(
                    x=sub["x"], y=sub["y"], mode="markers" + ("+text" if show_bin_label and len(sub) <= 200 else ""),
                    name=f"Bin {b}", marker=dict(size=10, symbol="square", color=colors[i % len(colors)]),
                    text=sub["bin_str"] if show_bin_label and len(sub) <= 200 else None,
                    textposition="top center", textfont=dict(size=8),
                ))
        if highlight_xy:
            hx, hy = zip(*highlight_xy) if highlight_xy else ([], [])
            fig.add_trace(go.Scatter(
                x=list(hx), y=list(hy), mode="markers", name="Diff",
                marker=dict(size=14, symbol="x-open", color="red", line=dict(width=2)),
            ))
        fig.update_layout(
            title=title, xaxis_title="X", yaxis_title="Y",
            showlegend=True, height=400, yaxis=dict(scaleanchor="x", scaleratio=1),
        )
        return fig
    except Exception:
        return None


# ---------- Wafer-to-Wafer with diff comparison ----------
def wafer_to_wafer(session: Session):
    st.subheader("Wafer-to-Wafer analysis")
    filters = _get_filters()
    lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
    lots_with_wafer = lots_q.join(Wafer).distinct().all()
    if not lots_with_wafer:
        st.info("No wafer data (or none match filters). Adjust Company/Product/Stage/Test Program / Time range.")
        return
    lot_options = [(l.id, l.lot_id) for l in lots_with_wafer]
    sel_idx = st.selectbox("Lot", range(len(lot_options)), format_func=lambda i: lot_options[i][1])
    if sel_idx is None:
        return
    chosen_lot_id = lot_options[sel_idx][0]
    wafers_in_lot = session.query(Wafer).filter_by(lot_id=chosen_lot_id).all()
    if not wafers_in_lot:
        st.info("No wafers in this lot.")
        return
    rows = []
    for w in wafers_in_lot:
        part_cnt = w.part_cnt or 0
        good_cnt = w.good_cnt or 0
        total_ms = session.query(func.coalesce(func.sum(Die.test_t), 0)).filter_by(wafer_id=w.id).scalar() or 0
        rows.append({
            "Wafer": w.wafer_id, "Parts": part_cnt, "Good": good_cnt,
            "Yield %": _safe_div(good_cnt, part_cnt, 0) * 100,
            "Total test time (ms)": total_ms,
            "Wafer start": w.start_t.strftime("%Y-%m-%d %H:%M") if w.start_t else "-",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
    if not df.empty and "Yield %" in df.columns:
        fig = px.bar(df, x="Wafer", y="Yield %", title="Wafer yield")
        st.plotly_chart(fig, use_container_width=True)

    # p-Chart: fail rate per wafer
    st.markdown("#### p-Chart (Fail rate per wafer)")
    try:
        w_labels, w_fail, w_total = [], [], []
        for w in wafers_in_lot:
            total = session.query(Die).filter_by(wafer_id=w.id).count()
            if total == 0:
                continue
            fails = session.query(Die.id).join(TestItem, TestItem.die_id == Die.id).filter(
                Die.wafer_id == w.id, TestItem.pass_fail == 1
            ).distinct().count()
            w_labels.append(w.wafer_id)
            w_total.append(total)
            w_fail.append(fails)
        if w_labels and w_total:
            pfig = _p_chart(w_labels, w_fail, w_total, title="p-Chart: Proportion defective per Wafer")
            if pfig:
                st.plotly_chart(pfig, use_container_width=True)
        st.caption("UCL/LCL = p̄ ± 3σ (per subgroup n).")
    except Exception as e:
        st.warning(f"p-Chart (wafer): {e}")

    # Statistics: yield / fail per wafer
    st.markdown("#### Statistics (per wafer)")
    try:
        stat_rows = []
        for w in wafers_in_lot:
            total = session.query(Die).filter_by(wafer_id=w.id).count()
            if total == 0:
                continue
            fails = session.query(Die.id).join(TestItem, TestItem.die_id == Die.id).filter(
                Die.wafer_id == w.id, TestItem.pass_fail == 1
            ).distinct().count()
            stat_rows.append({
                "Wafer": w.wafer_id, "N": total, "Fail": fails,
                "p": _safe_div(fails, total), "Yield%": _safe_div(w.good_cnt, w.part_cnt, 0) * 100,
            })
        if stat_rows:
            st.dataframe(pd.DataFrame(stat_rows), use_container_width=True)
    except Exception as e:
        st.warning(f"Stats: {e}")

    # Multi-wafer comparison: side-by-side wafer maps with bin marked
    st.markdown("---")
    st.subheader("Multi-Wafer comparison (left vs right)")
    wafer_choices = [(w.id, w.wafer_id) for w in wafers_in_lot]
    # multiselect returns list of selected items (tuples)
    selected_wafers = st.multiselect(
        "Select 2 wafers to compare (left = first, right = second)",
        options=wafer_choices,
        default=wafer_choices[:2] if len(wafer_choices) >= 2 else wafer_choices,
        format_func=lambda x: x[1],
    )
    if len(selected_wafers) >= 2:
        # Use first two as left/right
        left_id, left_label = selected_wafers[0][0], selected_wafers[0][1]
        right_id, right_label = selected_wafers[1][0], selected_wafers[1][1]
        wafer_ids = [left_id, right_id]

        # Build (x,y) -> bin per wafer
        data_by_wafer = {}
        for wid in wafer_ids:
            dies = session.query(Die).filter_by(wafer_id=wid).all()
            dmap = {}
            for d in dies:
                if d.x_coord is not None and d.y_coord is not None:
                    dmap[(d.x_coord, d.y_coord)] = {"hard_bin": d.hard_bin, "die_id": d.id}
            data_by_wafer[wid] = dmap
        all_xy = set()
        for dmap in data_by_wafer.values():
            all_xy.update(dmap.keys())

        # Differing dies (bin differs)
        diff_xy = []
        for xy in all_xy:
            b1 = data_by_wafer[left_id].get(xy, {}).get("hard_bin")
            b2 = data_by_wafer[right_id].get(xy, {}).get("hard_bin")
            if str(b1) != str(b2):
                diff_xy.append(xy)

        st.markdown(f"**Differing die count (bin):** {len(diff_xy)}")

        # Side-by-side wafer maps with bin marked
        col_left, col_right = st.columns(2)
        with col_left:
            dies_left = session.query(Die).filter_by(wafer_id=left_id).all()
            df_left = pd.DataFrame([{"x": d.x_coord, "y": d.y_coord, "hard_bin": d.hard_bin} for d in dies_left if d.x_coord is not None])
            fig_left = _wafer_map_bin_fig(df_left, f"Left: {left_label}", show_bin_label=False, highlight_xy=diff_xy)
            if fig_left:
                st.plotly_chart(fig_left, use_container_width=True)
        with col_right:
            dies_right = session.query(Die).filter_by(wafer_id=right_id).all()
            df_right = pd.DataFrame([{"x": d.x_coord, "y": d.y_coord, "hard_bin": d.hard_bin} for d in dies_right if d.x_coord is not None])
            fig_right = _wafer_map_bin_fig(df_right, f"Right: {right_label}", show_bin_label=False, highlight_xy=diff_xy)
            if fig_right:
                st.plotly_chart(fig_right, use_container_width=True)

        # Diff-only map (simple: red = differing position)
        if diff_xy:
            df_diff = pd.DataFrame([{"x": x, "y": y} for x, y in diff_xy])
            fig_diff = px.scatter(
                df_diff, x="x", y="y", title="Positions where bin differs (red = diff)",
                labels={"x": "X", "y": "Y"},
            )
            fig_diff.update_traces(marker=dict(size=12, color="red", symbol="x-open"))
            fig_diff.update_layout(yaxis=dict(scaleanchor="x", scaleratio=1), height=350)
            st.plotly_chart(fig_diff, use_container_width=True)

        # Table: selected wafers — common vs different TestItems (value or pass/fail)
        st.markdown("#### TestItem comparison (selected wafers)")
        try:
            # All tests present on any of the selected wafers
            tests_in_wafers = session.query(TestItem.test_num, TestItem.test_txt, TestItem.test_type).join(Die).filter(
                Die.wafer_id.in_(wafer_ids)
            ).distinct().all()
            wafer_labels_sel = [selected_wafers[i][1] for i in range(len(selected_wafers))]
            table_rows = []
            pchart_data = {}  # test_key -> (wafer_labels, fail_counts, total_counts)
            for (tnum, ttxt, ttyp) in tests_in_wafers:
                tname = (ttxt or f"Test#{tnum}").strip() or f"Test#{tnum}"
                per_wafer_total = []
                per_wafer_fail = []
                per_wafer_mean = []
                for wid in wafer_ids:
                    q = session.query(Die.id, TestItem.pass_fail, TestItem.result).join(TestItem, TestItem.die_id == Die.id).filter(
                        Die.wafer_id == wid, TestItem.test_num == tnum, TestItem.test_type == ttyp
                    ).all()
                    total = len(q)
                    fails = sum(1 for _ in q if _[1] == 1)
                    vals = [r[2] for r in q if r[2] is not None]
                    per_wafer_total.append(total)
                    per_wafer_fail.append(fails)
                    per_wafer_mean.append(float(np.mean(vals)) if vals else None)
                if not per_wafer_total or sum(per_wafer_total) == 0:
                    continue
                pchart_data[(tnum, tname, ttyp)] = (wafer_labels_sel[: len(wafer_ids)], per_wafer_fail, per_wafer_total)
                # Same = same pass/fail rate and (if PTR) same mean value within tolerance
                fail_rates = [_safe_div(f, n) for f, n in zip(per_wafer_fail, per_wafer_total)]
                same_pf = len(set(round(r, 4) for r in fail_rates)) <= 1
                same_val = True
                if ttyp == "PTR" and all(m is not None for m in per_wafer_mean):
                    if max(per_wafer_mean) - min(per_wafer_mean) > 1e-9:
                        same_val = False
                status = "Same" if (same_pf and same_val) else "Different"
                summary = "; ".join([f"{wafer_labels_sel[i]} p={fail_rates[i]:.3f}" + (f" μ={per_wafer_mean[i]:.4f}" if per_wafer_mean[i] is not None else "") for i in range(len(wafer_ids))])
                table_rows.append({"Test #": tnum, "Test name": tname, "Type": ttyp, "Status": status, "Per-wafer (p=fail rate, μ=mean)": summary[:80] + "…" if len(summary) > 80 else summary})
            if table_rows:
                df_comp = pd.DataFrame(table_rows)
                st.dataframe(df_comp, use_container_width=True)
                # p-Chart selector: pick a test to show p-chart across selected wafers
                test_choices = [(k[0], k[1], k[2]) for k in pchart_data.keys()]
                test_options_fmt = [f"{t[1]} (#{t[0]}, {t[2]})" for t in test_choices]
                sel_test_idx = st.selectbox("Show p-Chart for test (proportion defective per wafer)", range(len(test_choices)), format_func=lambda i: test_options_fmt[i], key="w2w_pchart_test")
                if sel_test_idx is not None and test_choices:
                    key = (test_choices[sel_test_idx][0], test_choices[sel_test_idx][1], test_choices[sel_test_idx][2])
                    if key in pchart_data:
                        wl, fc, tc = pchart_data[key]
                        pfig = _p_chart(wl, fc, tc, title=f"p-Chart: {test_choices[sel_test_idx][1]} (per selected wafer)")
                        if pfig:
                            st.plotly_chart(pfig, use_container_width=True)
            else:
                st.caption("No shared TestItems across selected wafers.")
        except Exception as e:
            st.warning(f"TestItem comparison table: {e}")

        # Test value comparison (optional)
        ptr_tests = session.query(TestItem.test_num, TestItem.test_txt).join(Die).filter(
            Die.wafer_id.in_(wafer_ids), TestItem.test_type == "PTR", TestItem.result != None
        ).distinct().limit(20).all()
        if ptr_tests:
            tsel = st.selectbox(
                "Choose a parametric test to see which die positions have different values (left vs right wafer)",
                range(len(ptr_tests)), format_func=lambda i: ptr_tests[i][1] or f"Test#{ptr_tests[i][0]}",
                help="Scatter plot shows (x,y) positions where the selected test’s result differs between the two wafers.",
            )
            if tsel is not None:
                tnum = ptr_tests[tsel][0]
                val_by_wafer = {}
                for wid in wafer_ids:
                    rows_v = session.query(Die.x_coord, Die.y_coord, TestItem.result).join(TestItem, TestItem.die_id == Die.id).filter(
                        Die.wafer_id == wid, TestItem.test_num == tnum, TestItem.test_type == "PTR", TestItem.result != None
                    ).all()
                    val_by_wafer[wid] = {(r[0], r[1]): r[2] for r in rows_v if r[0] is not None}
                all_xy_val = set()
                for v in val_by_wafer.values():
                    all_xy_val.update(v.keys())
                diff_val = []
                for xy in all_xy_val:
                    v1, v2 = val_by_wafer[left_id].get(xy), val_by_wafer[right_id].get(xy)
                    if v1 is not None and v2 is not None and abs(v1 - v2) > 1e-9:
                        diff_val.append(xy)
                st.write(f"**Die positions where this test’s measured value differs between left and right wafer:** {len(diff_val)}")
                if diff_val:
                    dfv = pd.DataFrame([{"x": x, "y": y} for x, y in diff_val])
                    figv = px.scatter(dfv, x="x", y="y", title=f"Wafer map: die positions with different {ptr_tests[tsel][1] or tnum} value (left vs right)")
                    figv.update_traces(marker=dict(size=10, color="darkorange"))
                    st.plotly_chart(figv, use_container_width=True)


def die_to_die(session: Session):
    st.subheader("Die-to-Die analysis")
    filters = _get_filters()
    lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
    lot_ids_filtered = [l.id for l in lots_q.all()]
    wafers = session.query(Wafer).filter(Wafer.lot_id.in_(lot_ids_filtered)).limit(500).all() if lot_ids_filtered else []
    if not wafers:
        st.info("No wafer/die data (or none match filters). Adjust Company/Product/Stage/Test Program / Time range.")
        return
    lot_map = {l.id: l.lot_id for l in session.query(Lot).filter(Lot.id.in_(lot_ids_filtered)).all()} if lot_ids_filtered else {}
    wafer_options = [(w.id, w.wafer_id, lot_map.get(w.lot_id, "")) for w in wafers]
    sel = st.selectbox("Wafer", range(len(wafer_options)), format_func=lambda i: f"{wafer_options[i][1]} (lot: {wafer_options[i][2]})")
    if sel is None:
        return
    wafer_id = wafer_options[sel][0]
    wafer_label = wafer_options[sel][1]
    dies = session.query(Die).filter_by(wafer_id=wafer_id).all()
    if not dies:
        st.info("No dies on this wafer.")
        return
    df = pd.DataFrame([{"x": d.x_coord, "y": d.y_coord, "hard_bin": d.hard_bin, "soft_bin": d.soft_bin} for d in dies])
    # Wafer map with bin marked (simpler: color by bin, optional labels)
    if df["x"].notna().any() and df["y"].notna().any():
        fig_bin = _wafer_map_bin_fig(df, f"Wafer map (bin): {wafer_label}", show_bin_label=(len(df) <= 150))
        if fig_bin:
            st.plotly_chart(fig_bin, use_container_width=True)

    # p-Chart: proportion defective per "subgroup" — for single wafer we use spatial regions or just overall p
    st.markdown("#### p-Chart (Pass/Fail on this wafer)")
    try:
        total = len(dies)
        if total > 0:
            fail_count = session.query(Die.id).join(TestItem, TestItem.die_id == Die.id).filter(
                Die.wafer_id == wafer_id, TestItem.pass_fail == 1
            ).distinct().count()
            pfig = _p_chart([wafer_label], [fail_count], [total], title=f"p-Chart: {wafer_label} (proportion defective)")
            if pfig:
                st.plotly_chart(pfig, use_container_width=True)
    except Exception as e:
        st.warning(f"p-Chart (die): {e}")

    # Statistics: bin counts, pass/fail, parametric summary
    st.markdown("#### Statistics (this wafer)")
    try:
        bin_counts = session.query(Die.hard_bin, func.count(Die.id)).filter(
            Die.wafer_id == wafer_id, Die.hard_bin != None
        ).group_by(Die.hard_bin).all()
        stat_rows = [{"Bin": f"Bin{hb}", "Count": c} for hb, c in bin_counts]
        if stat_rows:
            st.dataframe(pd.DataFrame(stat_rows), use_container_width=True)
        fail_count = session.query(Die.id).join(TestItem, TestItem.die_id == Die.id).filter(
            Die.wafer_id == wafer_id, TestItem.pass_fail == 1
        ).distinct().count()
        total_test_ms = session.query(func.coalesce(func.sum(Die.test_t), 0)).filter_by(wafer_id=wafer_id).scalar() or 0
        mean_test_ms = _safe_div(total_test_ms, total, 0)
        st.metric("Total dies", total)
        st.metric("Failing dies", fail_count)
        st.metric("Yield %", round(_safe_div(total - fail_count, total, 0) * 100, 2))
        st.metric("Total test time (ms)", total_test_ms)
        st.metric("Mean test time per die (ms)", round(mean_test_ms, 2))
    except Exception as e:
        st.warning(f"Stats: {e}")

    # Test item dropdown: wafer map by selected test
    ptr_tests = session.query(TestItem.test_num, TestItem.test_txt).join(Die).filter(
        Die.wafer_id == wafer_id, TestItem.test_type == "PTR", TestItem.result != None
    ).distinct().limit(100).all()
    if ptr_tests:
        test_options = [(t[0], (t[1] or f"Test#{t[0]}").strip() or f"Test#{t[0]}") for t in ptr_tests]
        tsel = st.selectbox(
            "Select parametric test to color wafer map by measured value",
            range(len(test_options)), format_func=lambda i: test_options[i][1],
            help="Each die is colored by this test’s result (e.g. voltage, current); helps spot spatial patterns.",
        )
        if tsel is not None:
            test_num, test_name = ptr_tests[tsel][0], test_options[tsel][1]
            results = session.query(Die.x_coord, Die.y_coord, TestItem.result).join(TestItem, TestItem.die_id == Die.id).filter(
                Die.wafer_id == wafer_id, TestItem.test_num == test_num, TestItem.test_type == "PTR", TestItem.result != None
            ).all()
            if results:
                dfr = pd.DataFrame(results, columns=["x", "y", "result"])
                fig2 = px.scatter(dfr, x="x", y="y", color="result", title=f"Wafer map: {test_name}", color_continuous_scale="Viridis")
                fig2.update_layout(yaxis=dict(scaleanchor="x", scaleratio=1))
                st.plotly_chart(fig2, use_container_width=True)
                # Stats for this test on this wafer
                stats_df = _stats_table(dfr, "result", None)
                if stats_df is not None:
                    st.dataframe(stats_df, use_container_width=True)


# ---------- Bin summary ----------
def bin_summary(session: Session):
    st.subheader("Bin Summary")
    filters = _get_filters()
    lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
    lots = lots_q.all()
    if not lots:
        st.info("No lot data (or none match filters). Adjust Company/Product/Stage/Test Program / Time range.")
        return
    lot_ids = [l.lot_id for l in lots]
    sel_lot = st.selectbox("Lot", lot_ids)
    lot = session.query(Lot).filter_by(lot_id=sel_lot).first()
    if not lot:
        return
    # Per wafer bin summary
    wafers = session.query(Wafer).filter_by(lot_id=lot.id).all()
    rows = []
    for w in wafers:
        bins = session.query(Die.hard_bin, Bin.hard_bin_name).select_from(Die).outerjoin(Bin, Bin.die_id == Die.id).filter(
            Die.wafer_id == w.id, Die.hard_bin != None
        ).all()
        for hb, hn in bins:
            rows.append({"Wafer": w.wafer_id, "Hard bin": hn or f"Bin{hb}", "Count": 1})
    if rows:
        df = pd.DataFrame(rows).groupby(["Wafer", "Hard bin"], as_index=False).sum()
        pivot = df.pivot(index="Wafer", columns="Hard bin", values="Count").fillna(0)
        st.dataframe(pivot, use_container_width=True)
        fig = px.bar(df, x="Wafer", y="Count", color="Hard bin", title="Bin summary per wafer")
        st.plotly_chart(fig, use_container_width=True)
    # Lot total
    lot_bins = session.query(Die.hard_bin, func.count(Die.id)).select_from(Die).filter(
        Die.lot_id == lot.id, Die.hard_bin != None
    ).group_by(Die.hard_bin).all()
    if lot_bins:
        bin_names = {}
        for hb, hn in session.query(Bin.hard_bin, Bin.hard_bin_name).join(Die).filter(Die.lot_id == lot.id).distinct():
            if hb not in bin_names:
                bin_names[hb] = (hn or "").strip() or f"Bin{hb}"
        df_lot = pd.DataFrame([{"Bin": bin_names.get(hb, f"Bin{hb}"), "Count": c} for hb, c in lot_bins])
        fig_lot = px.pie(df_lot, values="Count", names="Bin", title="Lot bin summary")
        st.plotly_chart(fig_lot, use_container_width=True)


# ---------- Equipment / Tester / Probe card / Load board ----------
def equipment_comparison(session: Session):
    st.subheader("Equipment & Tester comparison")
    filters = _get_filters()
    lots_q = _lots_query(session, **{k: v for k, v in filters.items() if v is not None})
    lots = lots_q.all()
    if not lots:
        st.info("No lot data (or none match filters). Adjust Company/Product/Stage/Test Program / Time range.")
        return
    lot_ids = [l.lot_id for l in lots]
    selected = st.multiselect("Select lots", lot_ids, default=lot_ids[: min(5, len(lot_ids))])
    if not selected:
        return
    # Lot tester info
    rows = []
    for l in session.query(Lot).filter(Lot.lot_id.in_(selected)):
        rows.append({
            "Lot": l.lot_id,
            "Tester": getattr(l, "tstr_typ", "") or "-",
            "Node": getattr(l, "node_nam", "") or "-",
            "Facility": getattr(l, "facil_id", "") or "-",
            "Floor": getattr(l, "floor_id", "") or "-",
            "Exec": getattr(l, "exec_typ", "") or "-",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
    # Site equipment (probe card, load board)
    eq_rows = []
    for l in session.query(Lot).filter(Lot.lot_id.in_(selected)):
        for e in session.query(SiteEquipment).filter_by(lot_id=l.id).all():
            eq_rows.append({
                "Lot": l.lot_id,
                "Head": e.head_num,
                "Site grp": e.site_grp,
                "Probe card": (e.card_typ or "-") + " / " + (e.card_id or ""),
                "Load board": (e.load_typ or "-") + " / " + (e.load_id or ""),
                "Handler": (e.hand_typ or "-") + " / " + (e.hand_id or ""),
            })
    if eq_rows:
        df_eq = pd.DataFrame(eq_rows)
        st.dataframe(df_eq, use_container_width=True)
    # Test time comparison
    st.subheader("Test time comparison (ms per die)")
    try:
        time_rows = []
        for l in session.query(Lot).filter(Lot.lot_id.in_(selected)):
            dies = session.query(Die.test_t).filter_by(lot_id=l.id).all()
            vals = [d[0] for d in dies if d[0] is not None and d[0] > 0]
            time_rows.append({"Lot": l.lot_id, "Mean (ms)": float(np.mean(vals)) if vals else 0, "Max (ms)": max(vals) if vals else 0, "Dies": len(vals)})
        if time_rows:
            dft = pd.DataFrame(time_rows)
            st.dataframe(dft, use_container_width=True)
            fig = px.bar(dft, x="Lot", y="Mean (ms)", title="Mean test time per lot")
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"Test time: {e}")


def custom_query(session: Session):
    st.subheader("Custom SQL query")
    sql = st.text_area("SQL (read-only)", height=120, placeholder="SELECT * FROM lot LIMIT 10")
    df_placeholder = st.empty()
    if st.button("Run query"):
        if sql.strip():
            run_sql(df_placeholder, session, sql)


def main():
    st.set_page_config(page_title="STDF Dashboard", layout="wide")
    st.title("STDF Database Dashboard")
    session = get_session()
    _sidebar_filters(session)
    sidebar = st.sidebar
    sidebar.header("Navigation")
    page = sidebar.radio(
        "Page",
        [
            "Dashboard",
            "Load STDF",
            "Lot-to-Lot",
            "Wafer-to-Wafer",
            "Die-to-Die",
            "Fail Pareto",
            "TestSuite→TestItem",
            "Bin Summary",
            "Equipment",
            "Custom SQL",
        ],
        label_visibility="collapsed",
    )
    if page == "Dashboard":
        dashboard_home(session)
    elif page == "Load STDF":
        load_stdf_ui()
    elif page == "Lot-to-Lot":
        lot_to_lot(session)
    elif page == "Wafer-to-Wafer":
        wafer_to_wafer(session)
    elif page == "Die-to-Die":
        die_to_die(session)
    elif page == "Fail Pareto":
        fail_pareto(session)
    elif page == "TestSuite→TestItem":
        test_suite_items(session)
    elif page == "Bin Summary":
        bin_summary(session)
    elif page == "Equipment":
        equipment_comparison(session)
    else:
        custom_query(session)
    session.close()


if __name__ == "__main__":
    main()
