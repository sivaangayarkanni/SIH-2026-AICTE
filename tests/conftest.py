import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="sealcheck-test-")
os.environ["SEALCHECK_DATA_DIR"] = TMP
os.environ["SEALCHECK_SAMPLES_DIR"] = TMP + "/samples"
os.environ.setdefault("RATE_LIMIT", "off")  # test_ops exercises the limiter directly
os.environ.setdefault("LOG_FORMAT", "plain")
if os.getenv("TEST_DATABASE_URL"):  # e.g. postgresql+psycopg://sealcheck@127.0.0.1:5544/sealcheck_test
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ.pop("DATABASE_URL", None)
    os.environ["SEALCHECK_DB_URL"] = f"sqlite:///{TMP}/test.db"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "seed"))
# demo PKI / trust roots for signature tests are generated into the temp data dir
import generate_samples  # noqa: E402
generate_samples.main()  # fresh synthetic PKI + samples signed by it
SAMPLES = Path(TMP) / "samples"
