---
slug: e26-backprop-subgoals
kind: exercise
title: "Name the subgoals of a mini-autograd backprop"
source: "prep for ARENA 0.4 Backpropagation"
duration_min: 12
axes: [training_mechanics, debugging]
domain_tags: [autograd, backprop, topological sort, zero_grad]
arena_section: "0.4"
pedagogy: subgoal
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** The centrepiece of ARENA 0.4 — the blank body everyone
stares at.

```python
def backprop(end_node: Tensor, end_grad: Tensor | None = None) -> None:
    """Accumulate the gradient of end_node into the .grad field of every
    leaf tensor it depends on.

    end_node: the node to backpropagate from (usually a scalar loss).
    end_grad: dL/d(end_node); defaults to ones_like(end_node).
    """
    raise NotImplementedError()
```

`Tensor` here has `.array`, `.requires_grad`, `.grad`, and `.recipe` —
where `recipe` records the forward function and the parent tensors, or
is `None` for a leaf.

**Question.** Before writing any code, name the 5 subgoals. Then say
what `.grad` accumulates and why `zero_grad()` has to exist.

Write your list down before opening the reveal.

<details>
<summary>reveal</summary>

1. **Seed the output gradient.**
   `grad_out = np.ones_like(end_node.array) if end_grad is None else end_grad.array`
   The docstring's default *is* subgoal 1 — this is where `loss.backward()`
   with no argument gets its `1.0`.
2. **Open a scratch map from node → gradient-so-far, separate from
   `.grad`.**
   `grads: dict[Tensor, np.ndarray] = {end_node: grad_out}`
   Intermediate nodes need somewhere to hold a partial sum, and it must
   not be `.grad` — `.grad` is for leaves only.
3. **Iterate in reverse topological order.**
   `for node in sorted_graph(end_node):`
   Every consumer of a node must be visited before the node itself, or
   you propagate a partial sum. (This is the trap from
   [e25](/exercise/e25-backward-pass-by-hand): a node used twice isn't
   finished until both consumers have contributed.)
4. **If the node is a leaf that wants gradients, accumulate into
   `.grad`.**
   ```python
   if node.recipe is None and node.requires_grad:
       node.grad = Tensor(grads[node]) if node.grad is None else node.grad + grads[node]
   ```
5. **Otherwise, push each parent's contribution into the map.**
   Look up the registered back-function for `(recipe.func, arg_index)`,
   call it with `(grads[node], node.array, *recipe.args)`, and **add**
   the result into `grads[parent]` — creating the entry if absent.
   `+=`, never `=`, for the same reason as step 4.

**What `.grad` accumulates and why `zero_grad` exists.** Both step 4 and
step 5 add rather than assign, because a tensor feeding `k` consumers
collects `k` gradient terms that must sum. That summation has no natural
end point — `backprop` cannot know whether you're going to call it again
for another loss term, or over another microbatch. So `.grad` is a
running total that the *caller* owns, and `optimizer.zero_grad()` is how
the caller says "this accumulation is finished, start a new one".
Gradient accumulation over microbatches is that same property used
deliberately rather than accidentally.

</details>

**Key insight.** Any ARENA function that walks a graph starts with the
same three subgoals — seed the boundary value, choose a traversal order
that respects dependencies, keep working state out of the fields you're
ultimately writing. `.grad` accumulating instead of assigning is not a
PyTorch quirk; it is the multivariate chain rule with no place to stop.
