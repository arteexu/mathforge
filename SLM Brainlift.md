# BrainLift: Problem Generation Is the Inverse of Problem Solving

An SLM fine-tuned to write AIME-level competition problems insight-first: every problem begins as a crux insight and is built outward into an elegant statement. This is because elegant problems, not long ones, are what train mathematical creativity. When I create problems, it’s out of insight and built inside out.

## Owners

- Arthur Xu

## Purpose

The purpose of this BrainLift is to redefine what it means to *generate* a competition math problem, and to build a small language model whose one reliable behavior embodies that definition. The consensus approach right now generates problems topic-first: pick a topic, assemble steps, tune the numbers. The result is exercises: problems that reward procedural fluency and stamina. But the problems that actually develop critical thinking (late-AIME, olympiad) are built the other way around. They begin with a single intriguing observation, and the statement is engineered so that the problem *falls* to that observation and resists everything else. A student with complete command of algebra, geometry, number theory, and precalculus should still be stopped cold until they find the insight.

So the model's unit of generation is the **crux insight**, not the topic. The training data is (insight → problem) pairs reverse-engineered from real contest problems; the behavior spec is that the model always builds a well-posed, integer-answer problem whose solution genuinely pivots on the seeded insight, without step-stacking. The educational payoff is a generator of *problem families*. This is a host of unlimited fresh surface realizations of one deep structure, which is precisely what the transfer literature says trains pattern recognition, and what static problem banks cannot do right now.

The dataset is the deliverable. The model is the dataset made runnable.

## In Scope

- Learning science governing schema induction, transfer, variation, desirable difficulties, and problem *posing* (as distinct from problem solving), as they apply to competition mathematics.  
- A structured account of what makes a competition problem good: crux insights, difficulty as a behavioral (not structural) property, elegance as a falsifiable property.  
- The data pipeline: harvesting rated contest problems, reverse-engineering them into (crux insight → problem) pairs, synthetic expansion via teacher distillation, and a verification-first quality gate.  
- Evaluation: base-vs-tuned measurement of insight-faithfulness, answer verifiability, difficulty band, elegance, and novelty.  
- AIME-band short-answer problems (with an easier-AIME comparison band).

## Out of Scope

- **Proof-based generation (USAJMO/USAMO) in v1 (for now).** Proofs have no cheap verifier and no unique integer answer, so every quality signal collapses into LLM-judge opinion. The base project will have time to implement this right now. It is the explicit stretch goal, gated on the AIME loop demonstrably working.  
- Training a model to *solve* competition problems. Solving is the verifier's job in the pipeline, performed by existing models; the trained behavior is generation.  
- Beating frontier models on capability. The thesis is reliable constrained behavior from data in a tiny local model, not raw intelligence.  
- General math-education content (curricula, lessons, hints). One target, one context.

**A note on the AIME:** the AIME is 15 short-answer problems, each with an integer answer from 0 to 999, taken by top AMC scorers. Difficulty ramps steeply: problems 1–7 are hard exercises; problems 10–15 are where nearly every solver is stopped until they find a non-routine idea. The integer-answer format is a gift to this project — it makes machine verification of generated problems cheap and decisive, which is the property that makes the whole pipeline falsifiable.

**Discipline the pipeline enforces (verification-first):** a generated problem is *not data* until (a) independent solvers converge on one integer answer, (b) a weak solver fails it at the target rate, and (c) the independent solutions demonstrably pivot on the seeded insight. Elegance judging happens only after those gates. This ordering is enforced in the pipeline code, not left to intention.

## DOK 4: Spiky Points of View (SPOVs)

### Spiky POV 1: A competition problem's identity is its crux insight, not its topic. Thus, generation must run insight-first, inverting how problem banks, prep books, and current synthetic-data pipelines are organized.

