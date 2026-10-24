---
slug: ml4good-prework-fall-2026
title: "ML4Good Technical Prework (Fall 2026)"
description: "Technical preparation for ML4Good Hong Kong 2026: PyTorch, tensor manipulation, and the shared AI safety readings and videos. Work in Colab and at the original sources; demonstrate each checkpoint before marking it complete."
source_url: "https://docs.google.com/document/d/1hwZ7FPMxE2qQEDtXYZ-IGsnKNFKzrVW7/edit#heading=h.1muxhwej888n"
chapters:
  - title: "Technical prework"
    sections:
      - title: "PyTorch and gradient descent in Colab"
        url: "https://colab.research.google.com/github/EffiSciencesResearch/ML4G-2.0/blob/master/workshops/pytorch_tuto/pytorch_tuto.ipynb"
        kind: external_exercise
        duration_min: 60
        domain_tags: [python, pytorch, colab, gradient descent]
        axes: [training_mechanics]
        depends_on: []
        checkpoint: "Run the introductory notebook, explain how a gradient changes a parameter, and demonstrate one update while predicting its direction."
        check_questions:
          - "For one scalar parameter and a loss, how would the sign of the gradient determine the direction of a gradient-descent update?"
          - "In a small notebook example, how would you inspect the parameter and gradient before and after one update to check your prediction?"
          - "What changes if the learning rate is much larger, and why does one update not by itself establish that training has converged?"
        notes: "Start with the track orientation and shared reading. Before this notebook, use targeted mathematics or Python refreshers if needed. Then work in Colab, consult the linked examples when useful, and demonstrate an update yourself."
        resources:
          - title: "PyTorch examples reference linked by the guide"
            url: "https://colab.research.google.com/corgiredirector?site=https%3A%2F%2Fpytorch.org%2Ftutorials%2Fbeginner%2Fpytorch_with_examples.html"
            kind: reading
      - title: "PyTorch Basics 0–3: workflow, tensors, data, transforms"
        url: "https://docs.pytorch.org/tutorials/beginner/basics/quickstart_tutorial.html"
        kind: external_reading
        duration_min: 90
        domain_tags: [pytorch, tensors, datasets, dataloaders, transforms]
        axes: [training_mechanics, data_pipeline]
        depends_on: [0]
        checkpoint: "Trace a batch from a Dataset through a DataLoader and transform; inspect its shape and explain each object's role without memorizing syntax."
        check_questions:
          - "How do a Dataset, a DataLoader, and a transform contribute to a batch in the PyTorch tutorial?"
          - "For one batch of images and labels, what does each tensor axis represent, and how would changing batch size affect the shapes?"
          - "What simple inspection would reveal that a transform produced the wrong dtype, range, or shape before the batch reaches a model?"
      - title: "PyTorch Basics 4–7: models, gradients, optimization, saving"
        url: "https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial.html"
        kind: external_reading
        duration_min: 90
        domain_tags: [pytorch, neural networks, autograd, optimizers, checkpoints]
        axes: [training_mechanics]
        depends_on: [1]
        checkpoint: "Explain the forward pass, loss, backward pass, gradient reset, and optimizer step; show how to save and reload model parameters."
        check_questions:
          - "How do the forward pass, loss, backward pass, gradient reset, and optimizer step fit together in a PyTorch training iteration?"
          - "What would happen to parameter gradients over repeated backward passes without a reset, and how could you check that behavior?"
          - "How would you save and reload model parameters and check that the restored model reproduces a prediction under the same evaluation conditions?"
      - title: "Why einops: readable tensor operations"
        url: "https://www.kolaayonrinde.com/blog/2024/01/08/einops.html"
        kind: external_reading
        duration_min: 30
        domain_tags: [einops, tensors, tensor manipulation]
        axes: [transformer_internals]
        depends_on: [1]
        checkpoint: "Explain the axis names and output shape in one einops pattern, and describe why that notation can make a tensor operation easier to check."
        check_questions:
          - "Choose an einops pattern from the reading: what does every named axis mean, and what output shape do you predict?"
          - "How does that named-axis expression make an intended tensor transformation easier to inspect than an equivalent reshape or transpose?"
          - "What dimension relationship must hold for your chosen pattern, and what small input would test whether you have the axis order right?"
      - title: "Practice manipulating high-dimensional tensors"
        url: "https://colab.research.google.com/github/EffiSciencesResearch/ML4G-2.0/blob/master/workshops/tensors/tensors_normal.ipynb"
        kind: external_exercise
        duration_min: 90
        domain_tags: [tensors, tensor manipulation, einops, einsum]
        axes: [transformer_internals]
        depends_on: [3]
        checkpoint: "Demonstrate representative tensor manipulations from the notebook, predicting and checking output shapes and axis meanings; completing every exercise is not required."
        check_questions:
          - "For a representative tensor rearrangement from the notebook, what are the input and output axis meanings and shapes?"
          - "For a reduction or contraction, which axes are retained and which are combined or removed, and how can you check a small case by hand?"
          - "How would you detect an axis-order error even when the resulting tensor has the expected shape?"
        notes: "Build familiarity with high-dimensional tensors rather than trying to clear every exercise. The documentation and video below are reference help, not extra completion requirements."
        resources:
          - title: "einops documentation"
            url: "https://einops.rocks/"
            kind: reading
          - title: "einsum video explainer"
            url: "https://www.youtube.com/watch?v=IvgV6QcsC64"
            kind: video
  - title: "Shared preparation for all participants"
    sections:
      - title: "AI Safety Atlas 1: Capabilities"
        url: "https://ai-safety-atlas.com/chapters/v1/capabilities/introduction/"
        kind: external_reading
        duration_min: 105
        domain_tags: [ai safety, capabilities]
        axes: [ai_safety_fundamentals]
        depends_on: []
        checkpoint: "Use your notes to explain a capability trend and its limits, and bring one question from the chapter for discussion."
        check_questions:
          - "Choose a capability example from the Atlas chapter: what evidence supports the claim, and what does that evidence leave unestablished?"
          - "How do compute, data, and algorithmic improvements enter the chapter's discussion of scaling, and what assumption limits a forecast based on that trend?"
          - "How do two possible AI development or takeoff scenarios differ, and what observation would make you revise your view of their plausibility?"
          - "Which unresolved question about capabilities would you bring to the chapter discussion, and which passage prompted it?"
      - title: "AI Safety Atlas 2: Risks"
        url: "https://ai-safety-atlas.com/chapters/v1/risks/introduction/"
        kind: external_reading
        duration_min: 105
        domain_tags: [ai safety, risks]
        axes: [ai_safety_fundamentals]
        depends_on: []
        checkpoint: "Describe a risk pathway in your own words, identify an assumption it depends on, and record one discussion question."
        check_questions:
          - "How do misuse, misalignment, and systemic risk differ as explanations of AI harm, and where might those categories overlap?"
          - "Choose one risk pathway from the chapter: what causal steps connect the system's capabilities to the harm, and which assumption is most uncertain?"
          - "How could deployment incentives or interactions between organizations amplify that risk, and what evidence would weaken your account?"
          - "Which unresolved question about that risk pathway would you bring to the chapter discussion?"
      - title: "AI Safety Atlas 3: Strategies"
        url: "https://ai-safety-atlas.com/chapters/v1/strategies/introduction/"
        kind: external_reading
        duration_min: 105
        domain_tags: [ai safety, safety strategies]
        axes: [ai_safety_fundamentals, ai_governance_strategy]
        depends_on: []
        checkpoint: "Explain how one safety strategy addresses a risk, name a limitation, and record one question to discuss."
        check_questions:
          - "Choose a strategy from the chapter: which risk pathway does it address, and through what mechanism would it reduce that risk?"
          - "Under what conditions could that strategy fail or leave an important part of the risk unaddressed?"
          - "Which other strategy could complement it, and why would their combination provide more protection than either alone?"
          - "Which assumption about your chosen strategy would you most want to discuss or investigate further?"
      - title: "AI Safety Atlas 4: Governance"
        url: "https://ai-safety-atlas.com/chapters/v1/governance/introduction/"
        kind: external_reading
        duration_min: 105
        domain_tags: [ai safety, governance]
        axes: [ai_governance_strategy]
        depends_on: []
        checkpoint: "Explain a governance intervention and its intended effect, name an implementation challenge, and record one discussion question."
        check_questions:
          - "Choose a governance intervention from the chapter: which actor could implement it, and how is it intended to reduce frontier AI risk?"
          - "What incentives, monitoring needs, or enforcement difficulties could limit that intervention in practice?"
          - "How could a technical safety measure complement the intervention, and what problem would remain even if that measure worked?"
          - "Which tradeoff or uncertainty about this governance approach would you bring to the chapter discussion?"
      - title: "Camp philosophy: Half-assing it with everything you've got"
        url: "https://mindingourway.com/half-assing-it-with-everything-youve-got/"
        kind: external_reading
        duration_min: 20
        domain_tags: [learning, prioritization]
        axes: []
        depends_on: []
        checkpoint: "Apply the essay's approach to one concrete learning task: state what a useful imperfect attempt would accomplish and what you would prioritize."
        check_questions:
          - "What distinction does the essay draw between caring about an outcome and demanding a perfect performance?"
          - "For one concrete learning task, what would a useful imperfect attempt look like, and what would make it useful?"
          - "How would you decide where to spend more effort and where to stop, using the essay's argument rather than perfection as the criterion?"
      - title: "ML4G transversal video playlist"
        url: "https://youtube.com/playlist?list=PLvc9BiqIzdAuAxVDdfsHiZ50jlvloXxvh"
        kind: external_video
        duration_min: 180
        domain_tags: [ai safety, background knowledge]
        axes: [ai_safety_fundamentals]
        depends_on: []
        checkpoint: "Review the playlist topics, explain the material you were least familiar with, and record questions about any remaining gaps."
        check_questions:
          - "Choose a video covering something unfamiliar: what is its central claim or concept, and how would you explain it with a concrete example?"
          - "Which assumption, limitation, or point of uncertainty in that video matters for understanding the claim?"
          - "Which remaining topic in the playlist is least familiar to you, and what question will guide your next viewing?"
  - title: "Mathematics refreshers — choose what you need"
    sections:
      - title: "Linear algebra foundations"
        url: "https://www.youtube.com/watch?v=kYB8IZa5AuE"
        kind: external_video
        duration_min: 120
        domain_tags: [linear algebra, matrix multiplication, bases]
        axes: [algorithmic]
        depends_on: []
        optional: true
        notes: "The guide calls these capabilities essential: linear transformations; matrix multiplication; rank, trace, determinant, and transpose; bases and basis transformations. Use the resources selectively to fill gaps. The two talks and series are alternative explanations, not a requirement to watch every resource."
        checkpoint: "Apply a small matrix to a vector, explain multiplication as composition, identify rank/trace/determinant/transpose, and describe what changes when you express the vector in another basis."
        check_questions:
          - "For a small matrix and vector of your choice, how does matrix-vector multiplication represent a linear transformation, and what changes when two transformations are composed?"
          - "Using a small matrix, how would you compute and interpret its rank and transpose, and its trace and determinant when those are defined?"
          - "How can the coordinates of a vector change under a change of basis while the represented vector stays the same?"
        resources:
          - title: "Linear transformations"
            url: "https://www.youtube.com/watch?v=kYB8IZa5AuE"
            kind: video
          - title: "Matrix multiplication"
            url: "http://mlwiki.org/index.php/Matrix-Matrix_Multiplication"
            kind: reading
          - title: "Linear Algebra Talk 1 of 2"
            url: "https://www.youtube.com/watch?v=GkPhwnvRe-8"
            kind: video
          - title: "Linear Algebra Talk 2 of 2"
            url: "https://www.youtube.com/watch?v=0EB23unfLSU"
            kind: video
          - title: "Essence of Linear Algebra series"
            url: "https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab"
            kind: video
      - title: "Linear algebra extensions: eigenvectors, SVD, and matrix types"
        url: "https://www.lesswrong.com/posts/iupCxk3ddiJBAJkts/six-and-a-half-intuitions-for-svd"
        kind: external_reading
        duration_min: 90
        domain_tags: [linear algebra, eigenvectors, singular value decomposition]
        axes: [algorithmic]
        depends_on: []
        optional: true
        notes: "Helpful extensions, not required to follow the camp: singular value decomposition; eigenvalues and eigenvectors; and the significance of symmetric, orthogonal, identity, and rotation matrices. The general linear-algebra series in the foundations section can also support these topics."
        checkpoint: "For the extension you chose, give a small example: interpret an eigenvector, explain an SVD factorization, or demonstrate the behavior of a named matrix type."
        check_questions:
          - "Choose one extension to study: eigenvectors, singular value decomposition, or a special matrix type. What does that concept mean in a small concrete example?"
          - "What property or relationship would you calculate to check that your example really has the claimed structure?"
          - "How does your chosen extension connect to linear transformations, and where could it help you understand a machine-learning computation?"
        resources:
          - title: "Six and a half intuitions for SVD"
            url: "https://www.lesswrong.com/posts/iupCxk3ddiJBAJkts/six-and-a-half-intuitions-for-svd"
            kind: reading
          - title: "Essence of Linear Algebra series"
            url: "https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab"
            kind: video
      - title: "Probability and statistics foundations"
        url: "https://jonathan-hui.medium.com/probability-in-machine-learning-deep-learning-a2acdd793f18"
        kind: external_reading
        duration_min: 60
        domain_tags: [probability, statistics, expectation, standard deviation]
        axes: [eval_design]
        depends_on: []
        optional: true
        notes: "Essential capabilities in the guide: probability rules, expected value, and standard deviation. Independence and the normal distribution are helpful extensions. Choose the explanations you need rather than treating all three articles as required reading."
        checkpoint: "Use a small distribution to compute a probability, expected value, and standard deviation, explaining what each means. If you studied an extension, explain independence or the role of a normal distribution."
        check_questions:
          - "For a small discrete distribution of your choice, how would you check the probability rules and calculate expected value and standard deviation?"
          - "What do expected value and standard deviation tell you about that distribution, and what do they leave out?"
          - "If you study the helpful extension on independence or the normal distribution, what does its central assumption mean and when might it fail? If not, which foundation needs more practice?"
        resources:
          - title: "Probability in Machine Learning and Deep Learning"
            url: "https://jonathan-hui.medium.com/probability-in-machine-learning-deep-learning-a2acdd793f18"
            kind: reading
          - title: "Normal Distributions in Machine Learning"
            url: "https://jonathan-hui.medium.com/normal-distributions-in-machine-learning-c8a21c8ba8c9"
            kind: reading
          - title: "Expected Value, Variance and Standard Deviation"
            url: "https://medium.com/jun94-devpblog/prob-stats-3-expected-value-variance-and-standard-deviation-bce9303d8da8"
            kind: reading
      - title: "Calculus foundations and useful extensions"
        url: "https://www.3blue1brown.com/topics/calculus"
        kind: external_video
        duration_min: 60
        domain_tags: [calculus, differentiation, gradients]
        axes: [training_mechanics]
        depends_on: []
        optional: true
        notes: "Differentiation and partial differentiation are essential capabilities in the guide. Basics of vector calculus, including the chain rule and Taylor series, are helpful extensions. Select relevant parts of the series to address your own gaps."
        checkpoint: "Differentiate a simple function and compute a partial derivative while stating what is held fixed. For an extension you studied, demonstrate a chain-rule step or a local Taylor approximation."
        check_questions:
          - "For a simple function of one variable, how would you find its derivative and explain what that derivative means locally?"
          - "For a function of two variables, how would you compute a partial derivative, and what must be held fixed?"
          - "How would a small finite change help you check a derivative prediction, and why might the prediction become less accurate for a larger change?"
        resources:
          - title: "3Blue1Brown calculus series"
            url: "https://www.3blue1brown.com/topics/calculus"
            kind: video
  - title: "Python refreshers — choose what you need"
    sections:
      - title: "Python basics: expressions, control flow, and data structures"
        url: "https://docs.python.org/3/tutorial/introduction.html"
        kind: external_reading
        duration_min: 90
        domain_tags: [python, control flow, data structures]
        axes: [software_engineering]
        depends_on: []
        optional: true
        notes: "The guide recommends these three tutorial chapters when Python needs a refresh: chapter 3, an informal introduction; chapter 4, control flow; and chapter 5, data structures. Work the examples you cannot yet explain or adapt."
        checkpoint: "Write a small function using a branch, a loop, and a suitable list or dictionary; explain its output and check an empty-input case."
        check_questions:
          - "How would you write a small Python function that uses a branch and a loop to transform a list or dictionary?"
          - "For your example, how do the data structure and iteration choices affect what values are read or changed?"
          - "What should your function do with an empty input, and which small examples would check its ordinary and boundary behavior?"
        resources:
          - title: "3. An Informal Introduction to Python"
            url: "https://docs.python.org/3/tutorial/introduction.html"
            kind: reading
          - title: "4. More Control Flow Tools"
            url: "https://docs.python.org/3/tutorial/controlflow.html"
            kind: reading
          - title: "5. Data Structures"
            url: "https://docs.python.org/3/tutorial/datastructures.html"
            kind: reading
      - title: "Python classes and readable code"
        url: "https://www.w3schools.com/python/python_classes.asp"
        kind: external_reading
        duration_min: 45
        domain_tags: [python, classes, readability]
        axes: [software_engineering]
        depends_on: []
        optional: true
        notes: "The guide asks for familiarity with classes and recommends PEP 20, the Zen of Python, as good practice. Use a short example to connect object state and methods, then apply one readability principle to it."
        checkpoint: "Create a small class with instance state and a method, explain the difference between two instances, and apply one principle from the Zen of Python to improve the example."
        check_questions:
          - "In a small Python class, which values belong to each instance and which behavior belongs in a method?"
          - "What would happen if you created two instances and changed the state of one, and how could you check that prediction?"
          - "Choose one principle from the Zen of Python: what concrete change would it suggest for the readability of your example?"
        resources:
          - title: "Python classes"
            url: "https://www.w3schools.com/python/python_classes.asp"
            kind: reading
          - title: "PEP 20 — The Zen of Python"
            url: "https://peps.python.org/pep-0020/"
            kind: reading
      - title: "Python bonus: object-oriented programming and PEP 8"
        url: "https://www.pythontutorial.net/python-oop/"
        kind: external_reading
        duration_min: 60
        domain_tags: [python, object-oriented programming, code style]
        axes: [software_engineering]
        depends_on: []
        optional: true
        notes: "The guide explicitly labels object-oriented programming and PEP 8 as bonus material. Choose the parts relevant to code you are writing; completing both resources is not a camp requirement."
        checkpoint: "Apply one object-oriented design idea or PEP 8 recommendation to a small program, and explain how the change improves its structure or readability."
        check_questions:
          - "Choose either an object-oriented design idea or a PEP 8 recommendation from the linked material: what problem does it address?"
          - "How would you apply that idea to a small Python program, and what would be different before and after?"
          - "Why does the change help structure or readability in this example, and when might a simpler approach be preferable?"
        resources:
          - title: "Python Object-Oriented Programming"
            url: "https://www.pythontutorial.net/python-oop/"
            kind: reading
          - title: "PEP 8 — Style Guide for Python Code"
            url: "https://peps.python.org/pep-0008/"
            kind: reading

