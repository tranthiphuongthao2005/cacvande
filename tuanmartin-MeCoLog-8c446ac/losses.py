import torch
import warnings


def prototypical_contrastive_loss(
    z_support,
    y_support,
    z_query,
    y_query,
    temperature=0.2,
    warn_on_degenerate=True,
):
    """
    Symmetric two-prototype contrastive loss (no asymmetric margin).
    """
    device = z_query.device
    z_support = torch.nn.functional.normalize(z_support, dim=1)
    z_query = torch.nn.functional.normalize(z_query, dim=1)
    y_support = y_support.view(-1)
    y_query = y_query.view(-1)

    support_norm_mask = (y_support == 0)
    support_anom_mask = (y_support == 1)
    if support_norm_mask.sum() == 0 or support_anom_mask.sum() == 0 or z_query.size(0) == 0:
        if warn_on_degenerate:
            warnings.warn(
                "Proto loss received a degenerate episode (missing support class or empty query); "
                "returning zero loss. Check episode sampler / label distribution.",
                RuntimeWarning,
                stacklevel=2,
            )
        return torch.tensor(0.0, device=device, requires_grad=True)

    mu_norm = z_support[support_norm_mask].mean(dim=0, keepdim=True)
    mu_anom = z_support[support_anom_mask].mean(dim=0, keepdim=True)
    mu_norm = torch.nn.functional.normalize(mu_norm, dim=1)
    mu_anom = torch.nn.functional.normalize(mu_anom, dim=1)

    sim_norm = torch.matmul(z_query, mu_norm.t()).squeeze(1)
    sim_anom = torch.matmul(z_query, mu_anom.t()).squeeze(1)
    logits = torch.stack([sim_norm, sim_anom], dim=1) / temperature
    loss = torch.nn.functional.cross_entropy(logits, y_query.long())
    return loss


def supervised_contrastive_loss(
    z_support,
    y_support,
    z_query,
    y_query,
    temperature=0.2,
    warn_on_degenerate=True,
):
    """
    Episodic supervised contrastive loss over support+query embeddings.
    """
    device = z_query.device
    z = torch.cat([z_support, z_query], dim=0)
    y = torch.cat([y_support.view(-1), y_query.view(-1)], dim=0).long()
    z = torch.nn.functional.normalize(z, dim=1)

    if z.size(0) < 2:
        if warn_on_degenerate:
            warnings.warn("SupCon received too few embeddings; returning zero loss.", RuntimeWarning, stacklevel=2)
        return torch.tensor(0.0, device=device, requires_grad=True)

    sim = torch.matmul(z, z.t()) / temperature
    mask_self = torch.eye(z.size(0), device=device, dtype=torch.bool)
    sim = sim.masked_fill(mask_self, float("-inf"))
    pos_mask = y.unsqueeze(0).eq(y.unsqueeze(1)) & (~mask_self)
    valid = pos_mask.any(dim=1)
    if not valid.any():
        if warn_on_degenerate:
            warnings.warn("SupCon episode has no positive pairs; returning zero loss.", RuntimeWarning, stacklevel=2)
        return torch.tensor(0.0, device=device, requires_grad=True)

    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    mean_log_prob_pos = (log_prob * pos_mask).sum(dim=1) / pos_mask.sum(dim=1).clamp_min(1)
    loss = -mean_log_prob_pos[valid].mean()
    return loss


def asymmetric_prototype_contrastive_loss(
    z_support,
    y_support,
    z_query,
    y_query,
    temperature=0.2,
    margin_scale=1.0,
    margin_mode="adaptive",
    fixed_margin=0.0,
    warn_on_degenerate=True,
):
    """
    Asymmetric Prototype Contrastive Loss (APCL), episodic form.

    Labels: 0 = normal, 1 = anomaly

    Episodic prototypes from support:
        mu_norm = mean(z_support[y_support==0])
        mu_anom = mean(z_support[y_support==1])

    Unified query loss:
        delta(z_q, y_q) = 1[y_q==1] * ReLU(z_q . mu_norm)
        L_q = -log(
            exp(z_q . mu_{y_q} / tau) /
            (
                exp((z_q . mu_norm + delta) / tau) +
                exp(z_q . mu_anom / tau)
            )
        )
    """
    device = z_query.device
    z_support = torch.nn.functional.normalize(z_support, dim=1)
    z_query = torch.nn.functional.normalize(z_query, dim=1)
    y_support = y_support.view(-1)
    y_query = y_query.view(-1)

    support_norm_mask = (y_support == 0)
    support_anom_mask = (y_support == 1)
    if support_norm_mask.sum() == 0 or support_anom_mask.sum() == 0 or z_query.size(0) == 0:
        if warn_on_degenerate:
            warnings.warn(
                "APCL received a degenerate episode (missing support class or empty query); "
                "returning zero loss. Check episode sampler / label distribution.",
                RuntimeWarning,
                stacklevel=2,
            )
        return torch.tensor(0.0, device=device, requires_grad=True)

    mu_norm = z_support[support_norm_mask].mean(dim=0, keepdim=True)
    mu_anom = z_support[support_anom_mask].mean(dim=0, keepdim=True)
    mu_norm = torch.nn.functional.normalize(mu_norm, dim=1)
    mu_anom = torch.nn.functional.normalize(mu_anom, dim=1)

    sim_norm = torch.matmul(z_query, mu_norm.t()).squeeze(1)  # z_q . mu_norm
    sim_anom = torch.matmul(z_query, mu_anom.t()).squeeze(1)  # z_q . mu_anom

    anom_query = (y_query == 1).to(sim_norm.dtype)
    if margin_mode == "adaptive":
        # delta(z_q, y_q) = lambda * 1[y_q==anom] * ReLU(z_q . mu_norm)
        delta = margin_scale * anom_query * torch.relu(sim_norm)
    elif margin_mode == "fixed":
        delta = fixed_margin * anom_query
    else:
        raise ValueError(f"Unsupported APCL margin_mode: {margin_mode}")

    logit_norm = (sim_norm + delta) / temperature
    logit_anom = sim_anom / temperature
    denom_log = torch.logsumexp(torch.stack([logit_norm, logit_anom], dim=1), dim=1)

    target_sim = torch.where(y_query == 0, sim_norm, sim_anom)
    target_logit = target_sim / temperature
    loss = -(target_logit - denom_log).mean()
    return loss


# Backward-compatible alias with explicit APCL name.
apcl_loss = asymmetric_prototype_contrastive_loss
