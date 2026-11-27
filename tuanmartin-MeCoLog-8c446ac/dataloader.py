import numpy as np
from torch.utils.data import Dataset
import math

EMBEDDING_DIM = 768


class DataGenerator(Dataset):
    def __init__(self, x, y, window_size, p=None, max_params=0):
        'Initialization'
        self.x = x
        self.y = y
        self.p = p
        self.window_size = window_size
        self.max_params = max_params
        # self.batch_size = batch_size

    def __len__(self):
        'Denotes the number of batches'
        return math.ceil(len(self.x))

    def __getitem__(self, index):
        'Generate one batch of data'
        # x = self.x[index * self.batch_size:(index + 1) * self.batch_size]
        # y = self.y[index * self.batch_size:(index + 1) * self.batch_size]
        x = self.x[index]
        y = self.y[index]
        if self.p is None:
            p = None
        elif isinstance(self.p, tuple):
            p = (self.p[0][index], self.p[1][index], self.p[2][index], self.p[3][index])
        else:
            p = self.p[index]
        # x = pad_sequences(x, dtype='object', padding='post',
        #                   value=np.zeros(EMBEDDING_DIM)).astype(np.float32)

        # 最大设置为40暂定不需要最大number的
        num_tokens = x.shape[0]
        # print('x.shape[0]:', num_tokens)

        mix_num_boxes = min(int(num_tokens), self.window_size)
        # # mix_boxes_pad = np.zeros((self._max_region_num, 5))
        mix_features_pad = np.zeros((self.window_size, 768))
        mix_features_pad[:mix_num_boxes] = x[:mix_num_boxes]
        x = mix_features_pad

        if p is None:
            return x, y

        p_key, p_type, p_val, p_num = p
        key_pad = np.zeros((self.window_size, self.max_params), dtype=np.int64)
        type_pad = np.zeros((self.window_size, self.max_params), dtype=np.int64)
        num_pad = np.zeros((self.window_size, self.max_params), dtype=np.float32)
        if p_val.ndim == 3:
            max_chars = p_val.shape[-1]
            val_pad = np.zeros((self.window_size, self.max_params, max_chars), dtype=np.int64)
        else:
            val_pad = np.zeros((self.window_size, self.max_params), dtype=np.int64)

        key_pad[:mix_num_boxes] = p_key[:mix_num_boxes]
        type_pad[:mix_num_boxes] = p_type[:mix_num_boxes]
        val_pad[:mix_num_boxes] = p_val[:mix_num_boxes]
        num_pad[:mix_num_boxes] = p_num[:mix_num_boxes]

        return x, y, (key_pad, type_pad, val_pad, num_pad)