---

# ML4Good Technical Prework (Fall 2026)

Based on the public **ML4Good Hong Kong 2026 participant guide**, curriculum snapshot **2026-09-25**. This track paraphrases the technical and shared required preparation; work stays at the linked sources. Check the source guide for subsequent changes.

The original technical and shared sections keep their positions so saved progress remains attached to the same work. Selectable mathematics and Python refreshers follow them; use **Work on this next** to bring a refresher into your current flow. List position preserves saved progress; it is not a recommended starting order. Shared preparation is independently available: the guide calls the Atlas reading its most important prerequisite. Start with orientation and reading, then choose targeted refreshers before technical practice where needed. All time blocks can be spread across sessions.

The guide permits skipping familiar material. For a section you choose to complete, demonstrate the capability in its checkpoint before marking it passed, even when you skip rereading. These are Bench-authored, self-attested checks, not automated assessments or certification from ML4Good.

## Start with orientation and reading

For a first 30-minute session, spend about 5 minutes reading the preparation scope and identifying unfamiliar mathematical or Python foundations. Use **Work on this next** to select **AI Safety Atlas 1: Capabilities**, then read its introduction and a manageable part of the chapter for about 20 minutes. Spend the final 5 minutes recording a claim, a question, and your stopping point. The chapter check covers the whole section; save partial notes and return to it after reading more.

