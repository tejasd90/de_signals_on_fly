"""Weekly block bootstrap that does not take three hours.

The slow version, which burned 3h+ on 2026-09-29 before being killed:

    for _ in range(2000):
        pick = rng.choice(unique_weeks, len(unique_weeks), replace=True)
        vals = np.concatenate([e[w == u] for u in pick])   # O(N) per week!
        boot.append(vals.mean())

With N=10.3M rows and 140 weeks that is 140*2000 full scans of a 10.3M array --
roughly 3e12 element comparisons. It is not the data volume that was wrong, it is
this line.

A week's contribution to a mean is fully described by its SUM and its COUNT, so
sum and count each week ONCE, then resample those 140 pairs. Identical answer,
O(weeks) per iteration instead of O(rows), and fully vectorised over iterations.
"""
import numpy as np

def week_codes(weeks):
    """string week labels -> integer codes, plus the number of distinct weeks."""
    uniq, code = np.unique(np.asarray(weeks), return_inverse=True)
    return code.astype(np.int32), len(uniq)

def boot_mean(vals, code, nw, n=2000, seed=0):
    """Distribution of the block-bootstrapped mean of `vals`."""
    vals = np.asarray(vals, float)
    s = np.bincount(code, weights=vals, minlength=nw)
    c = np.bincount(code, minlength=nw).astype(float)
    pick = np.random.default_rng(seed).integers(0, nw, size=(n, nw))
    S, C = s[pick].sum(1), c[pick].sum(1)
    return np.divide(S, C, out=np.zeros_like(S), where=C > 0)

def boot_diff(vals, code, nw, sel, n=2000, seed=0):
    """Distribution of mean(vals[sel]) - mean(vals[~sel]) under the same week draw.

    Both groups are resampled with the SAME week picks, which is the point: weeks
    are the unit of independence, so a week must enter or leave the comparison
    whole rather than being split between the two arms.
    """
    vals = np.asarray(vals, float); sel = np.asarray(sel, bool)
    sa = np.bincount(code[sel],  weights=vals[sel],  minlength=nw)
    ca = np.bincount(code[sel],  minlength=nw).astype(float)
    sb = np.bincount(code[~sel], weights=vals[~sel], minlength=nw)
    cb = np.bincount(code[~sel], minlength=nw).astype(float)
    pick = np.random.default_rng(seed).integers(0, nw, size=(n, nw))
    A = np.divide(sa[pick].sum(1), np.maximum(ca[pick].sum(1), 1e-9))
    B = np.divide(sb[pick].sum(1), np.maximum(cb[pick].sum(1), 1e-9))
    ok = (ca[pick].sum(1) > 0) & (cb[pick].sum(1) > 0)
    return (A - B)[ok]
