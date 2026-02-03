"""
Relational schema: Company -> Product -> Stage -> TestProgram -> Lot -> Wafer -> Die -> Bin / TestSuite -> TestItem.
SQLAlchemy ORM models for STDF hierarchy.
"""
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.pool import StaticPool

Base = declarative_base()


class Company(Base):
    __tablename__ = "company"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "product"
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("company.id"), nullable=False)
    name = Column(String(255), nullable=False)
    company = relationship("Company", back_populates="products")
    stages = relationship("Stage", back_populates="product", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_company_product"),)


class Stage(Base):
    __tablename__ = "stage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    name = Column(String(255), nullable=False)
    product = relationship("Product", back_populates="stages")
    test_programs = relationship("TestProgram", back_populates="stage", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("product_id", "name", name="uq_product_stage"),)


class TestProgram(Base):
    __tablename__ = "test_program"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stage_id = Column(Integer, ForeignKey("stage.id"), nullable=False)
    name = Column(String(255), nullable=False)   # e.g. JOB_NAM
    revision = Column(String(64), default="")     # JOB_REV
    stage = relationship("Stage", back_populates="test_programs")
    lots = relationship("Lot", back_populates="test_program", cascade="all, delete-orphan")
    test_suites = relationship("TestSuite", back_populates="test_program", cascade="all, delete-orphan")
    test_definitions = relationship("TestDefinition", back_populates="test_program", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("stage_id", "name", "revision", name="uq_stage_program"),)


class Lot(Base):
    __tablename__ = "lot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    test_program_id = Column(Integer, ForeignKey("test_program.id"), nullable=False)
    lot_id = Column(String(255), nullable=False)   # LOT_ID from MIR
    part_typ = Column(String(255), default="")    # PART_TYP
    setup_t = Column(DateTime, nullable=True)
    start_t = Column(DateTime, nullable=True)
    finish_t = Column(DateTime, nullable=True)
    # Tester info from MIR
    tstr_typ = Column(String(64), default="")     # Tester type
    node_nam = Column(String(64), default="")     # Node name
    facil_id = Column(String(64), default="")     # Facility ID
    floor_id = Column(String(64), default="")     # Floor ID
    stat_num = Column(Integer, nullable=True)     # Station number
    exec_typ = Column(String(64), default="")     # Exec type
    exec_ver = Column(String(64), default="")     # Exec version
    test_program = relationship("TestProgram", back_populates="lots")
    wafers = relationship("Wafer", back_populates="lot", cascade="all, delete-orphan")
    dies = relationship("Die", back_populates="lot", cascade="all, delete-orphan")
    site_equipment = relationship("SiteEquipment", back_populates="lot", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("test_program_id", "lot_id", name="uq_program_lot"),
        Index("ix_lot_lot_id", "lot_id"),
    )


class Wafer(Base):
    __tablename__ = "wafer"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(Integer, ForeignKey("lot.id"), nullable=False)
    wafer_id = Column(String(255), nullable=False)   # WAFER_ID from WIR/WRR
    head_num = Column(Integer, default=1)
    site_grp = Column(Integer, default=255)
    start_t = Column(DateTime, nullable=True)
    finish_t = Column(DateTime, nullable=True)
    part_cnt = Column(Integer, default=0)
    good_cnt = Column(Integer, default=0)
    lot = relationship("Lot", back_populates="wafers")
    dies = relationship("Die", back_populates="wafer", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("lot_id", "wafer_id", "head_num", name="uq_lot_wafer"),
        Index("ix_wafer_wafer_id", "wafer_id"),
    )


class Die(Base):
    __tablename__ = "die"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(Integer, ForeignKey("lot.id"), nullable=False)
    wafer_id = Column(Integer, ForeignKey("wafer.id"), nullable=True)  # null for package test
    head_num = Column(Integer, default=1)
    site_num = Column(Integer, default=1)
    x_coord = Column(Integer, nullable=True)   # -32768 = invalid in STDF
    y_coord = Column(Integer, nullable=True)
    part_id = Column(String(255), default="")
    hard_bin = Column(Integer, nullable=True)
    soft_bin = Column(Integer, nullable=True)
    part_flg = Column(Integer, default=0)
    num_test = Column(Integer, default=0)
    test_t = Column(Integer, default=0)       # elapsed test time ms
    lot = relationship("Lot", back_populates="dies")
    wafer = relationship("Wafer", back_populates="dies")
    bin_record = relationship("Bin", back_populates="die", uselist=False, cascade="all, delete-orphan")
    test_items = relationship("TestItem", back_populates="die", cascade="all, delete-orphan")
    __table_args__ = (
        Index("ix_die_wafer_site", "wafer_id", "head_num", "site_num"),
        Index("ix_die_xy", "wafer_id", "x_coord", "y_coord"),
        Index("ix_die_bins", "hard_bin", "soft_bin"),
    )


class Bin(Base):
    """Hard/soft bin summary per die (from PRR)."""
    __tablename__ = "bin"
    id = Column(Integer, primary_key=True, autoincrement=True)
    die_id = Column(Integer, ForeignKey("die.id"), nullable=False)
    hard_bin = Column(Integer, nullable=False)
    soft_bin = Column(Integer, nullable=True)
    hard_bin_name = Column(String(255), default="")
    soft_bin_name = Column(String(255), default="")
    die = relationship("Die", back_populates="bin_record")


class TestSuite(Base):
    """Logical group of tests (e.g. from BPS/EPS or TSR SEQ_NAME)."""
    __tablename__ = "test_suite"
    id = Column(Integer, primary_key=True, autoincrement=True)
    test_program_id = Column(Integer, ForeignKey("test_program.id"), nullable=False)
    name = Column(String(255), nullable=False)
    test_program = relationship("TestProgram", back_populates="test_suites")
    test_definitions = relationship("TestDefinition", back_populates="test_suite", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("test_program_id", "name", name="uq_program_suite"),)


class TestDefinition(Base):
    """Test definition from TSR: links test_num to TestSuite, defines test name/type."""
    __tablename__ = "test_definition"
    id = Column(Integer, primary_key=True, autoincrement=True)
    test_suite_id = Column(Integer, ForeignKey("test_suite.id"), nullable=False)
    test_program_id = Column(Integer, ForeignKey("test_program.id"), nullable=False)
    test_num = Column(Integer, nullable=False)
    test_type = Column(String(8), default="")   # P=PTR, F=FTR, M=MPR
    test_nam = Column(String(512), default="")
    test_lbl = Column(String(255), default="")
    exec_cnt = Column(Integer, nullable=True)
    fail_cnt = Column(Integer, nullable=True)
    alrm_cnt = Column(Integer, nullable=True)
    test_suite = relationship("TestSuite", back_populates="test_definitions")
    test_program = relationship("TestProgram", back_populates="test_definitions")
    __table_args__ = (
        UniqueConstraint("test_program_id", "test_num", name="uq_program_test_num"),
        Index("ix_test_def_test_num", "test_num"),
    )


class SiteEquipment(Base):
    """Site equipment from SDR: probe card, load board, handler, DIB, etc."""
    __tablename__ = "site_equipment"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(Integer, ForeignKey("lot.id"), nullable=False)
    head_num = Column(Integer, default=1)
    site_grp = Column(Integer, default=255)
    hand_typ = Column(String(128), default="")   # Handler/prober type
    hand_id = Column(String(128), default="")
    card_typ = Column(String(128), default="")   # Probe card type
    card_id = Column(String(128), default="")
    load_typ = Column(String(128), default="")   # Load board type
    load_id = Column(String(128), default="")
    dib_typ = Column(String(128), default="")
    dib_id = Column(String(128), default="")
    cabl_typ = Column(String(128), default="")
    cabl_id = Column(String(128), default="")
    cont_typ = Column(String(128), default="")   # Contactor type
    cont_id = Column(String(128), default="")
    lot = relationship("Lot", back_populates="site_equipment")
    __table_args__ = (UniqueConstraint("lot_id", "head_num", "site_grp", name="uq_lot_head_site"),)


class TestItem(Base):
    """Single parametric (PTR) or functional (FTR) test result per die."""
    __tablename__ = "test_item"
    id = Column(Integer, primary_key=True, autoincrement=True)
    die_id = Column(Integer, ForeignKey("die.id"), nullable=False)
    test_num = Column(Integer, nullable=False)
    test_txt = Column(String(512), default="")
    test_type = Column(String(8), nullable=False)   # 'PTR' or 'FTR'
    test_suite_id = Column(Integer, ForeignKey("test_suite.id"), nullable=True)  # from TestDefinition
    result = Column(Float, nullable=True)           # PTR RESULT; FTR use pass/fail
    units = Column(String(64), default="")
    lo_limit = Column(Float, nullable=True)
    hi_limit = Column(Float, nullable=True)
    pass_fail = Column(Integer, nullable=True)      # 0 pass, 1 fail, null unknown
    die = relationship("Die", back_populates="test_items")
    test_suite = relationship("TestSuite", backref="test_items")
    __table_args__ = (
        UniqueConstraint("die_id", "test_num", "test_type", name="uq_die_test"),
        Index("ix_test_item_test_num", "test_num"),
        Index("ix_test_item_name", "test_txt"),
        Index("ix_test_item_suite", "test_suite_id"),
    )


def get_engine(database_url: str = None, use_static_pool: bool = False):
    from config import DATABASE_URL
    url = database_url or DATABASE_URL
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if use_static_pool:
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def init_db(engine=None):
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate_add_columns(engine)


def _migrate_add_columns(engine):
    """Add new columns to existing tables if missing (SQLite)."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    if engine.dialect.name != "sqlite":
        return
    lot_cols = {c["name"] for c in insp.get_columns("lot")} if "lot" in insp.get_table_names() else set()
    new_lot_cols = [
        ("tstr_typ", "VARCHAR(64) DEFAULT ''"),
        ("node_nam", "VARCHAR(64) DEFAULT ''"),
        ("facil_id", "VARCHAR(64) DEFAULT ''"),
        ("floor_id", "VARCHAR(64) DEFAULT ''"),
        ("stat_num", "INTEGER"),
        ("exec_typ", "VARCHAR(64) DEFAULT ''"),
        ("exec_ver", "VARCHAR(64) DEFAULT ''"),
    ]
    with engine.begin() as conn:
        for col, typ in new_lot_cols:
            if col not in lot_cols:
                try:
                    conn.execute(text(f"ALTER TABLE lot ADD COLUMN {col} {typ}"))
                except Exception:
                    pass
        if "test_item" in insp.get_table_names():
            ti_cols = {c["name"] for c in insp.get_columns("test_item")}
            if "test_suite_id" not in ti_cols:
                try:
                    conn.execute(text("ALTER TABLE test_item ADD COLUMN test_suite_id INTEGER"))
                except Exception:
                    pass
