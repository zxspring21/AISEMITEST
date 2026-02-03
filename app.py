"""
Streamlit dashboard for STDF DB: lot-to-lot, wafer-to-wafer, die-to-die analysis,
fail pareto, TestSuite→TestItem mapping, wafer diff comparison, bin summary, equipment.
"""
import io
import tempfile
from pathlib import Path
from collections import defaultdict

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


def dashboard_home(session: Session):
    st.subheader("Overview")
    lots = session.query(Lot).count()
    wafers = session.query(Wafer).count()
    dies = session.query(Die).count()
    col1, col2, col3 = st.columns(3)
    col1.metric("Lots", lots)
    col2.metric("Wafers", wafers)
    col3.metric("Dies", dies)
    if lots:
        df = pd.DataFrame([
            {
                "Lot": l.lot_id, "Part type": l.part_typ or "-",
                "Tester": getattr(l, "tstr_typ", "") or "-",
                "Wafers": session.query(Wafer).filter_by(lot_id=l.id).count(),
                "Dies": session.query(Die).filter_by(lot_id=l.id).count()
            }
            for l in session.query(Lot).limit(20)
        ])
        st.dataframe(df, use_container_width=True)


def lot_to_lot(session: Session):
    st.subheader("Lot-to-Lot analysis")
    lots = session.query(Lot).all()
    if not lots:
        st.info("No lot data. Load STDF first.")
        return
    lot_ids = [l.lot_id for l in lots]
    selected = st.multiselect("Select lots", lot_ids, default=lot_ids[: min(5, len(lot_ids))])
    if not selected:
        return
    rows = []
    for lot in session.query(Lot).filter(Lot.lot_id.in_(selected)):
        dies_in_lot = session.query(Die).filter_by(lot_id=lot.id)
        total = dies_in_lot.count()
        rows.append({"Lot": lot.lot_id, "Total dies": total, "Part type": lot.part_typ or "-"})
    df = pd.DataFrame(rows)
    if df.empty:
        return
    st.dataframe(df, use_container_width=True)
    fig = px.bar(df, x="Lot", y="Total dies", title="Die count per lot", color="Total dies")
    st.plotly_chart(fig, use_container_width=True)
    sample = session.query(TestItem).filter(TestItem.test_type == "PTR", TestItem.result != None).first()
    if sample:
        test_name = sample.test_txt or f"Test#{sample.test_num}"
        st.caption(f"Parametric: {test_name}")
        q = session.query(Lot.lot_id.label("lot_id_str"), TestItem.result).join(Die, Die.lot_id == Lot.id).join(TestItem, TestItem.die_id == Die.id).filter(
            TestItem.test_num == sample.test_num, TestItem.test_type == "PTR", Lot.lot_id.in_(selected), TestItem.result != None
        )
        rows = [(r.lot_id_str, r.result) for r in q]
        if rows:
            dfp = pd.DataFrame(rows, columns=["Lot", "Result"])
            fig2 = px.box(dfp, x="Lot", y="Result", title=f"Lot-to-Lot: {test_name}")
            st.plotly_chart(fig2, use_container_width=True)


# ---------- Fail Pareto ----------
def fail_pareto(session: Session):
    st.subheader("Fail Pareto Analysis")
    level = st.radio("Level", ["Die", "Wafer"], horizontal=True)
    lots = session.query(Lot).all()
    if not lots:
        st.info("No lot data.")
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
        fig.update_xaxis(tickangle=-45)
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
            fig.update_xaxis(tickangle=-45)
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