Before technical exercises, choose a targeted refresher for any foundation you cannot yet explain. Read its linked explanation and try a small example, then move to the introductory PyTorch notebook when ready. Familiar learners may go straight to practice; a notebook is not the default first activity or a diagnostic requirement. These starting suggestions are Bench guidance, not an additional ML4Good requirement.

## Scope and time estimates

- **PyTorch Basics:** follow all numbered pages **0–7**. The first block covers Quickstart, Tensors, Datasets & DataLoaders, and Transforms. The second covers Build the Neural Network, Automatic Differentiation, Optimization, and Save & Load. Use the tutorial navigation to continue between pages. Aim to recognize the tools and explain their roles; memorizing API syntax is unnecessary.
- **Tensor practice:** the aim is familiarity with high-dimensional manipulation, not passing every notebook exercise. Use representative examples to check shape reasoning.
- **Atlas:** read the first four chapters, keep notes, and bring questions. The guide names Capabilities, Risks, and Strategies while requesting four chapters; this snapshot interprets “first four” using the current contents, which also includes **Governance**.
- **Source estimates:** introductory notebook about **60 minutes**, Atlas about **420 minutes total**, camp philosophy about **20 minutes**, and the playlist about **180 minutes**. The four **105-minute** Atlas blocks are a Bench scheduling split, not chapter-specific source estimates. The **90-minute** PyTorch blocks, **30-minute** einops reading, and **90-minute** tensor practice are Bench estimates. Skip familiar playlist material; actual time depends on prior knowledge.

## Choosing refreshers

The appended mathematics and Python sections are optional **resource-completion paths**: you can select one, save a stopping point, and return to it without making every refresher a prerequisite for the main track. The source calls these mathematical capabilities essential: linear transformations and matrix basics, probability rules/expectation/standard deviation, and differentiation/partial differentiation. Optional resource completion does not mean those capabilities are unimportant. If you cannot demonstrate them, use the matching refresher before relying on them in camp work.

Each section distinguishes essential foundations from helpful or bonus extensions and includes the guide's full relevant resource list. A resource list offers explanations to choose from, not a requirement to finish every link. The new refresher time blocks are **Bench estimates**, not timings supplied by ML4Good; split them across sessions as needed.

The introductory PyTorch section includes the guide's examples reference. The tensor-practice section includes einops documentation and the einsum video as support, without adding completion requirements. Governance-only supplemental readings are outside this technical track; the shared Atlas Governance chapter remains part of the required first four chapters.
