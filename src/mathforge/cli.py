"""MathForge command-line interface.

The pipeline stages are wired up as Typer subcommands. They are intentionally
*stubs* for now — each validates/initializes state and describes the work it
will do, so the surface area and data flow are locked in before the real logic
lands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Insight, LLMCall, Problem, Solution

app = typer.Typer(
    name="mathforge",
    help="Generate elegant, AIME/olympiad-level competition math problems.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _stub(stage: str, detail: str) -> None:
    console.print(f"[bold yellow]stub[/] [cyan]{stage}[/]: {detail}")


@app.command()
def init(db_url: Optional[str] = typer.Option(None, help="Override database URL.")):
    """Create the SQLite database and all tables."""
    engine = db.init_db(db_url)
    console.print(f"[green]initialized[/] database at [bold]{engine.url}[/]")


@app.command()
def fetch(
    dataset: str = typer.Argument(
        "all", help="Which to download: 'omni-math', 'numina', or 'all'."
    ),
):
    """Download + cache source datasets (Omni-MATH, NuminaMath-1.5) from HF."""
    from mathforge import datasets as ds

    targets = {
        "omni-math": ("Omni-MATH", ds.load_omni_math),
        "numina": ("NuminaMath-1.5", ds.load_numina_math),
    }
    if dataset != "all":
        if dataset not in targets:
            raise typer.BadParameter("choose 'omni-math', 'numina', or 'all'")
        targets = {dataset: targets[dataset]}

    for label, loader in targets.values():
        console.print(f"[cyan]downloading[/] {label} ...")
        data = loader()
        console.print(f"  [green]ready[/] {label}: {len(data):,} rows -> {data.cache_files[0]['filename'] if data.cache_files else 'cache'}")


@app.command()
def ingest(
    dataset: str = typer.Argument("omni-math", help="Dataset to ingest (omni-math)."),
    threshold: float = typer.Option(
        4.0, help="Easy/hard split on difficulty: <threshold=easy, >=threshold=hard."
    ),
    limit: Optional[int] = typer.Option(None, help="Max rows to ingest (debug)."),
    db_url: Optional[str] = typer.Option(None),
):
    """Import a source dataset into the bank, deduped and split into tiers.

    Omni-MATH is the primary set: every problem is labeled 'easy' or 'hard' by
    its difficulty rating, forming two separate sections.
    """
    if dataset != "omni-math":
        raise typer.BadParameter(
            "only 'omni-math' is wired up right now (NuminaMath-1.5 comes later)"
        )
    from mathforge.ingest import ingest_omni_math

    console.print(f"[cyan]ingesting[/] Omni-MATH (threshold={threshold}) ...")
    report = ingest_omni_math(threshold=threshold, limit=limit, db_url=db_url)

    table = Table(title="Omni-MATH ingest")
    table.add_column("metric", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("problems added", str(report.problems))
    table.add_row("  easy section (<%.1f)" % threshold, str(report.per_tier["easy"]))
    table.add_row("  hard section (>=%.1f)" % threshold, str(report.per_tier["hard"]))
    table.add_row("solutions added", str(report.solutions))
    table.add_row("evaluations added", str(report.evaluations))
    table.add_row("skipped duplicates", str(report.skipped_duplicates))
    console.print(table)


def _training_count(db_url: Optional[str]) -> int:
    with db.session_scope(db_url) as session:
        return len(session.exec(db.training_problems_select()).all())


@app.command(name="extract-features")
def extract_features_cmd(
    extractor: str = typer.Option(
        "heuristic", help="Feature extractor: 'heuristic' (offline) or 'llm' (teacher)."
    ),
    model: str = typer.Option("echo", help="Teacher model (for extractor='llm')."),
    limit: Optional[int] = typer.Option(100, help="Max problems this pass (None=all)."),
    split: str = typer.Option("train", help="Which split to extract (default: train)."),
    overwrite: bool = typer.Option(False, help="Re-extract even if features exist."),
    db_url: Optional[str] = typer.Option(None),
):
    """Teacher feature extraction per solution -> difficulty-predictor features.

    Stores a teacher Solution row per problem with techniques, crux_insight,
    crux_count, routine_step_count, prerequisite_level, and standard_method_solves.
    """
    from mathforge.features import run_extraction

    if extractor not in ("heuristic", "llm"):
        raise typer.BadParameter("extractor must be 'heuristic' or 'llm'")

    console.print(
        f"[cyan]extracting features[/] (extractor={extractor}, model={model}, "
        f"split={split}) ..."
    )
    report = run_extraction(
        extractor=extractor,
        model=model,
        limit=limit,
        split=split,
        db_url=db_url,
        overwrite=overwrite,
    )

    table = Table(title="Feature extraction")
    table.add_column("metric", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("teacher solutions written", str(report.extracted))
    table.add_row("skipped (already extracted)", str(report.skipped_existing))
    table.add_row("parse errors (fell back)", str(report.parse_errors))
    if report.extractor == "llm":
        table.add_row("logged LLM cost", f"${report.llm_cost_usd:.4f}")
    console.print(table)
    if report.per_level:
        console.print(
            "by prerequisite level: "
            + ", ".join(f"L{k}={report.per_level[k]}" for k in sorted(report.per_level))
        )


@app.command()
def annotate(
    limit: int = typer.Option(100, help="Max problems to annotate this pass."),
    db_url: Optional[str] = typer.Option(None),
):
    """Annotate TRAIN problems with teacher difficulty features (heuristic)."""
    from mathforge.features import run_extraction

    db.init_db(db_url)
    report = run_extraction(
        extractor="heuristic", limit=limit, split="train", db_url=db_url
    )
    console.print(
        f"[green]annotated[/] {report.extracted} problems "
        f"({report.skipped_existing} already had features)"
    )


@app.command()
def generate(
    n: int = typer.Option(10, help="How many candidate problems to generate."),
    band: str = typer.Option("aime_hard", help="Target difficulty band."),
    model: str = typer.Option("echo", help="Generator model."),
    db_url: Optional[str] = typer.Option(None),
):
    """Grow candidate Problems from seed Insights using a frontier model."""
    db.init_db(db_url)
    avail = _training_count(db_url)
    _stub(
        "generate",
        f"sample {n} Insights (band={band!r}) mined from {avail} TRAIN problems "
        f"(eval held out), prompt {model!r}, store candidate Problems",
    )


def _ask_score(label: str, parser, allow: set[str]):
    """Prompt until a valid score (via ``parser``) or a control key in ``allow``."""
    while True:
        try:
            raw = input(f"  {label}: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "q"
        low = raw.lower()
        if low in allow:
            return low
        try:
            return parser(raw)
        except ValueError as exc:
            console.print(f"  [red]{exc or 'invalid input'}[/] (or 's'=skip, 'q'=quit)")


@app.command()
def label(
    count: int = typer.Option(150, help="How many problems to line up this session."),
    split: str = typer.Option("train", help="Which split to label: train | eval | all."),
    seed: Optional[int] = typer.Option(None, help="Fix the sampling order (optional)."),
    clear: bool = typer.Option(True, help="Clear the screen between problems."),
    raw: bool = typer.Option(False, "--raw", help="Show raw LaTeX instead of rendered Unicode."),
    db_url: Optional[str] = typer.Option(None),
):
    """Hand-label difficulty (1-10) and elegance (0-5) — the ground truth.

    Presentation order is randomized and all existing ratings/source/ids are
    hidden so you're never anchored. Already-labeled problems are skipped, so you
    can stop ('q') and resume anytime.
    """
    from mathforge.labeling import (
        parse_difficulty,
        parse_elegance,
        record_human_label,
        select_label_batch,
        visible_solutions,
    )
    from mathforge.render import render_math

    def show(text: str) -> str:
        return render_math(text, enabled=not raw)

    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        ids = select_label_batch(session, count=count, split=split, seed=seed)
    if not ids:
        console.print("[green]nothing to label[/] — every problem in this split is done.")
        return

    console.print(
        "[bold]Human labeling[/]\n"
        "difficulty 1-10 (AoPS: 3~easy AIME, 5-6~late AIME, 6.5-7~AIME P15/easy olympiad)\n"
        "elegance 0-5 (5 beautiful/top-tier · 4 strong, elegant · 3 elegant, quality · "
        "2 decent · 1 poor · 0 bad)\n"
        "Enter 's' to skip, 'q' to quit."
    )

    labeled = 0
    for i, pid in enumerate(ids, 1):
        with db.session_scope(db_url) as session:
            problem = session.get(Problem, pid)
            solutions = visible_solutions(session, pid)

        if clear:
            console.clear()
        console.rule(f"Problem {i} of {len(ids)}   (labeled this session: {labeled})")
        console.print(show(problem.statement))
        if solutions:
            for k, text in enumerate(solutions, 1):
                console.print(f"\n[dim]— solution {k} —[/]")
                console.print(show(text))
        else:
            console.print("\n[dim](no worked solution available)[/]")
        console.print()

        difficulty = _ask_score("difficulty (1-10)", parse_difficulty, {"s", "q"})
        if difficulty == "q":
            break
        if difficulty == "s":
            continue
        # Revealed only after your own difficulty call, so it can't anchor it.
        ref = problem.difficulty
        ref_txt = f"{ref}" if ref is not None else "n/a (no source rating)"
        console.print(f"  [dim]current difficulty label (source): {ref_txt}[/]")
        elegance = _ask_score("elegance (0-5)", parse_elegance, {"s", "q"})
        if elegance == "q":
            break
        if elegance == "s":
            continue
        try:
            note = input("  note (optional): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        with db.session_scope(db_url) as session:
            record_human_label(session, pid, difficulty, elegance, note)
        labeled += 1

    console.print(f"\n[green]done[/] — recorded {labeled} human label(s) this session.")


@app.command()
def distill(
    n: int = typer.Option(25, help="How many problems to attempt this run."),
    k: int = typer.Option(3, help="Independent solver samples per verification."),
    generator_model: str = typer.Option("gpt-5.4", help="Frontier model that generates."),
    solver_model: Optional[str] = typer.Option(None, help="Independent verifier model (default: generator)."),
    judge_model: Optional[str] = typer.Option(None, help="Judge/repair model (default: solver)."),
    backend: str = typer.Option("openai", help="'openai' (real API) or 'echo' (offline dry run)."),
    base_url: Optional[str] = typer.Option(None, help="Generator base URL (default: OpenAI)."),
    api_key_env: str = typer.Option("OPENAI_API_KEY", help="Env var with the generator key."),
    solver_base_url: Optional[str] = typer.Option(None, help="Verifier/judge base URL (default: generator's)."),
    solver_key_env: Optional[str] = typer.Option(None, help="Env var with the verifier/judge key (default: generator's)."),
    verify: bool = typer.Option(
        True, "--verify/--no-verify",
        help="--no-verify: generation-only; verify later with Opus via qa-export/qa-apply.",
    ),
    db_url: Optional[str] = typer.Option(None),
):
    """Distill problems from a frontier model into the synthetic bank.

    Recommended flow: `distill --no-verify` (diverse candidates), then verify +
    correct with a strong out-of-band model via `qa-export` -> `qa-apply`.
    """
    from mathforge.distill import run_distill
    from mathforge.llm import LLMClient, make_anthropic_backend, make_openai_backend

    solver_model = solver_model or generator_model
    judge_model = judge_model or solver_model
    # Verifier/judge may live on a different provider than the generator.
    v_base_url = solver_base_url if solver_base_url is not None else base_url
    v_key_env = solver_key_env or api_key_env

    def make_client(model: str, url: Optional[str], key_env: str) -> LLMClient:
        be = None
        if backend == "openai":
            be = make_openai_backend(model, base_url=url, api_key_env=key_env)
        elif backend == "anthropic":
            # Reads ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN (gateway) from env.
            be = make_anthropic_backend(model)
        return LLMClient(model=model, backend=be, purpose="distill", db_url=db_url)

    console.print(
        f"[cyan]distilling[/] n={n}, k={k} · generate={generator_model} · "
        f"verify={solver_model} · judge={judge_model} · backend={backend}"
    )
    if backend == "openai":
        console.print(f"[dim]using OpenAI-compatible API (key env: {api_key_env}"
                      f"{', base_url=' + base_url if base_url else ''})[/]")

    try:
        report = run_distill(
            n=n,
            generator=make_client(generator_model, base_url, api_key_env),
            solver=make_client(solver_model, v_base_url, v_key_env),
            judge=make_client(judge_model, v_base_url, v_key_env),
            k=k,
            target=None,  # rotate topics/difficulty for diversity
            verify=verify,
            db_url=db_url,
        )
    except Exception as exc:  # surface API/key errors cleanly
        console.print(f"[red]distill failed[/]: {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1)

    table = Table(title="Distill run")
    table.add_column("metric", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("generated", str(report.generated))
    table.add_row("parse failures", str(report.parse_failures))
    table.add_row("banned template skipped", str(report.template_skipped))
    if not verify:
        table.add_row("stored raw (verify later)", str(report.raw_stored))
    table.add_row("verified directly", str(report.verified_direct))
    table.add_row("repaired then verified", str(report.repaired))
    table.add_row("unverified (kept for review)", str(report.unverified))
    table.add_row("duplicates skipped", str(report.duplicates))
    table.add_row("errors (skipped)", str(report.errors))
    table.add_row("stored (pending review)", str(report.stored))
    table.add_row("logged cost", f"${report.cost_usd:.4f}")
    console.print(table)
    if report.last_error:
        console.print(f"[yellow]last error:[/] {report.last_error}")
    for r in report.records:
        flag = "[green]verified[/]" if r.get("verified") else "[red]UNVERIFIED[/]"
        console.print(
            f"  {flag} [bold]{r.get('id', '—')}[/] ans={r['answer']} "
            f"difficulty={r['difficulty']} elegance={r['elegance']} "
            f"topic={r['topic']}" + ("  [yellow](repaired)[/]" if r["repaired"] else "")
        )
    if report.stored:
        if verify:
            console.print("\nreview them with: [bold]mathforge review[/]")
        else:
            console.print(
                "\nnext: [bold]mathforge qa-export candidates.json[/] -> verify + correct "
                "with Opus -> [bold]mathforge qa-apply verdicts.json[/]"
            )


@app.command(name="qa-export")
def qa_export_cmd(
    out: Path = typer.Argument(Path("candidates.json"), help="Where to write candidates."),
    statuses: str = typer.Option("pending,needs_edit", help="Comma-list of review statuses."),
    limit: Optional[int] = typer.Option(None, help="Max candidates to export."),
    db_url: Optional[str] = typer.Option(None),
):
    """Export unverified candidates (id + statement + stored answer) for verification."""
    import json as _json

    from mathforge.agents import export_candidates

    status_tuple = tuple(s.strip() for s in statuses.split(",") if s.strip())
    rows = export_candidates(db_url=db_url, statuses=status_tuple, limit=limit)
    out.write_text(_json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]exported[/] {len(rows)} candidate(s) to [bold]{out}[/]")
    console.print(
        "Have a strong model solve/verify each, then write a verdicts JSON "
        "(list of {id, correct_answer?, wellposed, recommendation, reason, difficulty?, elegance?}) "
        "and run: [bold]mathforge qa-apply verdicts.json[/]"
    )


@app.command(name="qa-apply")
def qa_apply_cmd(
    verdicts_file: Path = typer.Argument(..., help="JSON list of verdicts."),
    apply_status: bool = typer.Option(
        False, help="Also set review_status from each recommendation."
    ),
    db_url: Optional[str] = typer.Option(None),
):
    """Apply out-of-band (Opus in-chat) verification verdicts to the bank."""
    import json as _json

    from mathforge.agents import apply_verdicts

    verdicts = _json.loads(verdicts_file.read_text(encoding="utf-8"))
    counts = apply_verdicts(verdicts, db_url=db_url, apply_status=apply_status)
    console.print(
        f"[green]applied[/] {counts['applied']} verdict(s); "
        f"{counts['corrected']} answer(s) corrected. by recommendation: {counts['by_rec']}"
    )
    if counts["not_found"]:
        console.print(f"[yellow]not found:[/] {counts['not_found']}")


@app.command(name="elegance-export")
def elegance_export_cmd(
    out: Path = typer.Argument(Path("elegance_sample.json"), help="Where to write the sample."),
    target: int = typer.Option(72, help="Sample size (stratified across topic x band)."),
    id_prefix: str = typer.Option("omni-math-", help="Which problems to sample."),
    db_url: Optional[str] = typer.Option(None),
):
    """Export a stratified sample (statement + solution) for elegance rating."""
    import json as _json

    from mathforge.agents import export_elegance_sample

    rows = export_elegance_sample(db_url=db_url, target=target, id_prefix=id_prefix)
    out.write_text(_json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]exported[/] {len(rows)} problem(s) to [bold]{out}[/]")
    console.print(
        "Rate each 0-5 (elegance_judge_v1 rubric), then write a JSON list of "
        "{id, elegance, reason} and run: [bold]mathforge elegance-apply ratings.json[/]"
    )


@app.command(name="elegance-apply")
def elegance_apply_cmd(
    ratings_file: Path = typer.Argument(..., help="JSON list of {id, elegance, reason}."),
    db_url: Optional[str] = typer.Option(None),
):
    """Apply elegance ratings (writes elegance-only Evaluations, evaluator=opus-4.8)."""
    import json as _json

    from mathforge.agents import apply_elegance_ratings

    ratings = _json.loads(ratings_file.read_text(encoding="utf-8"))
    counts = apply_elegance_ratings(ratings, db_url=db_url)
    console.print(f"[green]applied[/] {counts['applied']} elegance rating(s).")
    if counts["not_found"]:
        console.print(f"[yellow]not found:[/] {counts['not_found']}")


@app.command()
def review(
    status: str = typer.Option(
        "pending",
        help="Which queue to review: comma-list of pending|accepted|rejected|needs_edit, or 'all'.",
    ),
    id_prefix: Optional[str] = typer.Option(
        None, help="Only review problems whose id starts with this (e.g. opus-hard-, distill-)."
    ),
    source: Optional[str] = typer.Option(
        None, help="Only review this source (e.g. synthetic)."
    ),
    limit: Optional[int] = typer.Option(None, help="Max problems to line up this session."),
    raw: bool = typer.Option(False, "--raw", help="Show raw LaTeX instead of rendered."),
    db_url: Optional[str] = typer.Option(None),
):
    """Human check of problems: accept / reject / edit / postpone any queue.

    Defaults to the ``pending`` queue (freshly distilled candidates), but any
    batch can be revisited — e.g. ``review --status accepted --id-prefix opus-hard-``
    to audit an auto-accepted batch, using 'd' to postpone (send back to pending).
    """
    from mathforge.render import render_math
    from mathforge.schema import ReviewStatus

    valid = {s.value for s in ReviewStatus}
    wanted = valid if status == "all" else {s.strip() for s in status.split(",") if s.strip()}
    bad = wanted - valid
    if bad:
        raise typer.BadParameter(f"unknown status {sorted(bad)}; choose from {sorted(valid)} or 'all'")

    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        candidates = session.exec(select(Problem)).all()
        pending_ids = [
            p.id for p in candidates
            if (p.review_status.value if p.review_status else "") in wanted
            and (id_prefix is None or p.id.startswith(id_prefix))
            and (source is None or p.source.value == source)
        ]
    if limit is not None:
        pending_ids = pending_ids[:limit]

    if not pending_ids:
        console.print(
            f"[green]nothing to review[/] — no problems match "
            f"(status={status}"
            + (f", id_prefix={id_prefix}" if id_prefix else "")
            + (f", source={source}" if source else "") + ")."
        )
        return

    def show(t: str) -> str:
        return render_math(t, enabled=not raw)

    console.print(
        f"[bold]Review[/] {len(pending_ids)} problem(s)  [dim](status={status})[/]. "
        "a=accept, e=accept & edit answer, p=good but needs problem edit, "
        "r=reject, s=skip (no change), d=postpone (send to pending), q=quit."
    )
    accepted = rejected = flagged = postponed = 0
    for i, pid in enumerate(pending_ids, 1):
        with db.session_scope(db_url) as session:
            p = session.get(Problem, pid)
            sols = session.exec(select(Solution).where(Solution.problem_id == pid)).all()
            prov = p.provenance or {}
        verified_flag = "[green]verified[/]" if p.verified else "[red]UNVERIFIED[/]"
        console.rule(f"Candidate {i}/{len(pending_ids)}   {verified_flag}")
        console.print(show(p.statement))
        console.print(f"\n[dim]answer:[/] {p.answer}   [dim]difficulty:[/] {p.difficulty}   "
                      f"[dim]topic:[/] {p.topic}   [dim]repaired:[/] {prov.get('repaired')}")
        if not p.verified:
            console.print(
                f"[yellow]not machine-verified[/] — generated answer "
                f"{prov.get('generated_answer')}, solver answers "
                f"{prov.get('solver_answers')} (consensus {prov.get('solver_consensus')}). "
                "Judge correctness yourself."
            )
        qa = prov.get("agent_qa")
        if qa:
            wp = (qa.get("wellposedness") or {}).get("verdict")
            console.print(
                f"[cyan]agent QA[/] ({qa.get('solver_model')} x{qa.get('k')}): "
                f"consensus {qa.get('consensus')} vs stored {p.answer}, "
                f"agreement {qa.get('agreement')}, well-posed={wp}, "
                f"elegance={(qa.get('elegance') or {}).get('overall')}, "
                f"difficulty={(qa.get('difficulty') or {}).get('difficulty')}"
            )
            if qa.get("recommendation"):
                console.print(
                    f"  [magenta]recommendation:[/] {qa['recommendation']} — {qa.get('reason', '')}"
                )
        for s in sols:
            console.print("\n[dim]— model solution —[/]")
            console.print(show(s.text))
        action = None
        new_answer: Optional[str] = None
        edit_note: str = ""
        new_statement: Optional[str] = None
        while action is None:
            try:
                choice = input("  [a/e/p/r/s/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"
            if choice in ("q", "a", "r", "s", "d"):
                action = {"q": "quit", "a": "accept", "r": "reject",
                          "s": "skip", "d": "postpone"}[choice]
            elif choice == "e":
                try:
                    raw_ans = input("    new integer answer 0-999 (blank to cancel): ").strip()
                except (EOFError, KeyboardInterrupt):
                    raw_ans = ""
                if raw_ans == "":
                    continue  # back to the menu
                if raw_ans.isdigit() and 0 <= int(raw_ans) <= 999:
                    new_answer = str(int(raw_ans))
                    action = "accept"
                else:
                    console.print("    [red]enter an integer 0-999 (or blank to cancel)[/]")
            elif choice == "p":
                # Good candidate, but the problem statement needs fixing.
                try:
                    edit_note = input("    what needs fixing? (optional note): ").strip()
                    raw_stmt = input(
                        "    corrected statement on one line (blank = edit later): "
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    edit_note, raw_stmt = "", ""
                new_statement = raw_stmt or None
                action = "needs_edit"
            else:
                console.print("    [red]choose a / e / p / r / s / d / q[/]")

        if action == "quit":
            break
        if action == "skip":
            continue

        with db.session_scope(db_url) as session:
            p = session.get(Problem, pid)
            if action == "accept":
                p.review_status = ReviewStatus.ACCEPTED
                accepted += 1
                if new_answer is not None:
                    old = p.answer
                    p.answer = new_answer
                    p.verified = True  # human corrected + confirmed
                    prov2 = dict(p.provenance or {})
                    prov2["human_answer_override"] = {"old": old, "new": new_answer}
                    p.provenance = prov2
                    console.print(f"  [green]accepted[/] with answer {old} -> {new_answer}")
            elif action == "needs_edit":
                p.review_status = ReviewStatus.NEEDS_EDIT
                flagged += 1
                prov2 = dict(p.provenance or {})
                if edit_note:
                    prov2["edit_note"] = edit_note
                if new_statement is not None:
                    prov2["original_statement"] = p.statement
                    p.statement = new_statement
                    p.refresh_dedup_fields()
                    p.verified = None  # edited statement must be re-verified
                    prov2["statement_edited"] = True
                p.provenance = prov2
                console.print(
                    "  [yellow]flagged for problem edit[/]"
                    + (" (statement updated)" if new_statement else "")
                )
            elif action == "postpone":
                p.review_status = ReviewStatus.PENDING
                postponed += 1
                console.print("  [blue]postponed[/] — sent back to the pending queue")
            else:
                p.review_status = ReviewStatus.REJECTED
                rejected += 1
            session.add(p)
    console.print(
        f"\n[green]done[/] — accepted {accepted}, flagged-for-edit {flagged}, "
        f"rejected {rejected}, postponed {postponed}."
    )


@app.command()
def qa(
    k: int = typer.Option(4, help="Independent strong agents per problem."),
    solver_model: str = typer.Option("gpt-5.4", help="Strong solver/agent model."),
    judge_model: Optional[str] = typer.Option(None, help="Judge model (default: solver)."),
    statuses: str = typer.Option("pending,needs_edit", help="Comma-list of review statuses to QA."),
    backend: str = typer.Option("openai", help="'openai' (real API) or 'echo' (dry run)."),
    base_url: Optional[str] = typer.Option(None, help="OpenAI-compatible base URL."),
    api_key_env: str = typer.Option("OPENAI_API_KEY", help="Env var with the API key."),
    limit: Optional[int] = typer.Option(None, help="Max candidates to QA."),
    overwrite: bool = typer.Option(False, help="Re-QA problems already QA'd."),
    db_url: Optional[str] = typer.Option(None),
):
    """Spawn strong math agents to solve, verify, and quality-check candidates."""
    from mathforge.agents import run_agent_qa
    from mathforge.llm import LLMClient, make_openai_backend

    judge_model = judge_model or solver_model

    def make_client(model: str) -> LLMClient:
        be = None
        if backend == "openai":
            be = make_openai_backend(model, base_url=base_url, api_key_env=api_key_env)
        return LLMClient(model=model, backend=be, purpose="qa", db_url=db_url)

    status_tuple = tuple(s.strip() for s in statuses.split(",") if s.strip())
    console.print(
        f"[cyan]agent QA[/] k={k} · solver={solver_model} · judge={judge_model} · "
        f"statuses={status_tuple} · backend={backend}"
    )
    try:
        report = run_agent_qa(
            db_url=db_url,
            solver=make_client(solver_model),
            judge=make_client(judge_model),
            k=k,
            statuses=status_tuple,
            limit=limit,
            overwrite=overwrite,
        )
    except Exception as exc:
        console.print(f"[red]qa failed[/]: {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1)

    table = Table(title="Agent QA")
    table.add_column("metric", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("processed", str(report.processed))
    table.add_row("verified correct", str(report.verified_correct))
    table.add_row("answer mismatch", str(report.answer_mismatch))
    table.add_row("no consensus", str(report.no_consensus))
    table.add_row("ill-posed (reject)", str(report.ill_posed))
    table.add_row("skipped (already QA'd)", str(report.skipped))
    table.add_row("errors", str(report.errors))
    table.add_row("logged cost", f"${report.cost_usd:.4f}")
    console.print(table)
    if report.last_error:
        console.print(f"[yellow]last error:[/] {report.last_error}")
    for r in report.records:
        flag = "[green]OK[/]" if r["verified"] else "[red]FAIL[/]"
        wp = r["wellposed"]
        wp_str = f"[red]{wp}[/]" if wp == "reject" else str(wp)
        console.print(
            f"  {flag} [bold]{r['id']}[/] consensus={r['consensus']} "
            f"stored={r['stored_answer']} agree={r['agreement']} "
            f"wellposed={wp_str} difficulty={r['difficulty']} elegance={r['elegance']}"
        )
    if report.processed:
        console.print("\nnow human-review with: [bold]mathforge review[/]")


@app.command(name="solve-panel")
def solve_panel_cmd(
    limit: Optional[int] = typer.Option(50, help="Max problems this pass (None=all)."),
    split: str = typer.Option("train", help="Which split to solve (default: train)."),
    weak_model: str = typer.Option("qwen2.5-7b-instruct", help="Weak (~7B) solver model."),
    weak_attempts: int = typer.Option(8, help="Attempts for the weak solver."),
    strong_model: str = typer.Option("o3", help="Strong (frontier) solver model."),
    strong_attempts: int = typer.Option(4, help="Attempts for the strong solver."),
    overwrite: bool = typer.Option(False, help="Re-solve even if attempts are cached."),
    db_url: Optional[str] = typer.Option(None),
):
    """Run the weak+strong solver panel and store solve rates (cached).

    Attempts are cached per (problem, model, prompt, attempt) so a problem is
    never solved twice. Requires a real solver backend for meaningful rates.
    """
    from mathforge.schema import SolverRole
    from mathforge.solver import SolverConfig, run_solver_panel

    weak = SolverConfig(SolverRole.WEAK, weak_model, attempts=weak_attempts)
    strong = SolverConfig(SolverRole.STRONG, strong_model, attempts=strong_attempts)

    console.print(
        f"[cyan]solver panel[/] weak={weak_model} x{weak_attempts}, "
        f"strong={strong_model} x{strong_attempts}, split={split} ..."
    )
    report = run_solver_panel(
        db_url=db_url,
        weak_config=weak,
        strong_config=strong,
        limit=limit,
        split=split,
        overwrite=overwrite,
    )

    table = Table(title="Solver panel")
    table.add_column("metric", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("problems", str(report.problems))
    table.add_row("attempts run (API)", str(report.attempts_run))
    table.add_row("attempts cached (reused)", str(report.attempts_cached))
    table.add_row("possibly_memorized", str(report.possibly_memorized))
    table.add_row("logged solver cost", f"${report.cost_usd:.4f}")
    console.print(table)
    if report.by_classification:
        console.print(
            "classification: "
            + ", ".join(
                f"{k}={v}" for k, v in sorted(report.by_classification.items())
            )
        )


@app.command()
def evaluate(
    db_url: Optional[str] = typer.Option(None),
    evaluator: str = typer.Option("judge_v1", help="human | solver_panel | judge_v<N>."),
):
    """Score problems for difficulty and elegance, writing Evaluations."""
    db.init_db(db_url)
    _stub(
        "evaluate",
        f"score candidate Problems with evaluator={evaluator!r} (difficulty + elegance)",
    )


@app.command()
def loop(
    rounds: int = typer.Option(1, help="Generate/evaluate/select iterations."),
    keep: int = typer.Option(20, help="Top-K problems to keep per round."),
    db_url: Optional[str] = typer.Option(None),
):
    """Run the generate -> evaluate -> select loop to grow the dataset."""
    db.init_db(db_url)
    _stub(
        "loop",
        f"{rounds} round(s): generate, evaluate, keep top {keep} by elegance/difficulty",
    )


@app.command()
def export(
    out: Path = typer.Argument(Path("dataset.jsonl"), help="Output path."),
    fmt: str = typer.Option("jsonl", help="Export format: jsonl."),
    db_url: Optional[str] = typer.Option(None),
):
    """Export the curated problem/solution dataset for SLM training."""
    db.init_db(db_url)
    avail = _training_count(db_url)
    _stub(
        "export",
        f"write {avail} curated TRAIN Problems+Solutions (eval excluded) to {out} as {fmt!r}",
    )


@app.command(name="freeze-eval")
def freeze_eval_cmd(
    n_omni: int = typer.Option(150, help="Number of Omni-MATH problems to freeze."),
    threshold: float = typer.Option(4.0, help="Omni easy/hard tier threshold."),
    force: bool = typer.Option(False, help="Re-freeze even if a manifest exists."),
    db_url: Optional[str] = typer.Option(None),
):
    """Freeze the held-out eval split: 2024-2026 AIME I/II + 150 Omni-MATH.

    Ensures Omni-MATH is ingested, adds the AIME problems, selects 150 diverse
    Omni-MATH problems, marks the whole set eval+frozen, and writes the immutable
    manifest. Frozen problems are excluded from all upstream stages.
    """
    from mathforge.holdout import freeze_eval
    from mathforge.ingest import ingest_omni_math

    console.print("[cyan]ensuring Omni-MATH is ingested[/] ...")
    ingest_omni_math(threshold=threshold, db_url=db_url)

    console.print("[cyan]freezing eval split[/] ...")
    try:
        report = freeze_eval(n_omni=n_omni, db_url=db_url, force=force)
    except FileExistsError as exc:
        console.print(f"[red]refused[/]: {exc}")
        raise typer.Exit(code=1)

    table = Table(title="Frozen eval split")
    table.add_column("part", style="cyan")
    table.add_column("count", justify="right", style="green")
    table.add_row("AIME (2024-2026 I/II)", str(report.aime))
    table.add_row("Omni-MATH (stratified)", str(report.omni))
    table.add_row("total", str(report.total))
    console.print(table)
    console.print("Omni eval by topic: " + ", ".join(
        f"{k}={v}" for k, v in sorted(report.per_topic.items())
    ))
    console.print("Omni eval by band: " + ", ".join(
        f"{k}={v}" for k, v in sorted(report.per_band.items())
    ))
    console.print(f"manifest: [bold]{report.manifest_path}[/]")
    console.print(f"integrity sha256: [dim]{report.integrity_sha256}[/]")


@app.command(name="eval-verify")
def eval_verify_cmd(db_url: Optional[str] = typer.Option(None)):
    """Verify the DB eval split still matches the frozen manifest."""
    from mathforge.holdout import verify_manifest

    result = verify_manifest(db_url=db_url)
    status = "[green]OK[/]" if result["ok"] else "[red]MISMATCH[/]"
    console.print(f"eval integrity: {status} ({result['count']} problems)")
    console.print(f"  manifest:   {result['manifest_integrity']}")
    console.print(f"  recomputed: {result['recomputed_integrity']}")
    for issue in result["issues"][:20]:
        console.print(f"  [red]-[/] {issue}")
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command()
def report(
    json_out: Optional[Path] = typer.Option(
        None, "--json", help="Also write the report snapshot to this JSON path."
    ),
    db_url: Optional[str] = typer.Option(None),
):
    """One-page data report: counts by source, difficulty band, and topic."""
    import json as _json

    from mathforge.report import build_report

    rep = build_report(db_url)
    t = rep["totals"]
    console.print(
        f"[bold]MathForge dataset report[/]  "
        f"problems={t['problems']}  train={t.get('train', 0)}  "
        f"eval={t.get('eval', 0)}  frozen={t['frozen']}"
    )

    def render(title: str, key_label: str, data: list[dict]) -> None:
        tbl = Table(title=title)
        tbl.add_column(key_label, style="cyan")
        tbl.add_column("total", justify="right", style="green")
        tbl.add_column("train", justify="right")
        tbl.add_column("eval", justify="right", style="magenta")
        for r in data:
            tbl.add_row(r["key"], str(r["total"]), str(r.get("train", 0)), str(r.get("eval", 0)))
        console.print(tbl)

    render("By source", "source", rep["by_source"])
    render("By difficulty band", "band", rep["by_band"])
    render("By topic", "topic", rep["by_topic"])

    if json_out:
        json_out.write_text(_json.dumps(rep, indent=2), encoding="utf-8")
        console.print(f"wrote snapshot to [bold]{json_out}[/]")


@app.command()
def rank(
    source: Optional[str] = typer.Option("synthetic", help="Filter by source (or 'all')."),
    id_prefix: Optional[str] = typer.Option(None, help="e.g. opus-hc-, opus-batch-."),
    elegance_min: float = typer.Option(3.0, help="Quality bar: minimum elegance to pass the gate."),
    difficulty_min: float = typer.Option(0.0, help="Optional depth bar: minimum difficulty."),
    require_verified: bool = typer.Option(True, help="Only rank verified/correct problems."),
    trust_sources: bool = typer.Option(True, "--trust-sources/--no-trust-sources",
        help="Treat official contest sources (Omni-MATH etc.) as verified."),
    top: int = typer.Option(25, help="How many to show."),
    apply: bool = typer.Option(False, help="Set review_status: accept keepers, reject the rest."),
    db_url: Optional[str] = typer.Option(None),
):
    """Eval harness: rank by quality (elegance first, then difficulty, then crux).

    One deep, elegant problem outranks fifty mediocre ones. Ranking is
    lexicographic behind a hard correctness gate.
    """
    from mathforge.evalharness import TRUSTED_SOURCES, QualityWeights, rank_problems
    from mathforge.schema import ReviewStatus

    weights = QualityWeights(
        require_verified=require_verified,
        elegance_floor=elegance_min,
        difficulty_floor=difficulty_min,
        trusted_sources=TRUSTED_SOURCES if trust_sources else frozenset(),
    )
    src = None if source in (None, "all") else source
    ranked = rank_problems(db_url=db_url, weights=weights, source=src, id_prefix=id_prefix)
    keepers = [s for s in ranked if s.passes_gate]

    table = Table(title="Quality ranking (elegance ▸ difficulty ▸ crux economy)")
    table.add_column("#", justify="right", style="dim")
    table.add_column("grade", style="bold")
    table.add_column("id", style="cyan")
    table.add_column("eleg", justify="right", style="magenta")
    table.add_column("diff", justify="right")
    table.add_column("crux", justify="right")
    table.add_column("routine", justify="right")
    table.add_column("score", justify="right", style="green")
    table.add_column("topic")
    for i, s in enumerate(ranked[:top], 1):
        gate = "" if s.passes_gate else "  (gated out)"
        table.add_row(
            str(i), s.grade, s.problem_id + gate,
            "-" if s.elegance is None else f"{s.elegance:g}",
            "-" if s.difficulty is None else f"{s.difficulty:g}",
            "-" if s.crux_count is None else str(s.crux_count),
            "-" if s.routine_step_count is None else str(s.routine_step_count),
            f"{s.score:.1f}", s.topic or "-",
        )
    console.print(table)
    console.print(
        f"[green]{len(keepers)}[/] keepers (gate: verified"
        f"{'' if not require_verified else ''}, elegance ≥ {elegance_min}"
        f"{f', difficulty ≥ {difficulty_min}' if difficulty_min else ''}) "
        f"of {len(ranked)} ranked."
    )

    if apply:
        keep_ids = {s.problem_id for s in keepers}
        with db.session_scope(db_url) as session:
            for s in ranked:
                p = session.get(Problem, s.problem_id)
                p.review_status = ReviewStatus.ACCEPTED if s.problem_id in keep_ids else ReviewStatus.REJECTED
                session.add(p)
        console.print(
            f"[bold]applied[/]: accepted {len(keep_ids)}, rejected {len(ranked) - len(keep_ids)}."
        )


@app.command()
def show(
    status: Optional[str] = typer.Option(None, help="accepted | rejected | pending | needs_edit"),
    source: Optional[str] = typer.Option(None, help="e.g. synthetic, aime, other_competition"),
    id_prefix: Optional[str] = typer.Option(None, help="e.g. opus-batch-, distill-, omni-math-"),
    topic: Optional[str] = typer.Option(None, help="e.g. Algebra, Number Theory"),
    limit: int = typer.Option(20, help="Max problems to print."),
    full: bool = typer.Option(False, help="Also show the solution + QA details."),
    raw: bool = typer.Option(False, "--raw", help="Raw LaTeX instead of rendered Unicode."),
    db_url: Optional[str] = typer.Option(None),
):
    """Inspect problems in the bank (filter by status / source / id / topic)."""
    from mathforge.render import render_math

    db.init_db(db_url)

    def show_txt(t: str) -> str:
        return render_math(t, enabled=not raw)

    with db.session_scope(db_url) as session:
        problems = session.exec(select(Problem)).all()
        matched = []
        for p in problems:
            if status and (p.review_status.value if p.review_status else "") != status:
                continue
            if source and p.source.value != source:
                continue
            if id_prefix and not p.id.startswith(id_prefix):
                continue
            if topic and (p.topic or "") != topic:
                continue
            matched.append(p)

        total = len(matched)
        for p in matched[:limit]:
            prov = p.provenance or {}
            vflag = "verified" if p.verified else ("unverified" if p.verified is None else "FAILED")
            st = p.review_status.value if p.review_status else "-"
            console.rule(f"{p.id}  [{p.topic}]  {st}/{vflag}")
            console.print(show_txt(p.statement))
            console.print(
                f"[dim]answer:[/] {p.answer}   [dim]difficulty:[/] {p.difficulty}   "
                f"[dim]source:[/] {p.source.value}"
            )
            if full:
                sols = session.exec(select(Solution).where(Solution.problem_id == p.id)).all()
                for sol in sols:
                    console.print("[dim]— solution —[/]")
                    console.print(show_txt(sol.text))
                qa = prov.get("agent_qa")
                if qa:
                    console.print(
                        f"[cyan]QA[/]: {qa.get('recommendation')} — {qa.get('reason', '')}"
                    )
    console.print(
        f"\n[green]{min(total, limit)}[/] shown of [bold]{total}[/] match"
        + (f" (limit {limit})" if total > limit else "")
    )


@app.command()
def stats(db_url: Optional[str] = typer.Option(None)):
    """Show row counts and total logged LLM spend."""
    db.init_db(db_url)
    table = Table(title="MathForge database")
    table.add_column("entity", style="cyan")
    table.add_column("rows", justify="right", style="green")
    with db.session_scope(db_url) as session:
        for model in (Problem, Solution, Evaluation, Insight, LLMCall):
            count = len(session.exec(select(model)).all())
            table.add_row(model.__name__, str(count))
        problems = session.exec(select(Problem)).all()
        spend = sum(c.cost_usd for c in session.exec(select(LLMCall)).all())

    tiers: dict[str, int] = {}
    for p in problems:
        key = p.tier.value if p.tier is not None else "unrated"
        tiers[key] = tiers.get(key, 0) + 1

    console.print(table)
    if tiers:
        tier_table = Table(title="Problem sections (tier)")
        tier_table.add_column("tier", style="cyan")
        tier_table.add_column("rows", justify="right", style="green")
        for key in sorted(tiers):
            tier_table.add_row(key, str(tiers[key]))
        console.print(tier_table)

    splits = db.count_by_split(db_url)
    split_table = Table(title="Train / eval split")
    split_table.add_column("split", style="cyan")
    split_table.add_column("rows", justify="right", style="green")
    split_table.add_row("train", str(splits.get("train", 0)))
    split_table.add_row("eval (held out)", str(splits.get("eval", 0)))
    split_table.add_row("frozen", str(splits.get("frozen", 0)))
    console.print(split_table)
    console.print(f"total logged LLM spend: [bold]${spend:.4f}[/]")


if __name__ == "__main__":
    app()
