"""
Load STDF files into the relational DB (Company/Product/Stage/TestProgram/Lot/Wafer/Die/Bin/TestSuite/TestItem).
Uses pystdf for parsing; implements a sink that receives record events and writes to SQLAlchemy.
"""
from datetime import datetime
from pathlib import Path

from pystdf.IO import Parser
from pystdf import V4
from sqlalchemy.orm import Session

from config import DEFAULT_COMPANY, DEFAULT_PRODUCT, DEFAULT_STAGE
from db_models import (
    Base,
    Company,
    Product,
    Stage,
    TestProgram,
    Lot,
    Wafer,
    Die,
    Bin,
    TestSuite,
    TestDefinition,
    TestItem,
    SiteEquipment,
    get_engine,
    init_db,
)


def _field_dict(rec_type, fields):
    """Build dict from (recType, fields) using recType.fieldNames or fieldMap."""
    if not fields:
        return {}
    names = getattr(rec_type, "fieldNames", None) or (
        [f[0] for f in rec_type.fieldMap] if hasattr(rec_type, "fieldMap") else []
    )
    if not names:
        return {}
    return dict(zip(names, fields))


def _stdf_time_to_datetime(val):
    """Convert STDF U4 timestamp (seconds since epoch) to datetime; None if invalid."""
    if val is None or (isinstance(val, int) and val == 0):
        return None
    try:
        return datetime.utcfromtimestamp(int(val))
    except (OSError, ValueError):
        return None


