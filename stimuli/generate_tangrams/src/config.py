from pathlib import Path

# project paths

GEN_TAN_ROOT = Path(__file__).parent.parent

DATA_DIR = GEN_TAN_ROOT / "data"

# data paths

RAW_TANGRAMS_SVGS = DATA_DIR / "raw_tangrams" / "raw_svgs"
PROCESSED_TANGRAMS_SVGS = DATA_DIR / "raw_tangrams" / "fixed_svgs"
PROCESSED_PNGS = DATA_DIR / "processed_tangrams" / "processed_pngs"
PROCESSED_TANGRAMS_WHITE = DATA_DIR / "processed_tangrams" / "compositional-white"
PROCESSED_TANGRAMS_TRANS = DATA_DIR / "processed_tangrams" / "compositional-trans"
PROCESSED_TANGRAMS_FINAL = DATA_DIR / "processed_tangrams" / "compositional-final"

MAPPING_FILE = DATA_DIR / "tangram_map.csv"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"

# output paths

OUTPUT_DIR = GEN_TAN_ROOT / "outputs"
SIMILARITY_RESULTS = OUTPUT_DIR / "similarity_results"
CHECKPOINTS = OUTPUT_DIR / "checkpoints"