**Explanation:** Existing organizations of competition math like textbooks, prep courses, and the big synthetic math datasets used to train LLMs (MetaMath-style augmentation, GSM-variant pipelines) often treat the *topic* or the *template* as the atom: pick "quadratics," instantiate numbers, vary the surface. This produces exercises, because surface variation of a routine template never creates the property that defines a good hard problem: that knowing all the relevant concepts is insufficient. What defines a late-AIME problem are non-routine observations, the crux of the problem. The same crux (e.g., "count by symmetry classes instead of directly," "the order of an element jumps predictably at prime powers," "interpret the algebraic expression as a distance") recurs across topics and decades while surface details change. This is exactly the schema/surface distinction from analogical-transfer research: Gick & Holyoak showed people fail to reuse a solution principle across surface changes unless the deep structure is made the explicit object of attention. My claim inverts the data model accordingly: the training pair is (crux insight → problem), and the topic is a secondary tag. A model trained topic-first learns to imitate the *look* of AIME problems; a model trained insight-first learns the generative grammar of *why* they're hard.

**Falsifiable version:** hold the SFT budget fixed and train two models on the same problems, one conditioned on topic tags only, one conditioned on extracted crux insights. If insight-conditioning does not produce a significantly higher rate of problems that (a) pass the weak-solver difficulty gate and (b) pass the insight-faithfulness check, the POV is wrong and topic-first is vindicated.

### Spiky POV 2: A problem is hard not because of the underlying topics, but because of the way they are elegantly combined.

**Explanation:** The intuitive proxy for difficulty and the one LLMs often default to when asked for a "hard" problem is structural: more steps, more variables, uglier numbers, more machinery. This is the consensus embedded in most synthetic "hard problem" generation, and it is wrong in a way that actively damages learning. A 12-step routine problem trains bookkeeping; the best AIME problems are famously short to solve *once you see it*. Psychometrics settled the right definition decades ago: in item response theory, an item's difficulty is a parameter estimated from response behavior, who gets it right, not from any structural feature of the item. The community already lives by this: AIME positions reflect empirical solve rates, AoPS's difficulty scale and Evan Chen's MOHS hardness scale for olympiad problems are calibrated to solver experience, not solution length. My position operationalizes it for a generation pipeline: difficulty \= the pair (weak-solver solve rate, strong-solver solve rate), where the target band is "weak solvers fail, strong solvers succeed" — hard because of an idea, not broken and not long. Step-stacked drafts are *rejected* even when their answers verify. This is spiky because it makes the most common way to generate "hard" problems a filtered-out failure mode.

**Falsifiable version:** across generated problems, structural features (solution token length, step count) should correlate only weakly with panel solve rates within the accepted set; and human competitors' quality ratings of accepted problems should track the behavioral difficulty band, not step count. If step count turns out to predict both solve rate and rated quality, the structural view wins and the anti-step-stacking gate is unjustified.

### Spiky POV 3: Elegance is falsifiable. "The best problems use a simple idea creatively" can be reduced to measurable properties. For example, crux count ≤ 2, short post-insight solution, and failure of routine methods, rather than left as taste.

**Explanation:** The consensus treats mathematical elegance as ineffable. Hardy's "beauty is the first test" is quoted as an aesthetic mystery, and problem quality in practice is adjudicated by expert taste (contest problem committees). If that's true, an automated pipeline can never select for quality and this project dies at the filter. My position is that for *this genre*, elegance decomposes into checkable properties: (1) **low crux count** — the accepted solution contains at most one or two non-routine moves, everything else routine; (2) **high resistance** — solvers who only apply standard methods fail (the weak-solver gate); (3) **surprise/compression** — the solution is short relative to the apparent complexity of the statement. This tracks the mathematical-aesthetics literature more faithfully than the "ineffability" reading: Sinclair documents aesthetics functioning as an operational *guide* in mathematical work, not just a verdict; Dreyfus & Eisenberg found that appreciating an elegant solution is precisely appreciating economy of means over brute force. Hardy himself named the criteria — unexpectedness combined with inevitability and economy. The spiky consequence: my pipeline's elegance gate is a rubric an LLM judge (calibrated against my own hand-labels) applies mechanically, and "we selected for elegance" becomes an auditable claim instead of a vibe.

