import pandas as pd
import os
import re

print(f"Current working directory: {os.getcwd()}")

# Load model

from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

# for each dataset...

# get pairwise chats for each game
