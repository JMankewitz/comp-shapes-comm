import pandas as pd
import os
import re

print(f"Current working directory: {os.getcwd()}")

def load_data(data_name, study_name, run_num_list):
    
    base_path = os.path.join('..', 'data', 'processed_data', study_name)
    source_files = []

    print(f"searching in: {base_path}")

    for root, dirs, files in os.walk(base_path):
        print(files)
        for file in files:
            # Check if the file matches our pattern (e.g., "games.csv")
            if file == f"{data_name}.csv":
                # Get the run number from the path
                run_folder = os.path.basename(root)  # This gets the immediate parent folder name
                if any(run_folder.endswith(run_num) for run_num in run_num_list):
                    full_path = os.path.join(root, file)
                    source_files.append(full_path)
    
    print(f"Source files found for {data_name}:", source_files)
    
    if not source_files:
        print(f"Warning: No files found for {data_name}")
        return pd.DataFrame()
    
    # Read and concatenate all found CSV files
    dfs = []
    for file in source_files:
        try:
            df = pd.read_csv(file)
            dfs.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")
    
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

study_run_name = "run_v3"
run_num = ["0", "1", "2"]

d_game = load_data("games", study_run_name, run_num)
d_round = load_data("rounds", study_run_name, run_num)
d_chat = load_data("chats", study_run_name, run_num)
d_players = load_data("players", study_run_name, run_num)

d_chat_clean = d_chat.merge(d_round, how='left').merge(d_game, how='left')

def clean_text(text):
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    text = re.sub(r'\s+', ' ', text)  # Replace multiple spaces with single space
    text = text.strip()  # Remove leading and trailing whitespace
    return text

# Clean the text and compute lengths
d_chat_clean['text'] = d_chat_clean['text'].apply(clean_text)
d_chat_clean['utt_length_chars'] = d_chat_clean['text'].str.len()
d_chat_clean['utt_length_words'] = d_chat_clean['text'].str.split().str.len()


chat_by_trial = d_chat_clean.groupby(['gameID', 'roundID','index', 'repNum', 'playerID','contextStructure']).agg({
    'text': lambda x: ', '.join(x),
    'utt_length_words': 'sum',
    'utt_length_chars': 'sum'
}).reset_index()

chat_by_trial.rename(columns={'utt_length_words': 'total_num_words', 'utt_length_chars': 'total_num_chars'}, inplace=True)
chat_by_trial['index'] = chat_by_trial.index

from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

embeddings = model.encode(chat_by_trial['text'])

# Compute cosine similarities
similarities = model.similarity(embeddings, embeddings)

chat_by_trial.rename(columns = {"index":"index1",
                                "roundID":"roundID1",
                                "repNum":"repNum1"})

similarity_df = pd.DataFrame(similarities.numpy(), index=chat_by_trial.index, columns=chat_by_trial.index)
result = similarity_df.stack().reset_index()

result.columns = ['index1', 'index2', 'value']

# Remove duplicate pairs if the matrix is symmetric
result = result[result['index1'] < result['index2']]

word1 = chat_by_trial.rename(columns = {"index":"index1",
                                "roundID":"roundID1",
                                "repNum":"repNum1",
                                "playerID":"playerID1",
                                "text":"text1"})[["index1",  "text1", "roundID1", "repNum1", "playerID1"]]

word2 = chat_by_trial.rename(columns = {"index":"index2",
                                "roundID":"roundID2",
                                "repNum":"repNum2",
                                "playerID":"playerID2",
                                "text":"text2"})[["index2",  "text2", "roundID2", "repNum2", "playerID2"]]

similarity_df_merged = result.merge(word1, how = "left").merge(word2, how = "left")

similarity_df_merged.to_csv(os.path.join('..','data', 'processed_data', "chat_pairwise_similarities.csv"))