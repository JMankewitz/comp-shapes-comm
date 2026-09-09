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
import numpy as np

def resolve_device(device):
    """Map a device request to a concrete torch device string.

    `None` reproduces the original cuda-or-cpu behaviour exactly, so existing
    call sites are unaffected. MPS is never selected implicitly -- ask for it
    with "mps", or with "auto" to prefer cuda > mps > cpu.
    """
    if device is None:
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    return device


def setup_pretrained_model(repo_id, file_paths, device, eval_mode=False):
    """Load the KiloGram fine-tuned CLIP, merging the three .pth parts.

    eval_mode defaults to False because the published Experiment 1 numbers were
    produced with the model left in train mode (the original never called
    .eval()). CLIP ViT-B/32 has no dropout and only LayerNorm, so eval should be
    numerically identical -- but that is verified in 01_validate_refactor.py
    rather than assumed here.
    """
    device = resolve_device(device)
    preprocessor = preprocess_for_clip
    pth_paths = [hf_hub_download(repo_id=repo_id, filename=filename) for filename in file_paths]
    # weights land on CPU, then the assembled model is moved once
    model_parts = [torch.load(pth_path, map_location="cpu") for pth_path in pth_paths]

    combined_state_dict = {}
    for part in model_parts:
        combined_state_dict.update(part)
    model = FTCLIP(device=device)
    model.load_state_dict(combined_state_dict['model_state_dict']) ### load the weights into the model
    model = model.to(device)
    if eval_mode:
        model.eval()
    return model, preprocessor, device

def preprocess_for_clip(image_path):
    # CLIP's image preprocessing
    pil_image = Image.open(image_path)
    transform = Compose([
        Resize(224, interpolation=Image.BICUBIC),
        CenterCrop(224),
        ToTensor(),
        Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))
    ])

    return transform(pil_image).unsqueeze(0)

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
            image = preprocess_for_clip(image)
    with torch.no_grad():
            features = model.forward(image)
    return features


# The transform preprocess_for_clip applies, minus the unsqueeze(0) that makes
# it a batch of one. Built once: reconstructing Compose per image is pure waste
# at 220,900 images.
_CLIP_TRANSFORM = Compose([
    Resize(224, interpolation=Image.BICUBIC),
    CenterCrop(224),
    ToTensor(),
    Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))
])


class ImagePathDataset(torch.utils.data.Dataset):
    """Decode + preprocess PNGs by path, so DataLoader workers can parallelize it.

    PNG decode is the bottleneck at this scale, not the forward pass.
    """

    def __init__(self, paths):
        self.paths = [str(p) for p in paths]

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        return _CLIP_TRANSFORM(Image.open(self.paths[i]))


def _worker_init(worker_id):
    """One compute thread per worker.

    Workers inherit torch's default intra-op thread count, so N workers each
    spin up N threads and oversubscribe the machine. The transforms here are
    tiny; threading them is pure contention.
    """
    torch.set_num_threads(1)


def make_loader(paths, batch_size=256, num_workers=0, device="cpu",
                prefetch_factor=2):
    """DataLoader over image paths, preserving order.

    Build ONE of these per run, not per unit of output -- see embed_stream.

    A note on num_workers, measured the hard way. On Linux, multiprocessing
    forks, so workers inherit the loaded interpreter cheaply and parallel PNG
    decode is a real win; use 8-16 on the cluster. On macOS the start method is
    SPAWN, so every worker relaunches Python and re-imports torch + clip, which
    on a memory-pressured machine is catastrophic (benchmarked at 7 img/s with
    8 workers vs 118 with none). Use num_workers=0 on the Mac.

    prefetch_factor matters more than it looks: the queue holds
    num_workers * prefetch_factor * batch_size preprocessed 3x224x224 float32
    tensors, i.e. ~600 KB each. At 8/4/256 that is 4.9 GB of RAM in flight.
    """
    kw = {}
    if num_workers > 0:
        kw.update(persistent_workers=True,
                  prefetch_factor=prefetch_factor,
                  worker_init_fn=_worker_init)
    return torch.utils.data.DataLoader(
        ImagePathDataset(paths),
        batch_size=batch_size,
        shuffle=False,           # order must match `paths` exactly
        num_workers=num_workers,
        pin_memory=(device == "cuda"),
        **kw,
    )


def embed_stream(paths, model, device, batch_size=256, num_workers=0,
                 prefetch_factor=2):
    """Yield (start_index, float32 CPU tensor) per batch, in order.

    Streaming rather than returning one tensor lets a caller slice fixed-size
    chunks out mid-run (see 02_embed_shards.py) without one loader per chunk.
    """
    if len(paths) == 0:
        return
    loader = make_loader(paths, batch_size, num_workers, device, prefetch_factor)
    i = 0
    with torch.no_grad():
        for batch in loader:
            feats = model.forward(batch.to(device)).float().cpu()
            yield i, feats
            i += feats.shape[0]


def embed_paths(paths, model, device, batch_size=256, num_workers=0,
                progress=None):
    """Embed images in batches. Returns a float32 CPU tensor (len(paths), 512).

    Replaces the one-image-at-a-time loop, which measured ~35 ms/image on CPU
    (~2.1 h for the full 220,900).

    Note that batching changes the reduction order inside the ViT relative to
    batch-of-1, so results are not guaranteed bit-identical to the original
    loop. 01_validate_refactor.py measures the actual deviation (~2e-06 on CPU).
    """
    if len(paths) == 0:
        return torch.empty(0, 512)

    out = []
    for _, feats in embed_stream(paths, model, device, batch_size, num_workers):
        out.append(feats)
        if progress is not None:
            progress(feats.shape[0])
    return torch.cat(out)

class FTCLIP(nn.Module):
    def __init__(self, device=None):
        super(FTCLIP, self).__init__()
        # Previously hardcoded to cuda-or-cpu, which silently pinned the forward
        # pass to CPU on Apple silicon no matter what device was requested.
        self._device = resolve_device(device)

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
    
    def forward(self, images):
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