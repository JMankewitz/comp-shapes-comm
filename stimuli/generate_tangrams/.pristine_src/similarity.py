from embedding import setup_model, get_image_embedding, setup_pretrained_model
from typing import Optional
import torch
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
from config import PROCESSED_TANGRAMS_WHITE, MAPPING_FILE, CHECKPOINTS
import math
import pickle
import time


class ImageSet:
    def __init__(self, set_id, image_paths, set_type):
        self.set_id = set_id
        self.image_paths = image_paths
        self.embeddings = None
        self.similarity_matrix = None
        self.set_type = set_type
    
    def extract_embeddings(self, model, preprocess, device):
        embeddings = []
        for path in self.image_paths:
            image_embeddings = get_image_embedding(path, model, preprocess, device)
            embeddings.append(image_embeddings)
        self.embeddings = torch.cat(embeddings)
    
    def compute_cosine_similarities(self):
        if self.embeddings == None:
            raise ValueError("Need to extract embeddings first!")

        #embeddings = self.embeddings.mean(dim=1)
        embeddings = self.embeddings
        #normalized = embeddings / embeddings.norm(dim=1, keepdim=True)
        # matmul(A, B.t()) is the full pairwise sim
        self.similarity_matrix = torch.matmul(embeddings, embeddings.T)

    def get_pair_similarity(self, idx1, idx2):
        # get the similarity between any two items
        return self.similarity_matrix[idx1, idx2].item()
    
    def get_pairwise_embeddings(self):
        n = len(self.image_paths)
        indices = torch.triu_indices(n, n, offset=1)
        similarities = self.similarity_matrix[indices[0], indices[1]]
        return(similarities)
    
    def get_summary_stats(self):
        # Remove self-similarities from diagonal
        similarities = self.get_pairwise_embeddings()
        return {
            'mean_similarity': similarities.mean().item(),
            'min_similarity': similarities.min().item(),
            'max_similarity': similarities.max().item(),
            'median_similarity': similarities.median().item()
        }
    
    def get_most_similar_pairs(self, n=2):
        """Get the n most similar image pairs"""
        similarities = self.similarity_matrix - torch.eye(len(self.image_paths))
        values, indices = similarities.view(-1).topk(n)
        pairs = [(idx // len(self.image_paths), idx % len(self.image_paths)) 
                for idx in indices]
        return list(zip(pairs, values))
    
    def get_all_pairs_ranked(self, reverse = False):
        if self.similarity_matrix is None:
            raise ValueError("Need to compute similarities first!")
        
        n_images = len(self.image_paths)

        pairs = []

        for i in range(n_images):
            for j in range(i+1, n_images):
                similarity = self.similarity_matrix[i, j].item()
                pairs.append({
                'image1_idx': i,
                'image2_idx': j,
                'image1_path': self.image_paths[i],
                'image2_path': self.image_paths[j],
                'similarity': similarity
            })
        
        pairs.sort(key=lambda x: x['similarity'], reverse=not reverse)

        return pairs
    
    def display_ranked_pairs(self, n_pairs=None, figsize=(6, 3), reverse = False):
        
        if self.similarity_matrix is None:
            raise ValueError("Need to compute similarities first!")
        
        # Get ranked pairs
        ranked_pairs = self.get_all_pairs_ranked(reverse = reverse)
        if n_pairs:
            ranked_pairs = ranked_pairs[:n_pairs]
        
        # Create figure for each pair
        for i, pair in enumerate(ranked_pairs):
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
            
            # Load and display images
            img1 = Image.open(pair['image1_path'])
            img2 = Image.open(pair['image2_path'])
            
            ax1.imshow(img1)
            ax2.imshow(img2)
            
            # Remove axes
            ax1.axis('off')
            ax2.axis('off')
            
            # Get filenames from Path objects
            img1_name = pair['image1_path'].name  # .name gets just the filename
            img2_name = pair['image2_path'].name
        
            # Add similarity score as title
            plt.suptitle(f"Similarity: {pair['similarity']:.3f}\n"
                    f"Images: {img1_name} and {img2_name}")
            plt.tight_layout()
            plt.show()

class SimilarityAnalysisManager:
    def __init__(
        self,
        mapping_file,
        image_folder,
        set_type,
        repo_id: str = "lil-lab/kilogram-models",
        file_paths: list = ["clip_controlled/whole+black/model0.pth",
             "clip_controlled/whole+black/model1.pth",
             "clip_controlled/whole+black/model2.pth"],
        device: Optional[str] = None
        ):
        self.set_size = 16
        self.set_type = set_type
        self.image_folder = image_folder
        self.shapes = pd.read_csv(mapping_file, sep=',', header=None)
        self.subshapes = self.shapes.iloc[:,1:].values

        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.model, self.preprocess, self.device = setup_pretrained_model(repo_id, file_paths, self.device)

        self.checkpoint_dir = CHECKPOINTS / set_type

        self.sets = {}
        self.current_set_id = 0

    def gen_target_images(self):
        if self.set_type == "comp":
            shape_samples = np.random.choice(self.subshapes.shape[0], (int(math.sqrt(self.set_size)))*2, replace=False)
            shape_tops = shape_samples[0:(int(math.sqrt(self.set_size)))]
            shape_bottoms = shape_samples[-(int(math.sqrt(self.set_size))):]
            final_shapes = []
            for i in shape_tops:
                for j in shape_bottoms:
                    final_shapes.append(self.image_folder / f"{i}_{j}.png")
        else:
            shape_samples = np.random.choice(self.subshapes.shape[0], self.set_size*2, replace=False)
            shape_tops = shape_samples[0:self.set_size]
            shape_bottoms = shape_samples[-self.set_size:]
            final_shapes = []
            for i in range(len(shape_tops)):
                final_shapes.append(self.image_folder / f"{shape_tops[i]}_{shape_bottoms[i]}.png")
        return final_shapes
    
    def create_image_set(self):
        image_paths = self.gen_target_images()
        image_set = ImageSet(self.current_set_id, image_paths, self.set_type)
        image_set.extract_embeddings(self.model, self.preprocess, self.device)
        image_set.compute_cosine_similarities()
        image_set.get_summary_stats()
        self.sets[self.current_set_id] = image_set
        self.current_set_id += 1

        return image_set
    
    def save_checkpoint(self, batch_num):
        checkpoint = {
            'current_set_id': self.current_set_id,
            'sets': self.sets,
            'batch_num': batch_num
        }

        checkpoint_path = self.checkpoint_dir / f'checkpoint_batch_{batch_num}.pkl'
        with open(checkpoint_path, 'wb') as f:
            pickle.dump(checkpoint, f)

    def load_checkpoint(self, batch_num):
        checkpoint_path = self.checkpoint_dir / f'checkpoint_batch_{batch_num}.pkl'
        if checkpoint_path.exists():
            with open(checkpoint_path, 'rb') as f:
                checkpoint = pickle.load(f)
            self.current_set_id = checkpoint['current_set_id']
            self.sets = checkpoint['sets']
            return checkpoint['batch_num']
        return 0
    
    def process_sets(self, n_sets, batch_size = 5, start_batch = 0):
        total_batches = (n_sets + batch_size - 1) // batch_size

        if start_batch > 0:
            batch_num = self.load_checkpoint(start_batch)
            print(f"Resumed from batch {batch_num}")
        else:
            batch_num = 0
        
        try:
            for batch in range(batch_num, total_batches):
                start_time = time.time()

                start_id = batch*batch_size
                end_id = min((batch+1)*batch_size, n_sets)
                sets_in_batch = end_id - start_id

                print(f"\nProcessing batch {batch+1}/{total_batches}")
                print(f"Sets {start_id} to {end_id-1}")

                for _ in range(sets_in_batch):
                    self.create_image_set()
                    if self.current_set_id % 25 == 0:
                        print(f"Processed {self.current_set_id} sets total")
                self.save_checkpoint(batch)

                batch_time = time.time() - start_time
                print(f"Batch {batch+1} completed in {batch_time:.2f} seconds")
                print(f"Checkpoint saved: batch_{batch}.pkl")

        except KeyboardInterrupt:
            print("\nProcess interrupted! Saving checkpoint...")
            self.save_checkpoint(batch)
            print(f"Progress saved to batch_{batch}.pkl")
            raise

    def get_set(self, set_id):
        return self.sets.get(set_id)
    
    def save_set_summaries(self, output_path):
        print(f"Output path: {output_path}")
        print(f"Output path type: {type(output_path)}")
        print(f"Parent directory: {output_path.parent}")
        print(f"Parent exists?: {output_path.parent.exists()}")
        summaries = []
        for set_id, image_set in self.sets.items():
            stats = image_set.get_summary_stats()
            stats['set_id'] = set_id
            stats['set_type'] = image_set.set_type
            summaries.append(stats)
        
        df = pd.DataFrame(summaries)
        df.to_csv(output_path)
        return summaries
    
    def save_sets_to_json(self, output_path):
        pass