---
slug: e32-activation-patching-order
kind: exercise
title: "Order the activation patching loop"
source: "prep for ARENA 1.2 Intro to Mech Interp"
duration_min: 11
axes: [mechanistic_interpretability]
domain_tags: [activation patching, logit diff, transformerlens, causal intervention]
arena_section: "1.2"
pedagogy: parsons
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Clean prompt: `"When John and Mary went to the shop, John
gave a drink to"` → ` Mary`. Corrupted prompt: the same sentence with
the second `John` swapped to `Mary`. You want to find which
`(layer, position)` in the residual stream carries the information
that makes ` Mary` win.

You are patching **clean → corrupted**: run the corrupted prompt, but
splice one clean activation back in.

Eight blocks, scrambled. One should not be used at all.

```
A  patched_logits = model.run_with_hooks(
       corrupted_tokens,
       fwd_hooks=[(utils.get_act_name("resid_pre", layer), hook_fn)])
B  def metric(logits): return (logits[0, -1, mary] - logits[0, -1, john])
C  results[layer, pos] = ((metric(patched_logits) - corrupted_base)
                          / (clean_base - corrupted_base))
D  clean_logits, clean_cache = model.run_with_cache(clean_tokens)
   clean_base = metric(clean_logits)
E  def hook_fn(activation, hook):
       activation[:, pos, :] = clean_cache[hook.name][:, pos, :]
       return activation
F  for layer in range(model.cfg.n_layers):
       for pos in range(seq_len):
G  corrupted_base = metric(model(corrupted_tokens))
H  corrupted_logits, corrupted_cache = model.run_with_cache(
       corrupted_tokens)
```

**Question.** Give the order, and name the block that must be dropped.
Commit before revealing.

<details>
<summary>reveal</summary>

**Order: B → D → G → F → E → A → C.** Drop **H**.

The constraints that force it:

- **B first.** Everything downstream is measured in this metric's
  units. A patching result is meaningless without a scalar you decided
  on before you started looking.
- **D and G before the loop.** They are the two endpoints of the
  normalization in C. Compute them once; they do not depend on
  `layer` or `pos`.
- **F before E.** `hook_fn` closes over `pos`, so it has to be
  redefined inside the loop body — a hook defined once outside would
  patch whatever `pos` happened to hold last.
- **E before A.** `run_with_hooks` takes the function as an argument;
  it must exist first. Note the hook mutates `activation` and returns
  it — the returned tensor is what continues down the forward pass.
- **C last.** It needs `patched_logits`, which only exists after A.
  Normalizing to `(patched − corrupted) / (clean − corrupted)` puts
  every cell on a 0-to-1 scale: 0 = the patch changed nothing, 1 = the
  patch fully restored clean behavior.

**H is the distractor.** Caching the corrupted run is the instinctive
move, and it is wasted work: in the clean → corrupted direction you
only need the corrupted *metric*, which G already gives you, and the
corrupted activations are produced live by the forward pass in A.
You would need a corrupted cache only if you were patching the other
direction.

</details>

**Key insight.** Activation patching is: fix a metric, measure both
baselines, then run **one** forward pass per patched site with the
clean value spliced in. If a step in your loop does not depend on
`(layer, pos)`, it belongs outside the loop — and if it produces a
cache you never read, it does not belong at all.
