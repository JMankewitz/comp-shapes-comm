# Tangram Similiarity Analyses

This project preprocesses and analyzes sets of tangrams using CLIP embeddings for the future use in the Compositional Shapes project. 

## Project Structure

generate_tangrams/
├── data/
│   ├── raw_tangrams/         # Original tangrams from Kilogram
│   ├── processed_tangrams/   # Transformed tangrams
│   │   ├── processed_pngs /  # Black, borderless pngs
│   │   ├── compositional-transparent/  # Compositional tangrams for experiment use
│   │   └── compositional-white/        # Compositional tangrams for model use
│   ├── tangram_map.csv      # Maps raw to processed images
│   └── embeddings/          # CLIP embeddings
├── outputs/
│   ├── similarity_results/ # Analysis results
│   └── checkpoints/        # Saved states
├── src/
│   ├── preprocess.py      # Image processing
│   ├── embedding.py       # CLIP embedding extraction
│   ├── similarity.py      # Similarity analysis
│   └── utils.py           # Helper functions
└── notebooks/
│   ├── develop.ipynb      # Development testing
│   └── analysis.ipynb     # Results analysis

## Setup

1. Install requirements:

For now, use conda environments - might move to container?

```bash
pip install -r requirements.txt
```
## Pipeline

1. Image Processing: Transform raw images and save both transparent and white background versions
2. Embedding Extraction: Generate CLIP embeddings for processed images
3. Similarity Analysis: Analyze similarity between sets of 16 images

## Notes

Currently using base CLIP model for embeddings
Processing ~500 sets of 16 images each