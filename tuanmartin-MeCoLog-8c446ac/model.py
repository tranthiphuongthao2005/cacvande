import math

import torch
from torch import nn

TYPE_NUM = 0
TYPE_IP = 1
TYPE_HEX = 2
TYPE_PATH = 3
TYPE_STR = 4


def _rotate_half(x):
    """Split last dim in half and rotate: [-x2, x1] (pairs with RoPE cos/sin layout)."""
    d = x.shape[-1]
    x1 = x[..., : d // 2]
    x2 = x[..., d // 2 :]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(q, k, cos, sin):
    """
    q, k: (batch, n_heads, seq_len, head_dim)
    cos, sin: (1, 1, seq_len, head_dim) broadcastable to q/k
    """
    q_embed = (q * cos) + (_rotate_half(q) * sin)
    k_embed = (k * cos) + (_rotate_half(k) * sin)
    return q_embed, k_embed


class RotaryEmbedding(nn.Module):
    """
    RoPE frequencies for relative positional encoding (Su et al., RoFormer).
    Caches cos/sin up to max_len; call update(seq_len, device, dtype) if longer.
    """

    def __init__(self, head_dim, max_len=512, base=10000.0):
        super().__init__()
        if head_dim % 2 != 0:
            raise ValueError(f"RoPE requires even head_dim, got {head_dim}")
        self.head_dim = head_dim
        self.max_len = max_len
        self.base = base
        inv_freq = 1.0 / (
            base ** (torch.arange(0, head_dim, 2, dtype=torch.float32) / head_dim)
        )
        self.register_buffer("inv_freq", inv_freq, persistent=False)
        self._cache_len = 0
        self._cos_cached = None
        self._sin_cached = None

    def _build_cache(self, seq_len, device, dtype):
        t = torch.arange(seq_len, device=device, dtype=self.inv_freq.dtype)
        freqs = torch.outer(t, self.inv_freq)  # (seq_len, head_dim/2)
        emb = torch.cat((freqs, freqs), dim=-1)  # (seq_len, head_dim)
        cos = emb.cos().to(dtype)
        sin = emb.sin().to(dtype)
        return cos, sin

    def forward(self, seq_len, device, dtype):
        if seq_len > self.max_len:
            raise ValueError(
                f"Sequence length {seq_len} exceeds RoPE max_len={self.max_len}. "
                "Increase max_len in Model / ParamAwareEncoderLayer."
            )
        stale = (
            self._cos_cached is None
            or self._cache_len < seq_len
            or self._cos_cached.device != device
            or self._cos_cached.dtype != dtype
        )
        if stale:
            cos, sin = self._build_cache(seq_len, device, dtype)
            self._cos_cached = cos
            self._sin_cached = sin
            self._cache_len = seq_len
        else:
            cos = self._cos_cached[:seq_len]
            sin = self._sin_cached[:seq_len]
        # (1, 1, seq_len, head_dim) for broadcasting over batch and heads
        return cos.unsqueeze(0).unsqueeze(0), sin.unsqueeze(0).unsqueeze(0)


class ParamEncoder(nn.Module):
    def __init__(self, dim, key_vocab_size, char_vocab_size, max_chars,
                 type_vocab_size=5, char_emb_dim=32, char_conv_channels=64, char_kernel_size=3):
        super().__init__()
        self.key_emb = nn.Embedding(key_vocab_size, dim)
        self.type_emb = nn.Embedding(type_vocab_size, dim)
        self.num_linear = nn.Linear(1, dim)
        self.char_emb = nn.Embedding(char_vocab_size, char_emb_dim)
        self.char_conv = nn.Conv1d(
            char_emb_dim, char_conv_channels, kernel_size=char_kernel_size, padding=char_kernel_size // 2
        )
        self.char_proj = nn.Linear(char_conv_channels, dim)
        self.max_chars = max_chars

    def forward(self, key_idx, type_idx, val_chars, num_val):
        key_e = self.key_emb(key_idx)
        type_e = self.type_emb(type_idx)
        num_e = self.num_linear(num_val.unsqueeze(-1))

        num_mask = (type_idx == TYPE_NUM).unsqueeze(-1)
        str_or_path_mask = ((type_idx == TYPE_STR) | (type_idx == TYPE_PATH)).unsqueeze(-1)

        bsz, seq_len, n_params, _ = val_chars.size()
        flat_chars = val_chars.view(bsz * seq_len * n_params, self.max_chars)
        char_e = self.char_emb(flat_chars)
        char_e = char_e.transpose(1, 2)
        char_h = torch.relu(self.char_conv(char_e))
        char_pooled = torch.amax(char_h, dim=-1)
        val_e = self.char_proj(char_pooled).view(bsz, seq_len, n_params, -1)
        val_e = val_e * str_or_path_mask
        num_e = num_e * num_mask

        param_e = key_e + type_e + val_e + num_e
        return param_e.sum(dim=2)


class ParamAwareEncoderLayer(nn.Module):
    __constants__ = ['batch_first']

    def __init__(self, d_model, nhead, param_dim=8, dim_feedforward=3072, dropout=0.1,
                 layer_norm_eps=1e-5, batch_first=False, max_seq_len=2048, rope_base=10000.0,
                 device=None, dtype=None) -> None:
        super().__init__()

        factory_kwargs = {'device': device, 'dtype': dtype}
        self.d_model = d_model
        self.nhead = nhead
        self.head_dim = d_model // nhead
        if self.head_dim * nhead != d_model:
            raise ValueError("d_model must be divisible by nhead")

        self.q_proj = nn.Linear(d_model, d_model, **factory_kwargs)
        self.k_proj = nn.Linear(d_model, d_model, **factory_kwargs)
        self.v_proj = nn.Linear(d_model, d_model, **factory_kwargs)
        self.out_proj = nn.Linear(d_model, d_model, **factory_kwargs)

        self.p_proj = nn.Linear(param_dim, d_model, **factory_kwargs)
        self.gate_proj = nn.Linear(param_dim, d_model, **factory_kwargs)
        self.p_norm = nn.LayerNorm(d_model, eps=layer_norm_eps)

        # RoPE after GKI: relative position in Q/K attention (per-head dim must be even)
        self.rope = RotaryEmbedding(self.head_dim, max_len=max_seq_len, base=rope_base)
        self.use_rope = True

        self.dropout = nn.Dropout(dropout)
        self.dropout1 = nn.Dropout(dropout)
        self.norm1 = nn.LayerNorm(d_model, eps=layer_norm_eps)

        self.linear1 = nn.Linear(d_model, dim_feedforward, **factory_kwargs)
        self.activation = nn.GELU()
        self.linear2 = nn.Linear(dim_feedforward, d_model, **factory_kwargs)
        self.dropout2 = nn.Dropout(dropout)
        self.norm2 = nn.LayerNorm(d_model, eps=layer_norm_eps)

    def forward(self, src, params, src_mask=None, src_key_padding_mask=None):
        # src: (B, L, d_model), params: (B, L, param_dim)
        bsz, seq_len, _ = src.size()

        q = self.q_proj(src)
        k_base = self.k_proj(src)
        v = self.v_proj(src)

        p_proj = self.p_norm(self.p_proj(params))
        gate = torch.sigmoid(self.gate_proj(params))
        # GKI: content-augmented keys, then RoPE encodes relative order on Q and K
        k = k_base + gate * p_proj

        q = q.view(bsz, seq_len, self.nhead, self.head_dim).transpose(1, 2)
        k = k.view(bsz, seq_len, self.nhead, self.head_dim).transpose(1, 2)
        v = v.view(bsz, seq_len, self.nhead, self.head_dim).transpose(1, 2)

        if self.use_rope:
            cos, sin = self.rope(seq_len, q.device, q.dtype)
            q, k = apply_rotary_pos_emb(q, k, cos, sin)

        attn_weights = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)

        if src_mask is not None:
            if src_mask.dim() == 2:
                attn_weights = attn_weights + src_mask.unsqueeze(0).unsqueeze(0)
            elif src_mask.dim() == 3:
                attn_weights = attn_weights + src_mask.unsqueeze(1)

        if src_key_padding_mask is not None:
            attn_weights = attn_weights.masked_fill(
                src_key_padding_mask.unsqueeze(1).unsqueeze(2), float('-inf'))

        attn_probs = torch.softmax(attn_weights, dim=-1)
        attn_probs = self.dropout(attn_probs)

        attn_out = torch.matmul(attn_probs, v)
        attn_out = attn_out.transpose(1, 2).contiguous().view(bsz, seq_len, self.d_model)
        attn_out = self.out_proj(attn_out)
        attn_out = self.dropout1(attn_out)
        src = self.norm1(src + attn_out)

        src2 = self.linear2(self.dropout(self.activation(self.linear1(src))))
        src2 = self.dropout2(src2)
        src = self.norm2(src + src2)

        return src


class Model(nn.Module):
    def __init__(self, num_layers=4, max_params=8, key_vocab_size=2, char_vocab_size=129,
                 max_chars=16, dim=768, window_size=100, nhead=8, dim_feedforward=3072, dropout=0.1,
                 use_rope=True):
        super(Model, self).__init__()
        self.param_encoder = ParamEncoder(dim, key_vocab_size, char_vocab_size, max_chars)
        # +2: [CLS] + log events (window_size positions) with small margin
        rope_max = max(window_size + 2, 32)
        self.layers = nn.ModuleList([
            ParamAwareEncoderLayer(
                dim, nhead, param_dim=dim, dim_feedforward=dim_feedforward, dropout=dropout,
                batch_first=True, max_seq_len=rope_max,
            )
            for _ in range(num_layers)
        ])
        self.cls_token = nn.Parameter(torch.zeros(1, 1, dim))
        self.max_params = max_params
        self.max_chars = max_chars
        self.use_rope = use_rope
        for layer in self.layers:
            layer.use_rope = use_rope

    def encode(self, x, params=None):
        bsz, seq_len, _ = x.size()
        if params is None:
            key_idx = torch.zeros((bsz, seq_len, self.max_params), device=x.device, dtype=torch.long)
            type_idx = torch.zeros((bsz, seq_len, self.max_params), device=x.device, dtype=torch.long)
            val_idx = torch.zeros(
                (bsz, seq_len, self.max_params, self.max_chars), device=x.device, dtype=torch.long
            )
            num_val = torch.zeros((bsz, seq_len, self.max_params), device=x.device, dtype=x.dtype)
        else:
            key_idx, type_idx, val_idx, num_val = params
        param_vec = self.param_encoder(key_idx, type_idx, val_idx, num_val)

        cls_token = self.cls_token.expand(bsz, -1, -1)
        x = torch.cat([cls_token, x], dim=1)
        cls_params = torch.zeros((bsz, 1, param_vec.size(-1)), device=x.device, dtype=x.dtype)
        param_vec = torch.cat([cls_params, param_vec], dim=1)

        for layer in self.layers:
            x = layer(x, param_vec)
        return x[:, 0, :]

    def forward(self, x, params=None):
        return self.encode(x, params)


if __name__ == '__main__':
    model = Model()
    pass