**Falsifiable version:** collect blind quality ratings from experienced AIME-level competitors on accepted problems. If the rubric's elegance scores fail to correlate with expert ratings meaningfully better than chance — or if step-stacked rejects are rated as highly as accepted problems — elegance was not captured and the gate is theater.

### Spiky POV 4: The educational value of a *generator* is problem families, not problem banks. Near-transfer variations sharing one crux train pattern recognition better than an equal number of unrelated problems, which is something static banks structurally cannot provide.

**Explanation:** The consensus model of contest prep is the bank: accumulate past problems, do them, review solutions. Banks are finite, contaminated (solutions are one search away), and — most importantly — structured by year and topic, not by deep structure, so the student rarely sees the same crux twice in close succession with varied surfaces. But the transfer literature is unambiguous about what induces schemas: *comparison across analogs*. Gick & Holyoak showed one example almost never transfers while two structurally-aligned examples do; Marton's variation theory sharpens this — a learner discerns a critical feature only when it varies against an invariant background (or stays invariant while everything else varies), which is exactly a problem family: crux invariant, surface varying. Kornell & Bjork and Rohrer add the discrimination side: mixing families interleaved trains the "which pattern is this?" judgment that is the actual bottleneck skill. A trained insight-first generator is the only artifact that can serve this on demand — fresh, uncontaminated, surface-novel instances of any chosen crux, at a chosen difficulty. That reframes the SLM from "content mill" to "the missing instrument for schema-level practice." This is also the honest answer to "why does this even exist" when frontier models loom: a cheap local model that reliably instantiates a *specified* deep structure is a pedagogical instrument; a frontier model that brilliantly freestyles is not.