# ---------- Wafer-to-Wafer with diff comparison ----------
def wafer_to_wafer(session: Session):
    st.subheader("Wafer-to-Wafer analysis")
    lots_with_wafer = session.query(Lot).join(Wafer).distinct().all()
    if not lots_with_wafer:
        st.info("No wafer data.")
        return
    lot_options = [(l.id, l.lot_id) for l in lots_with_wafer]
    sel_idx = st.selectbox("Lot", range(len(lot_options)), format_func=lambda i: lot_options[i][1])
    if sel_idx is None:
        return
    chosen_lot_id = lot_options[sel_idx][0]
    wafers_in_lot = session.query(Wafer).filter_by(lot_id=chosen_lot_id).all()
    rows = [{"Wafer": w.wafer_id, "Parts": w.part_cnt, "Good": w.good_cnt, "Yield %": (w.good_cnt / w.part_cnt * 100) if w.part_cnt else 0} for w in wafers_in_lot]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
    if not df.empty and "Yield %" in df.columns:
        fig = px.bar(df, x="Wafer", y="Yield %", title="Wafer yield")
        st.plotly_chart(fig, use_container_width=True)

    # Multi-wafer comparison
    st.markdown("---")
    st.subheader("Multi-Wafer comparison: highlight differences")
    wafer_choices = [(w.id, w.wafer_id) for w in wafers_in_lot]
    selected_wafers = st.multiselect("Select 2+ wafers to compare", wafer_choices, default=[], format_func=lambda x: x[1])
    if len(selected_wafers) >= 2:
        wafer_ids = [w[0] for w in selected_wafers]
        # Build (x,y) -> {wafer_id: (hard_bin, test results)} for common dies
        all_xy = set()
        data_by_wafer = {}
        for wid in wafer_ids:
            dies = session.query(Die).filter_by(wafer_id=wid).all()
            dmap = {}
            for d in dies:
                if d.x_coord is not None and d.y_coord is not None:
                    key = (d.x_coord, d.y_coord)
                    all_xy.add(key)
                    dmap[key] = {"hard_bin": d.hard_bin, "die_id": d.id}
            data_by_wafer[wid] = dmap
        # Find differing dies
        diff_xy = []
        for xy in all_xy:
            bins = [data_by_wafer[wid].get(xy, {}).get("hard_bin") for wid in wafer_ids]
            if len(set(str(b) for b in bins)) > 1:
                diff_xy.append(xy)
        st.write(f"**Differing die positions (bin differs):** {len(diff_xy)}")
        if diff_xy:
            df_diff = pd.DataFrame([{"x": x, "y": y} for x, y in diff_xy])
            fig_diff = px.scatter(df_diff, x="x", y="y", title="Wafer map: positions where selected wafers differ (bin)")
            st.plotly_chart(fig_diff, use_container_width=True)
        # Test item differences: pick a test
        ptr_tests = session.query(TestItem.test_num, TestItem.test_txt).join(Die).filter(
            Die.wafer_id.in_(wafer_ids), TestItem.test_type == "PTR", TestItem.result != None
        ).distinct().limit(20).all()
        if ptr_tests:
            tsel = st.selectbox("Test for value comparison", range(len(ptr_tests)), format_func=lambda i: ptr_tests[i][1] or f"Test#{ptr_tests[i][0]}")
            if tsel is not None:
                tnum = ptr_tests[tsel][0]
                # For each wafer, get (x,y)->result
                val_by_wafer = {}
                for wid in wafer_ids:
                    rows = session.query(Die.x_coord, Die.y_coord, TestItem.result).join(TestItem, TestItem.die_id == Die.id).filter(
                        Die.wafer_id == wid, TestItem.test_num == tnum, TestItem.test_type == "PTR", TestItem.result != None
                    ).all()
                    val_by_wafer[wid] = {(r[0], r[1]): r[2] for r in rows if r[0] is not None}
                all_xy_val = set()
                for v in val_by_wafer.values():
                    all_xy_val.update(v.keys())
                diff_val = []
                for xy in all_xy_val:
                    vals = [val_by_wafer[wid].get(xy) for wid in wafer_ids]
                    valid = [v for v in vals if v is not None]
                    if len(valid) >= 2 and (max(valid) - min(valid)) > 1e-9:
                        diff_val.append(xy)
                st.write(f"**Differing die positions (test value differs):** {len(diff_val)}")
                if diff_val:
                    dfv = pd.DataFrame([{"x": x, "y": y} for x, y in diff_val])
                    figv = px.scatter(dfv, x="x", y="y", title=f"Positions where test values differ: {ptr_tests[tsel][1] or tnum}")
                    st.plotly_chart(figv, use_container_width=True)


def die_to_die(session: Session):
    st.subheader("Die-to-Die analysis")
    wafers = session.query(Wafer).limit(500).all()
    if not wafers:
        st.info("No wafer/die data.")
        return
    lot_map = {l.id: l.lot_id for l in session.query(Lot).all()}
    wafer_options = [(w.id, w.wafer_id, lot_map.get(w.lot_id, "")) for w in wafers]
    sel = st.selectbox("Wafer", range(len(wafer_options)), format_func=lambda i: f"{wafer_options[i][1]} (lot: {wafer_options[i][2]})")
    if sel is None:
        return
    wafer_id = wafer_options[sel][0]
    dies = session.query(Die).filter_by(wafer_id=wafer_id).all()
    if not dies:
        st.info("No dies on this wafer.")
        return
    df = pd.DataFrame([{"x": d.x_coord, "y": d.y_coord, "hard_bin": d.hard_bin, "soft_bin": d.soft_bin} for d in dies])
    if df["x"].notna().any() and df["y"].notna().any():
        fig = px.scatter(df, x="x", y="y", color="hard_bin", title="Wafer map (hard bin)", size_max=8)
        st.plotly_chart(fig, use_container_width=True)
    sample = session.query(TestItem).join(Die).filter(Die.wafer_id == wafer_id, TestItem.test_type == "PTR", TestItem.result != None).first()
    if sample:
        results = session.query(Die.x_coord, Die.y_coord, TestItem.result).join(TestItem, TestItem.die_id == Die.id).filter(
            Die.wafer_id == wafer_id, TestItem.test_num == sample.test_num, TestItem.test_type == "PTR"
        ).all()
        if results:
            dfr = pd.DataFrame(results, columns=["x", "y", "result"])
            fig2 = px.scatter(dfr, x="x", y="y", color="result", title=f"Wafer map: {sample.test_txt or sample.test_num}")
            st.plotly_chart(fig2, use_container_width=True)


# ---------- Bin summary ----------
def bin_summary(session: Session):
    st.subheader("Bin Summary")
    lots = session.query(Lot).all()
    if not lots:
        st.info("No lot data.")
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
        bins = session.query(Die.hard_bin, Bin.hard_bin_name).outerjoin(Bin, Bin.die_id == Die.id).filter(
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
    lots = session.query(Lot).all()
    if not lots:
        st.info("No lot data.")
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
    time_rows = []
    for l in session.query(Lot).filter(Lot.lot_id.in_(selected)):
        dies = session.query(Die.test_t).filter_by(lot_id=l.id).all()
        vals = [d[0] for d in dies if d[0] is not None and d[0] > 0]
        time_rows.append({"Lot": l.lot_id, "Mean (ms)": np.mean(vals) if vals else 0, "Max (ms)": max(vals) if vals else 0, "Dies": len(vals)})
    if time_rows:
        dft = pd.DataFrame(time_rows)
        st.dataframe(dft, use_container_width=True)
        fig = px.bar(dft, x="Lot", y="Mean (ms)", title="Mean test time per lot")
        st.plotly_chart(fig, use_container_width=True)


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