class StdfToDbSink:
    """
    Sink that receives pystdf record events and inserts into the relational DB.
    Tracks current lot/wafer/die and buffers PTR/FTR until PRR.
    """
    def __init__(self, session: Session, company_name: str = None, product_name: str = None, stage_name: str = None):
        self.session = session
        self.company_name = company_name or DEFAULT_COMPANY
        self.product_name = product_name or DEFAULT_PRODUCT
        self.stage_name = stage_name or DEFAULT_STAGE
        self._company = None
        self._product = None
        self._stage = None
        self._test_program = None
        self._lot = None
        self._wafer = None
        self._current_die_key = None   # (head_num, site_num)
        self._current_die = None
        self._ptr_ftr_buffer = []     # list of (rec_type, field_dict) for current die
        self._wafer_id_current = None
        self._head_num = 1
        self._site_num = 1
        # HBR/SBR: (head_num, site_num) -> { bin_num: name }; (255, 255) = summary
        self._hard_bin_names = {}
        self._soft_bin_names = {}
        # test_num -> test_suite_id (from TSR)
        self._test_num_to_suite = {}

    def _get_bin_name(self, head_num, site_num, bin_num, is_hard=True):
        names = self._hard_bin_names if is_hard else self._soft_bin_names
        key = (head_num, site_num)
        if key in names and bin_num in names[key]:
            return names[key][bin_num]
        summary_key = (255, 255)
        if summary_key in names and bin_num in names[summary_key]:
            return names[summary_key][bin_num]
        return ""

    def _get_or_create_company_product_stage_program(self, job_nam, job_rev, part_typ, mode_cod):
        company = self.session.query(Company).filter_by(name=self.company_name).first()
        if not company:
            company = Company(name=self.company_name)
            self.session.add(company)
            self.session.flush()
        self._company = company

        product_name = (part_typ or self.product_name or "").strip() or "DefaultProduct"
        product = self.session.query(Product).filter_by(company_id=company.id, name=product_name).first()
        if not product:
            product = Product(company_id=company.id, name=product_name)
            self.session.add(product)
            self.session.flush()
        self._product = product

        stage_name = (mode_cod or self.stage_name or "").strip() or "DefaultStage"
        stage = self.session.query(Stage).filter_by(product_id=product.id, name=stage_name).first()
        if not stage:
            stage = Stage(product_id=product.id, name=stage_name)
            self.session.add(stage)
            self.session.flush()
        self._stage = stage

        prog_name = (job_nam or "").strip() or "DefaultProgram"
        prog_rev = (job_rev or "").strip() or ""
        prog = self.session.query(TestProgram).filter_by(
            stage_id=stage.id, name=prog_name, revision=prog_rev
        ).first()
        if not prog:
            prog = TestProgram(stage_id=stage.id, name=prog_name, revision=prog_rev)
            self.session.add(prog)
            self.session.flush()
        self._test_program = prog

    def before_send(self, data_source, data):
        rec_type, fields = data
        fd = _field_dict(rec_type, fields)
        if isinstance(rec_type, V4.Mir):
            self._on_mir(fd)
        elif isinstance(rec_type, V4.Wir):
            self._on_wir(fd)
        elif isinstance(rec_type, V4.Wrr):
            self._on_wrr(fd)
        elif isinstance(rec_type, V4.Pir):
            self._on_pir(fd)
        elif isinstance(rec_type, V4.Prr):
            self._on_prr(fd)
        elif isinstance(rec_type, V4.Ptr):
            self._on_ptr(fd)
        elif isinstance(rec_type, V4.Ftr):
            self._on_ftr(fd)
        elif isinstance(rec_type, V4.Hbr):
            self._on_hbr(fd)
        elif isinstance(rec_type, V4.Sbr):
            self._on_sbr(fd)
        elif isinstance(rec_type, V4.Tsr):
            self._on_tsr(fd)
        elif isinstance(rec_type, V4.Sdr):
            self._on_sdr(fd)

    def _on_sdr(self, fd):
        if not self._lot:
            return
        head_num = fd.get("HEAD_NUM") or 1
        site_grp = fd.get("SITE_GRP")
        if site_grp is None:
            site_grp = 255
        hand_typ = (fd.get("HAND_TYP") or "").strip()[:128]
        hand_id = (fd.get("HAND_ID") or "").strip()[:128]
        card_typ = (fd.get("CARD_TYP") or "").strip()[:128]
        card_id = (fd.get("CARD_ID") or "").strip()[:128]
        load_typ = (fd.get("LOAD_TYP") or "").strip()[:128]
        load_id = (fd.get("LOAD_ID") or "").strip()[:128]
        dib_typ = (fd.get("DIB_TYP") or "").strip()[:128]
        dib_id = (fd.get("DIB_ID") or "").strip()[:128]
        cabl_typ = (fd.get("CABL_TYP") or "").strip()[:128]
        cabl_id = (fd.get("CABL_ID") or "").strip()[:128]
        cont_typ = (fd.get("CONT_TYP") or "").strip()[:128]
        cont_id = (fd.get("CONT_ID") or "").strip()[:128]
        eq = self.session.query(SiteEquipment).filter_by(
            lot_id=self._lot.id, head_num=head_num, site_grp=site_grp
        ).first()
        if not eq:
            eq = SiteEquipment(
                lot_id=self._lot.id,
                head_num=head_num,
                site_grp=site_grp,
                hand_typ=hand_typ,
                hand_id=hand_id,
                card_typ=card_typ,
                card_id=card_id,
                load_typ=load_typ,
                load_id=load_id,
                dib_typ=dib_typ,
                dib_id=dib_id,
                cabl_typ=cabl_typ,
                cabl_id=cabl_id,
                cont_typ=cont_typ,
                cont_id=cont_id,
            )
            self.session.add(eq)
            self.session.flush()

    def _on_hbr(self, fd):
        head_num = fd.get("HEAD_NUM")
        if head_num is None:
            return
        site_num = fd.get("SITE_NUM")
        if site_num is None:
            site_num = 255
        hbin_num = fd.get("HBIN_NUM")
        hbin_nam = (fd.get("HBIN_NAM") or "").strip()
        key = (head_num, site_num)
        self._hard_bin_names.setdefault(key, {})[hbin_num] = hbin_nam[:255] if hbin_nam else ""

    def _on_sbr(self, fd):
        head_num = fd.get("HEAD_NUM")
        if head_num is None:
            return
        site_num = fd.get("SITE_NUM")
        if site_num is None:
            site_num = 255
        sbin_num = fd.get("SBIN_NUM")
        sbin_nam = (fd.get("SBIN_NAM") or "").strip()
        key = (head_num, site_num)
        self._soft_bin_names.setdefault(key, {})[sbin_num] = sbin_nam[:255] if sbin_nam else ""

    def _on_tsr(self, fd):
        seq_name = (fd.get("SEQ_NAME") or "").strip()
        test_num = fd.get("TEST_NUM")
        test_typ = (fd.get("TEST_TYP") or " ").strip()
        test_nam = (fd.get("TEST_NAM") or "").strip()[:512]
        test_lbl = (fd.get("TEST_LBL") or "").strip()[:255]
        exec_cnt = fd.get("EXEC_CNT")
        fail_cnt = fd.get("FAIL_CNT")
        alrm_cnt = fd.get("ALRM_CNT")
        if not seq_name or not self._test_program:
            return
        suite = self.session.query(TestSuite).filter_by(
            test_program_id=self._test_program.id, name=seq_name
        ).first()
        if not suite:
            suite = TestSuite(test_program_id=self._test_program.id, name=seq_name)
            self.session.add(suite)
            self.session.flush()
        # Create TestDefinition linking test_num to TestSuite
        if test_num is not None:
            td = self.session.query(TestDefinition).filter_by(
                test_program_id=self._test_program.id, test_num=test_num
            ).first()
            if not td:
                td = TestDefinition(
                    test_program_id=self._test_program.id,
                    test_suite_id=suite.id,
                    test_num=test_num,
                    test_type=test_typ if test_typ else "",
                    test_nam=test_nam,
                    test_lbl=test_lbl,
                    exec_cnt=exec_cnt,
                    fail_cnt=fail_cnt,
                    alrm_cnt=alrm_cnt,
                )
                self.session.add(td)
                self.session.flush()
            self._test_num_to_suite[test_num] = suite.id

    def _on_mir(self, fd):
        lot_id = (fd.get("LOT_ID") or "").strip() or "UNKNOWN_LOT"
        part_typ = fd.get("PART_TYP") or ""
        job_nam = fd.get("JOB_NAM") or ""
        job_rev = fd.get("JOB_REV") or ""
        mode_cod = fd.get("MODE_COD") or ""
        setup_t = fd.get("SETUP_T")
        start_t = fd.get("START_T")
        tstr_typ = (fd.get("TSTR_TYP") or "").strip()[:64]
        node_nam = (fd.get("NODE_NAM") or "").strip()[:64]
        facil_id = (fd.get("FACIL_ID") or "").strip()[:64]
        floor_id = (fd.get("FLOOR_ID") or "").strip()[:64]
        stat_num = fd.get("STAT_NUM")
        exec_typ = (fd.get("EXEC_TYP") or "").strip()[:64]
        exec_ver = (fd.get("EXEC_VER") or "").strip()[:64]
        self._get_or_create_company_product_stage_program(job_nam, job_rev, part_typ, mode_cod)
        lot = self.session.query(Lot).filter_by(
            test_program_id=self._test_program.id, lot_id=lot_id
        ).first()
        if not lot:
            lot = Lot(
                test_program_id=self._test_program.id,
                lot_id=lot_id,
                part_typ=(part_typ or "").strip(),
                setup_t=_stdf_time_to_datetime(setup_t),
                start_t=_stdf_time_to_datetime(start_t),
                tstr_typ=tstr_typ,
                node_nam=node_nam,
                facil_id=facil_id,
                floor_id=floor_id,
                stat_num=stat_num,
                exec_typ=exec_typ,
                exec_ver=exec_ver,
            )
            self.session.add(lot)
            self.session.flush()
        self._lot = lot
        self._wafer = None
        self._wafer_id_current = None
        self._current_die = None
        self._current_die_key = None
        self._ptr_ftr_buffer = []
        self._hard_bin_names = {}
        self._soft_bin_names = {}
        self._test_num_to_suite = {}

    def _on_wir(self, fd):
        wafer_id = (fd.get("WAFER_ID") or "").strip() or "UNKNOWN_WAFER"
        head_num = fd.get("HEAD_NUM") or 1
        site_grp = fd.get("SITE_GRP")
        if site_grp is None:
            site_grp = 255
        start_t = fd.get("START_T")
        if not self._lot:
            return
        wafer = self.session.query(Wafer).filter_by(
            lot_id=self._lot.id, wafer_id=wafer_id, head_num=head_num
        ).first()
        if not wafer:
            wafer = Wafer(
                lot_id=self._lot.id,
                wafer_id=wafer_id,
                head_num=head_num,
                site_grp=site_grp,
                start_t=_stdf_time_to_datetime(start_t),
            )
            self.session.add(wafer)
            self.session.flush()
        self._wafer = wafer
        self._wafer_id_current = wafer_id
        self._current_die = None
        self._current_die_key = None
        self._ptr_ftr_buffer = []

    def _on_wrr(self, fd):
        finish_t = fd.get("FINISH_T")
        part_cnt = fd.get("PART_CNT")
        good_cnt = fd.get("GOOD_CNT")
        if self._wafer:
            self._wafer.finish_t = _stdf_time_to_datetime(finish_t)
            if part_cnt is not None:
                self._wafer.part_cnt = part_cnt
            if good_cnt is not None:
                self._wafer.good_cnt = good_cnt
        self._wafer_id_current = None

    def _on_pir(self, fd):
        head_num = fd.get("HEAD_NUM") or 1
        site_num = fd.get("SITE_NUM") or 1
        self._head_num = head_num
        self._site_num = site_num
        self._current_die_key = (head_num, site_num)
        self._current_die = None
        self._ptr_ftr_buffer = []

    def _on_prr(self, fd):
        head_num = fd.get("HEAD_NUM") or 1
        site_num = fd.get("SITE_NUM") or 1
        part_flg = fd.get("PART_FLG")
        if isinstance(part_flg, (list, bytes)):
            part_flg = part_flg[0] if part_flg else 0
        num_test = fd.get("NUM_TEST") or 0
        hard_bin = fd.get("HARD_BIN")
        soft_bin = fd.get("SOFT_BIN")
        x_coord = fd.get("X_COORD")
        y_coord = fd.get("Y_COORD")
        test_t = fd.get("TEST_T") or 0
        part_id = (fd.get("PART_ID") or "").strip()
        if x_coord == -32768:
            x_coord = None
        if y_coord == -32768:
            y_coord = None
        if soft_bin == 65535:
            soft_bin = None
        if not self._lot:
            self._ptr_ftr_buffer = []
            return
        wafer_id_fk = self._wafer.id if self._wafer else None
        die = Die(
            lot_id=self._lot.id,
            wafer_id=wafer_id_fk,
            head_num=head_num,
            site_num=site_num,
            x_coord=x_coord,
            y_coord=y_coord,
            part_id=part_id,
            hard_bin=hard_bin,
            soft_bin=soft_bin,
            part_flg=part_flg or 0,
            num_test=num_test,
            test_t=test_t,
        )
        self.session.add(die)
        self.session.flush()
        self._current_die = die
        if hard_bin is not None:
            hard_name = self._get_bin_name(head_num, site_num, hard_bin, is_hard=True)
            soft_name = self._get_bin_name(head_num, site_num, soft_bin, is_hard=False) if soft_bin is not None else ""
            bin_rec = Bin(
                die_id=die.id,
                hard_bin=hard_bin,
                soft_bin=soft_bin,
                hard_bin_name=hard_name,
                soft_bin_name=soft_name,
            )
            self.session.add(bin_rec)
        for rec_type_name, item_fd in self._ptr_ftr_buffer:
            if rec_type_name == "PTR":
                result = item_fd.get("RESULT")
                test_txt = (item_fd.get("TEST_TXT") or "").strip()[:512]
                units = (item_fd.get("UNITS") or "").strip()[:64]
                lo_limit = item_fd.get("LO_LIMIT")
                hi_limit = item_fd.get("HI_LIMIT")
                test_num = item_fd.get("TEST_NUM") or 0
                test_flg = item_fd.get("TEST_FLG")
                if isinstance(test_flg, (list, bytes)):
                    test_flg = test_flg[0] if test_flg else 0
                pass_fail = None
                if test_flg is not None and hasattr(test_flg, "__and__"):
                    pass_fail = 1 if (test_flg & 0x80) else 0
                suite_id = self._test_num_to_suite.get(test_num)
                ti = TestItem(
                    die_id=die.id,
                    test_num=test_num,
                    test_txt=test_txt,
                    test_type="PTR",
                    test_suite_id=suite_id,
                    result=float(result) if result is not None else None,
                    units=units,
                    lo_limit=float(lo_limit) if lo_limit is not None else None,
                    hi_limit=float(hi_limit) if hi_limit is not None else None,
                    pass_fail=pass_fail,
                )
                self.session.add(ti)
            else:
                test_num = item_fd.get("TEST_NUM") or 0
                test_txt = (item_fd.get("TEST_TXT") or "").strip()[:512]
                test_flg = item_fd.get("TEST_FLG")
                if isinstance(test_flg, (list, bytes)):
                    test_flg = test_flg[0] if test_flg else 0
                pass_fail = None
                if test_flg is not None and hasattr(test_flg, "__and__"):
                    pass_fail = 1 if (test_flg & 0x80) else 0
                suite_id = self._test_num_to_suite.get(test_num)
                ti = TestItem(
                    die_id=die.id,
                    test_num=test_num,
                    test_txt=test_txt,
                    test_type="FTR",
                    test_suite_id=suite_id,
                    result=None,
                    pass_fail=pass_fail,
                )
                self.session.add(ti)
        self._ptr_ftr_buffer = []
        self._current_die = None
        self._current_die_key = None

    def _on_ptr(self, fd):
        self._ptr_ftr_buffer.append(("PTR", fd))

    def _on_ftr(self, fd):
        self._ptr_ftr_buffer.append(("FTR", fd))

    def after_send(self, data_source, data):
        rec_type, fields = data
        if isinstance(rec_type, V4.Mrr) and self._lot:
            fd = _field_dict(rec_type, fields)
            finish_t = fd.get("FINISH_T")
            self._lot.finish_t = _stdf_time_to_datetime(finish_t)


def load_stdf(
    stdf_path,
    db_url=None,
    company_name=None,
    product_name=None,
    stage_name=None,
):
    """
    Parse STDF file and load into DB. Creates tables if needed.
    """
    path = Path(stdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"STDF file not found: {stdf_path}")
    engine = get_engine(db_url)
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine, autoflush=True)
    session = SessionLocal()
    sink = StdfToDbSink(
        session,
        company_name=company_name,
        product_name=product_name,
        stage_name=stage_name,
    )
    parser = Parser(inp=open(path, "rb"))
    parser.addSink(sink)
    try:
        parser.parse()
    finally:
        parser.inp.close()
    session.commit()
    session.close()
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python stdf_loader.py <file.stdf> [company] [product] [stage]")
        sys.exit(1)
    stdf_file = sys.argv[1]
    company = sys.argv[2] if len(sys.argv) > 2 else None
    product = sys.argv[3] if len(sys.argv) > 3 else None
    stage = sys.argv[4] if len(sys.argv) > 4 else None
    load_stdf(stdf_file, company_name=company, product_name=product, stage_name=stage)
    print("Done.")
