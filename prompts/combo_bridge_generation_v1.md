# combo_bridge_generation_v1
# Bridge discovery only. JSON only; exactly three candidates.

STAGE: COMBO_BRIDGE_GENERATION_V1

You are designing mathematical interactions, not full problem statements. Given
exactly two competition-math techniques, propose exactly {{bridge_count}}
precise bridge-cruxes in which the techniques genuinely fuse.

A valid bridge makes one technique transform, expose, or encode an object that
the other technique must exploit. Reject a sequence of unrelated steps such as
"first compute with A, then plug the result into B." Each bridge must be
elementary enough to verify, capable of supporting an original AIME-style
integer-answer problem, and different from the supplied examples.

TECHNIQUES (their IDs and metadata are authoritative):
{{techniques_json}}

Use only each snapshot's `id` in technique_ids and technique_roles.

Target draft difficulty: {{target_difficulty}}.
Selected context-pair difficulty overlap: {{difficulty_overlap}}.

Return one JSON object and nothing else. Use this exact schema and no extra keys:

{
  "schema_version": "combo_bridge_generation_v1",
  "technique_ids": ["first exact ID", "second exact ID"],
  "candidates": [
    {
      "bridge_id": "b1",
      "shared_object": "the mathematical object both techniques act on",
      "interaction_type": "transforms_into",
      "crux": "one precise mathematical observation",
      "technique_roles": {
        "first exact ID": "its indispensable operation",
        "second exact ID": "its indispensable operation"
      },
      "proof_sketch": "a short verification of the bridge itself",
      "problem_shape": "a natural contest setup that could conceal this bridge",
      "integer_answer_route": "why the setup can yield a unique integer from 0 to 999",
      "naturalness": 1,
      "surprise": 1,
      "feasibility": 1,
      "stapling_risk": 0,
      "memorization_risk": 0
    }
  ]
}

Use integer scores only. naturalness/surprise/feasibility are 1–5; both risks
are 0–5. Candidate IDs must be b1 through b{{bridge_count}}. All JSON-stage
mathematics must use plain text or Unicode—never LaTeX commands or raw
backslashes. The three cruxes must be mathematically distinct, not paraphrases.
interaction_type must be exactly one of: feeds, transforms_into,
dual_representation, certifies, forces_structure, counts_same_object.