**Falsifiable version:** a study-time-matched comparison — students practicing generated families (same crux, varied surface, interleaved across families) vs. an equal number of unrelated bank problems — should show an advantage on *novel* mixed transfer items sharing the practiced cruxes. Prediction registered up front; a null result reported honestly would cut against the family claim (though not against the generator's validity metrics).

## Experts

- **Mary L. Gick & Keith J. Holyoak**  
    
  - **Who:** Cognitive scientists; foundational researchers on analogical transfer and schema induction.  
  - **Focus:** Their 1980/1983 studies showed solvers fail to transfer a principle to a structurally identical problem from one example, but succeed after comparing two analogs — comparison forces extraction of the shared schema.  
  - **Why follow:** The scientific core of SPOV 1 and SPOV 4\. The crux insight *is* the schema; problem families *are* the analogs. The entire (insight → problem) data model is Gick & Holyoak run in reverse: instead of asking students to extract the schema, the generator instantiates it.  
  - **Where:** Gick & Holyoak (1980), "Analogical Problem Solving," *Cognitive Psychology* 12; Gick & Holyoak (1983), "Schema Induction and Analogical Transfer," *Cognitive Psychology* 15\. [https://pdf.retrievalpractice.org/transfer/Gick\_Holyoak\_1980.pdf](https://pdf.retrievalpractice.org/transfer/Gick_Holyoak_1980.pdf)


- **George Pólya**  
    
  - **Who:** Mathematician and the founder of modern problem-solving pedagogy (*How to Solve It*, 1945; *Mathematical Discovery*).  
  - **Focus:** Heuristics of mathematical discovery — and, underappreciated, the "looking back" phase: varying the problem, generalizing it, asking what made the solution work. Pólya treats problem *variation* as the highest form of understanding a solution.  
  - **Why follow:** Pólya's looking-back is exactly the reverse-engineering annotation step: dissect a solved problem into the thing that made it work, at a level of generality that could seed a new problem. He is the intellectual license for treating generation as the inverse of solving.  
  - **Where:** Pólya, *How to Solve It* (Princeton, 1945); *Mathematical Discovery* (Wiley, 1962).


- **Edward A. Silver (with Brown & Walter)**  
    
  - **Who:** Mathematics-education researcher; the central academic figure on **problem posing**. Stephen Brown & Marion Walter wrote the field's founding book, *The Art of Problem Posing*.  
  - **Focus:** Silver (1994) frames problem posing as a cognitive activity intertwined with understanding — the ability to pose good problems tracks depth of knowledge, not just fluency. Brown & Walter's "what-if-not" method systematically mutates a known problem's attributes to produce new ones.  
  - **Why follow:** This is the only literature directly about the target behavior — generating problems, not solving them. "What-if-not" is implemented literally in the pipeline's seed-mutation stage (swap the modulus, invert the constraint, change the geometric object while preserving the crux).  
  - **Where:** Silver (1994), "On Mathematical Problem Posing," *For the Learning of Mathematics* 14(1); Brown & Walter, *The Art of Problem Posing* (3rd ed., Routledge, 2005).


- **Ference Marton**  
    
  - **Who:** Educational psychologist (Gothenburg); originator of **variation theory**.  
  - **Focus:** A learner can only discern a critical aspect of a concept when that aspect *varies* against an invariant background — or remains invariant while everything else varies. Learning design is therefore the deliberate engineering of patterns of variance and invariance.  
  - **Why follow:** Variation theory is the precise theoretical description of a problem family: crux invariant, surface features varying. It converts SPOV 4 from an intuition into a design principle the generator's seed-sampling implements.  
  - **Where:** Marton, *Necessary Conditions of Learning* (Routledge, 2015); Marton & Booth, *Learning and Awareness* (1997).


- **Robert A. Bjork & Elizabeth L. Bjork (and Doug Rohrer)**  
    
  - **Who:** Cognitive psychologists; originators of the "desirable difficulties" framework (UCLA) and the leading researcher on interleaved math practice (Rohrer, USF).  
  - **Focus:** Conditions that make practice feel harder — interleaving, spacing, retrieval — produce more durable, more transferable learning; Kornell & Bjork (2008) and Rohrer & Taylor (2007) show interleaving specifically trains *category discrimination* and method selection on novel items.  
  - **Why follow:** Grounds the deployment story: generated families should be interleaved, not blocked, because the bottleneck contest skill is "which crux is this?" — a discrimination judgment. Also grounds why generated problems should sit at the edge of failure (the difficulty band), not comfortably solvable.  
  - **Where:** Kornell & Bjork (2008), *Psychological Science*; Rohrer & Taylor (2007), *Instructional Science*; bjorklab.psych.ucla.edu.


- **Nathalie Sinclair (with Dreyfus & Eisenberg; G.H. Hardy)**  
    
  - **Who:** Mathematics-education researcher on the roles of aesthetics in mathematical activity; Dreyfus & Eisenberg wrote the classic study on students' appreciation of solution elegance; Hardy supplies the canonical criteria.  
  - **Focus:** Sinclair (2004) shows aesthetic judgments function *operationally* in mathematics — guiding, motivating, and evaluating inquiry — rather than as mere decoration. Dreyfus & Eisenberg (1986) characterize elegance as economy of means and show it must be explicitly taught. Hardy names the components: unexpectedness, inevitability, economy.  
  - **Why follow:** The backbone of SPOV 3\. If aesthetics is operational, it is specifiable; if it is specifiable, an elegance rubric is legitimate rather than a category error.  
  - **Where:** Sinclair (2004), "The Roles of the Aesthetic in Mathematical Inquiry," *Mathematical Thinking and Learning* 6(3); Dreyfus & Eisenberg (1986), "On the Aesthetics of Mathematical Thought," *For the Learning of Mathematics* 6(1); Hardy, *A Mathematician's Apology* (1940).


- **Practitioners: Evan Chen & Richard Rusczyk**  
    
  - **Who:** Chen — olympiad coach, USAMO problem committee experience, author of the MOHS hardness scale and extensive public writing on how olympiad problems are proposed and selected. Rusczyk — founder of Art of Problem Solving, architect of the dominant discovery-based contest curriculum.  
  - **Focus:** Chen's writing on problem proposals describes real problems as growing from a "nugget" — a surprising observation the proposer then dresses into a statement — which is the insight-first thesis stated by a practitioner who lives it. Rusczyk's curriculum philosophy is built on students confronting problems *slightly beyond* their reach, the practitioner form of desirable difficulty.  
  - **Why follow:** They are the ground truth for what the expert community means by problem quality; the elegance judge and crux annotations are calibrated toward their standards. Chen's MOHS ratings are also a direct data source for the olympiad stretch corpus.  
  - **Where:** web.evanchen.cc (MOHS scale; writing on problem proposals); Rusczyk, Art of Problem Solving curriculum and talks.

## DOK 3: Insights

**Theme A: The unit of generation**

- **Insight 1:** Because every AIME problem is surface-unique but crux-recurrent, the generator's atomic object must be the crux insight, with the problem as a rendered instance — the same atom-inversion the LSAT BrainLift made for study tools, now applied to the *production* side. The data model, the seed format, the eval, and the DPO pairs are all keyed to the crux.  
- **Insight 2:** Reverse-engineering is cheaper and more reliable than de-novo invention. A teacher model asked to "write a hard problem" regurgitates or step-stacks; a teacher asked to *extract the crux* from a verified real problem, then re-instantiate it in a new surface, has its creativity constrained by ground truth. Harvested problems are therefore primarily a source of *insights*, secondarily a source of text.

**Theme B: What difficulty and quality actually are**

- **Insight 3:** The integer-answer format makes this project falsifiable in a way essay-like generation tasks never are: answer-consistency across independent solves is a hard, cheap verifier, so "the dataset is high quality" is an auditable claim. This is also the decisive reason proofs are out of scope for v1.  
- **Insight 4:** Solve-rate banding with a two-solver panel (weak fails, strong succeeds) operationalizes "hard because of an idea": problems the strong solver also fails are usually broken, and problems the weak solver passes are exercises. The band *is* the definition of the product.  
- **Insight 5:** Step-stacking is the signature failure mode of LLM-generated "hard" problems, so it must be a first-class rejection reason — and every step-stacked reject sharing a seed with an accepted problem is a free DPO preference pair. The pipeline's garbage is the alignment data.

**Theme C: From generator to learning tool**

- **Insight 6:** A problem family (crux invariant, surface varying) is variation theory made executable, and comparison across two family members is Gick & Holyoak's transfer condition made on-demand. Static banks cannot do this; a generator is the first artifact that can.  
- **Insight 7:** Contamination cuts both ways: students can look up bank problems (motivating fresh generation) and the base model has memorized historical AIME (mandating novelty scoring and held-out-year evals). Novelty is therefore both a pedagogical feature and an integrity metric, measured the same way (embedding distance to corpus).  
- **Insight 8:** The small model's defensible win is *constraint-keeping*, not brilliance: always honoring the seed, always well-posed, always integer-answer, never step-stacking. Difficulty attainment is reported honestly as the hardest metric; the thesis survives even if peak difficulty tops out below P13, because the behavior — insight-faithful generation — is what was trained.

## DOK 2: Knowledge Tree

- **Category 1: The AIME — structure and difficulty gradient**  
    
  - **Source:** MAA / AoPS contest pages and archives.  
  - **DOK 1 — Facts:** 15 problems, 3 hours, each answer an integer 0–999; two versions (I and II) per year; qualification via top AMC 10/12 scores; difficulty ramps so that late problems have very low solve rates among an already-elite population; the AoPS community maintains an approximate 1–10 difficulty scale on which late AIME sits roughly 5–6.5.  
  - **DOK 2 — Summary:** The integer-answer format enables machine verification; the position-number gradient provides free human difficulty labels; the elite-population solve rates confirm difficulty is behavioral.  
  - **Link:** [https://artofproblemsolving.com/wiki/index.php/AIME\_Problems\_and\_Solutions](https://artofproblemsolving.com/wiki/index.php/AIME_Problems_and_Solutions)


- **Category 2: Data sources for harvesting**  
    
  - **Source:** Public HuggingFace datasets and contest archives.  
  - **DOK 1 — Facts:** Omni-MATH (\~4.4k olympiad problems with AoPS-scale difficulty ratings); NuminaMath-CoT / 1.5 (\~860k+ problems with solutions, including AMC/AIME/olympiad subsets); MATH (Hendrycks, 12.5k, leveled); DeepScaleR and Big-Math as pre-verified pools; HMMT/PUMaC/CMIMC/OMO archives at comparable difficulty; Evan Chen's MOHS-rated olympiad archive for the proof stretch.  
  - **DOK 2 — Summary:** Enough rated, solution-attached material exists publicly that scraping is unnecessary; the scarce thing is not problems but *crux annotations and verification* — which is where the project's labor goes. MAA copyright means published artifacts are annotations \+ synthetic problems, with harvested items referenced by pointer.  
  - **Link:** [https://huggingface.co/datasets/KbsdJames/Omni-MATH](https://huggingface.co/datasets/KbsdJames/Omni-MATH)


- **Category 3: Learning-science foundations**  
    
  - **Subcategory 3.1: Schema induction / transfer** — Gick & Holyoak (1980, 1983): single examples rarely transfer; compared analogs do. Foundation of SPOV 1/4. [https://pdf.retrievalpractice.org/transfer/Gick\_Holyoak\_1980.pdf](https://pdf.retrievalpractice.org/transfer/Gick_Holyoak_1980.pdf)  
  - **Subcategory 3.2: Variation theory** — Marton (2015): discernment requires engineered variance against invariance; the formal design theory of problem families.  
  - **Subcategory 3.3: Interleaving / discrimination** — Kornell & Bjork (2008); Rohrer & Taylor (2007): interleaving trains category identification on novel items — the "which crux is this?" skill. [https://web.williams.edu/Psychology/Faculty/Kornell/Publications/Kornell.Bjork.2008a.pdf](https://web.williams.edu/Psychology/Faculty/Kornell/Publications/Kornell.Bjork.2008a.pdf)  
  - **Subcategory 3.4: Problem posing** — Silver (1994); Brown & Walter (2005): posing as a marker and driver of understanding; "what-if-not" as a systematic mutation method — implemented in seed sampling.  
  - **Subcategory 3.5: Mathematical aesthetics** — Sinclair (2004); Dreyfus & Eisenberg (1986); Hardy (1940): elegance as operational economy \+ surprise, hence rubric-able (SPOV 3).  
  - **Subcategory 3.6: Difficulty as a behavioral parameter** — item response theory (Lord, 1980, *Applications of Item Response Theory*): item difficulty is estimated from response patterns, not item structure; the psychometric license for solve-rate banding (SPOV 2).


- **Category 4: ML context (why this is buildable in a week)**  
    
  - **DOK 1 — Facts:** QLoRA SFT on a ≤4B instruct model fits a single GPU; teacher distillation with hard filtering is the standard recipe for instilling narrow behaviors; frontier models step-stack and regurgitate when asked for "hard original problems," and memorization of historical AIME is pervasive — motivating novelty scoring and held-out-year evals.  
  - **DOK 2 — Summary:** The training loop is commodity; the differentiated work is the insight annotation scheme and the verification-first funnel. The dataset is the deliverable.