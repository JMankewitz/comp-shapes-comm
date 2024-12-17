import argparse
import sys
from pathlib import Path
sys.path.append(str(Path.cwd().parent / "src"))

from config import PROCESSED_TANGRAMS_WHITE, MAPPING_FILE, OUTPUT_DIR
from similarity import SimilarityAnalysisManager

def parse_args():
    parser = argparse.ArgumentParser(description='Generate and analyze image sets')
    parser.add_argument('--n-sets', type=int, default=100,
                       help='Number of sets to generate')
    parser.add_argument('--batch-size', type=int, default=25,
                       help='Number of sets to process in each batch')
    parser.add_argument('--set-type', type=str, choices=['comp', 'noncomp'],
                       default='comp', help='Type of set generation to use')
    parser.add_argument('--start-batch', type=int, default=0,
                       help='Batch number to start/resume from')
    parser.add_argument('--device', type=str, choices=['cuda', 'cpu'],
                       help='Device to use for computation (default: auto-detect)')
    return parser.parse_args()

def main():
    args = parse_args()

    manager = SimilarityAnalysisManager(MAPPING_FILE, 
                                               PROCESSED_TANGRAMS_WHITE, 
                                               set_type = args.set_type,
                                               repo_id = "lil-lab/kilogram-models",
                                               device=args.device)
    manager.process_sets(
            n_sets=args.n_sets,
            batch_size=args.batch_size,
            start_batch=args.start_batch
        )
    manager.save_set_summaries(OUTPUT_DIR / f"similarity_results/set_summaries_{args.set_type}.csv")


if __name__ == "__main__":
    main()