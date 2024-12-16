# config file
from config import PROCESSED_TANGRAMS_WHITE

# code to set up the CLIP model and embeddings
from transformers import CLIPProcessor, CLIPModel 
from transformers import AutoModel, AutoProcessor

from huggingface_hub import hf_hub_download
import torch
import torch.nn as nn
from torchvision.transforms import Compose, Resize, CenterCrop, ToTensor, Normalize
from PIL import Image
import clip

def setup_model(model_name, device):
    device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(device)
    model.eval()
    return model, processor, device

def preprocess_image(image_path, preprocess, device):
    inputs = preprocess(images = Image.open(image_path), return_tensors = "pt")
    return inputs.to(device)

def get_image_embedding(image, model, preprocess, device):
    if not isinstance(image, torch.Tensor):
            image = preprocess_image(image, preprocess, device)
    with torch.no_grad():
            features = model.get_image_features(**image)

            #outputs = model.vision_model(pixel_values = image, output_hidden_states=True)
    #features = outputs.last_hidden_state
    return features

class FTCLIP(nn.Module):
    def __init__(self):
        super(FTCLIP, self).__init__()
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

        model, _ = clip.load("ViT-B/32", device=self._device, jit=False)
        model = model.float()
        self.model = model
        self.encode_image = model.encode_image
        self.encode_text = model.encode_text

        self.logit_scale = nn.Parameter(torch.ones([]) * np.log(1 / 0.07))

        self.loss = nn.CrossEntropyLoss()
    def compute_loss(self, predicted, gold_label):
        return self.loss(predicted, gold_label)

    def compute_norm(self, features):
        return features / features.norm(dim=-1, keepdim=True).float()

    def compute_similarity(self, texts_features, images_features):
        return texts_features @ images_features.t()
    
    def forward(self, images, texts):
      # Generate image features
      I_e=self.encode_image(images.to(self._device)).float()

      # Normalize features
      images_features = self.compute_norm(I_e)

      return images_features
    
    def load(self, state_dict):
        self.load_state_dict(state_dict)

    def save(self, model_path, epoch, optim, lr_scheduler, val_loss, loss, acc, count):
        save_dict = {
        'epoch': epoch,
        'model_state_dict': self.state_dict(),
        'optimizer_state_dict': optim.state_dict(),
        'val_loss': val_loss,
        'loss': loss,
        'val_accuracy': acc,
        'patience': count
        }
        if lr_scheduler is not None:
            save_dict["lr_scheduler_state_dict"] = lr_scheduler.state_dict()
        torch.save(save_dict, model_path)

def preprocess_for_clip(pil_image):
    # CLIP's image preprocessing
    transform = Compose([
        Resize(224, interpolation=Image.BICUBIC),
        CenterCrop(224),
        ToTensor(),
        Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))
    ])

    return transform(pil_image).unsqueeze(0)