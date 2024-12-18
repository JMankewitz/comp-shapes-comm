import json
import pickle
import torch
from pathlib import Path
from config import CHECKPOINTS, PROCESSED_TANGRAMS_FINAL
import statistics

import shutil

condition_type = "comp"

checkpoints = CHECKPOINTS / condition_type
checkpoint_files = sorted(checkpoints.glob('checkpoint_batch_*.pkl'))
last_checkpoint = checkpoint_files[-1]

with open(last_checkpoint, 'rb') as f:
    checkpoint = pickle.load(f)
    image_sets = checkpoint['sets']

max_similarities = [
        image_sets[set].get_summary_stats()['max_similarity'] 
        for set in image_sets
    ]

median_max = statistics.median(max_similarities)

def get_json_sets(image_sets, median_max):
    kept_set = []
    tangrams_to_copy = set()
    for image_set in image_sets:
        similiarity = image_sets[image_set].get_summary_stats()['max_similarity']
        if similiarity <= median_max:        
            tangram_numbers = []
            for path in image_sets[image_set].image_paths:
                tangrams_to_copy.add(path)
                top, bottom = path.stem.split('_')  # stem removes .png extension
                tangram_numbers.append((int(top), int(bottom)))
            
            top_tangrams = []
            bottom_tangrams = []
            for top, bottom in tangram_numbers:
                if top not in top_tangrams:
                    top_tangrams.append(top)
                if bottom not in bottom_tangrams:
                    bottom_tangrams.append(bottom)
            
            set_data = {
            "set_id": image_sets[image_set].set_id,
            "top_tangrams": top_tangrams,
            "bottom_tangrams": bottom_tangrams,
            "max_sim": similiarity
        }
            kept_set.append(set_data)
    return kept_set, tangrams_to_copy

kept_set, tangrams_to_copy = get_json_sets(image_sets, median_max)

with open(f'{condition_type}_sets.json', 'w') as f:
    json.dump(kept_set, f, indent=2)

print(f"Copying {len(tangrams_to_copy)} unique tangram files...")

for src_path in tangrams_to_copy:
    dest_path = PROCESSED_TANGRAMS_FINAL / src_path.name
    #print(dest_path)
    shutil.copy2(src_path, dest_path)
