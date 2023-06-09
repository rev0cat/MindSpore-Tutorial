import os
import pickle

import mindspore.dataset
import numpy as np
import nltk
from PIL import Image
from mindspore import ops
from mindspore.dataset import transforms

from build_vocab import Vocabulary
from pycocotools.coco import COCO


class CocoDataset:
    """COCO Custom Dataset compatible with torch.utils.data.DataLoader."""

    def __init__(self, root, json, vocab, transform=None):
        """Set the path for images, captions and vocabulary wrapper.

        Args:
            root: image directory.
            json: coco annotation file path.
            vocab: vocabulary wrapper.
            transform: image transformer.
        """
        super(CocoDataset, self).__init__()
        self.root = root
        self.coco = COCO(json)
        self.ids = list(self.coco.anns.keys())
        self.vocab = vocab
        self.transform = transform

    def __getitem__(self, index):
        """Returns one data pair (image and caption)."""
        coco = self.coco
        vocab = self.vocab
        ann_id = self.ids[index]
        caption = coco.anns[ann_id]['caption']
        img_id = coco.anns[ann_id]['image_id']
        path = coco.loadImgs(img_id)[0]['file_name']

        image = Image.open(os.path.join(self.root, path)).convert('RGB')
        if self.transform is not None:
            image = self.transform[0](image)
            image = self.transform[1](image)
            image = self.transform[2](image)
            image = self.transform[3](image)

        # Convert caption (string) to word ids.
        tokens = nltk.tokenize.word_tokenize(str(caption).lower())
        caption = []
        caption.append(vocab('<start>'))
        caption.extend([vocab(token) for token in tokens])
        caption.append(vocab('<end>'))
        target = mindspore.Tensor(caption)
        return image, target

    def __len__(self):
        return len(self.ids)


def collate_fn(images, captions):
    """Creates mini-batch tensors from the list of tuples (image, caption).

    We should build custom collate_fn rather than using default collate_fn,
    because merging caption (including padding) is not supported in default.

    Args:
        data: list of tuple (image, caption).
            - image: torch tensor of shape (3, 256, 256).
            - caption: torch tensor of shape (?); variable length.

    Returns:
        images: torch tensor of shape (batch_size, 3, 256, 256).
        targets: torch tensor of shape (batch_size, padded_length).
        lengths: list; valid length for each padded caption.
    """
    # Sort a data list by caption length (descending order).
    # data.sort(key=lambda x: len(x[1]), reverse=True)

    # images, captions = zip(*data)

    # Merge images (from tuple of 3D tensor to 4D tensor).
    images = ops.stack(images, 0)

    # Merge captions (from tuple of 1D tensor to 2D tensor).
    lengths = [len(cap) for cap in captions]
    targets = ops.zeros(len(captions), max(lengths)).long()
    for i, cap in enumerate(captions):
        end = lengths[i]
        targets[i, :end] = cap[:end]
    return images, targets, lengths


def get_dataset(root, json, vocab, transform, batch_size, shuffle, python_multiprocessing):
    """Returns torch.utils.data.DataLoader for custom coco dataset."""
    # COCO caption dataset
    coco = CocoDataset(root=root,
                       json=json,
                       vocab=vocab,
                       transform=transform)

    # Data loader for COCO dataset
    # This will return (images, captions, lengths) for each iteration.
    # images: a tensor of shape (batch_size, 3, 224, 224).
    # captions: a tensor of shape (batch_size, padded_length).
    # lengths: a list indicating valid length for each caption. length is (batch_size).
    data_loader = mindspore.dataset.GeneratorDataset(source=coco,
                                                     shuffle=shuffle,
                                                     python_multiprocessing=python_multiprocessing,
                                                     column_names=['images', 'captions'])

    data_loader = data_loader.map(operations=transforms.PadEnd(pad_shape=[30]), input_columns=['captions'])
    print("pad complete!")
    data_loader = data_loader.batch(batch_size)
    print("batch complete!")
    # data_loader = data_loader.apply(collate_fn)
    data_loader = data_loader.map(operations=collate_fn, input_columns=['images', 'captions'],
                                  output_columns=['images', 'captions', 'length'])
    print("collate complete!")
    return data_loader
