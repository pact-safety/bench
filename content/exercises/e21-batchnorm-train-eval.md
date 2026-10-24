---
slug: e21-batchnorm-train-eval
kind: exercise
title: "Spot the BatchNorm mode bug in an eval loop"
source: "prep for ARENA 0.2 CNNs & ResNets"
duration_min: 10
axes: [training_mechanics, debugging]
domain_tags: [batchnorm, eval mode, running stats, resnet]
arena_section: "0.2"
pedagogy: debug
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup — the symptom first.** You are finetuning a ResNet. Training
accuracy climbs to 96%. Validation accuracy is stuck around 60% and
*jitters by several points between runs on the identical val set*. Then
you serve the model on single images and the predictions disagree with
what the val loop reported for those same images.

```python
def evaluate(model, val_loader) -> float:
    correct = 0
    with t.inference_mode():
        for imgs, labels in val_loader:
            preds = model(imgs).argmax(dim=-1)
            correct += (preds == labels).sum().item()
    return correct / len(val_loader.dataset)

for epoch in range(n_epochs):
    for imgs, labels in train_loader:
        ...                       # forward, backward, step
    print(evaluate(model, val_loader))
```

**Question.** Name the bug, the minimum fix, and what the *jitter*
specifically told you.

<details>
<summary>reveal</summary>

**Bug.** `model.eval()` is never called. `t.inference_mode()` turns off
autograd — it does **not** change module mode. BatchNorm is still in
training mode during evaluation.

**What that changes.** A `BatchNorm2d` in train mode normalises each
channel using the mean and variance *of the batch in front of it*, and
also writes those statistics into `running_mean` / `running_var` with
`momentum=0.1`. In eval mode it uses the stored running stats and
updates nothing.

So two things break at once:

1. **Predictions become batch-dependent.** An image's logits now depend
   on which other images landed in its batch. Shuffle the val loader
   and the accuracy moves — that is your jitter, and it is the tell
   that the forward pass is reading something other than the weights.
2. **The running stats get polluted by validation data**, drifting on
   every eval pass. The stats you eventually deploy with are not the
   ones training produced, which is why single-image serving disagrees.

**Minimum fix.**

```python
def evaluate(model, val_loader) -> float:
    model.eval()                              # <-- the fix
    correct = 0
    with t.inference_mode():
        ...
    model.train()                             # <-- restore, or the next
    return correct / len(val_loader.dataset)  #     epoch trains in eval mode
```

Dropout has the same train/eval split, so the fix covers it too.

</details>

**Key insight.** `inference_mode` / `no_grad` and `model.eval()` control
orthogonal things — gradient recording versus module behaviour — and
BatchNorm and Dropout only listen to the second. Any output that changes
when you reshuffle the *evaluation* set is a train-mode normalisation
layer until proven otherwise.
