import json
import os
import sys
from pathlib import Path

import pandas as pd


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "bundled_web"
OUTPUT_DIR = APP_DIR / "verification" / "outputs"
REPORT_PATH = APP_DIR / "verification" / "feature_verification_report.json"
DEFAULT_SOURCE = Path(r"C:\Users\USER\Downloads\dirty_financial_transactions.csv")


def load_web_app():
    sys.path.insert(0, str(WEB_DIR))
    os.chdir(WEB_DIR)
    import app as webapp

    return webapp


def changed_examples(webapp, before_df, after_df, limit=5):
    before_rows, after_rows = webapp.changed_dataframe_previews(before_df, after_df, limit=limit)
    examples = []
    for index, (before, after) in enumerate(zip(before_rows, after_rows), start=1):
        changes = {
            key: {"before": before.get(key, ""), "after": after.get(key, "")}
            for key in after
            if str(before.get(key, "")) != str(after.get(key, ""))
        }
        examples.append({"row": index, "changes": changes})
    return examples


def assert_condition(assertions, name, passed, detail):
    assertions.append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        raise AssertionError(f"{name}: {detail}")


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        raise FileNotFoundError(f"Source CSV not found: {source}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    webapp = load_web_app()

    source_df = pd.read_csv(source)
    source_stats = webapp.dataframe_stats(source_df)
    report = {
        "source_csv": str(source),
        "source_stats": source_stats,
        "checks": {}
    }

    cleaning_log = webapp.RunLogger("verify-cleaning")
    clean_before, clean_after = webapp.clean_dataframe(
        str(source),
        str(OUTPUT_DIR / "cleaned_full.csv"),
        cleaning_log
    )
    cleaning_assertions = []
    clean_stats = webapp.dataframe_stats(clean_after)
    assert_condition(cleaning_assertions, "cleaning_removes_missing_values", clean_stats["missing"] == 0, clean_stats)
    assert_condition(cleaning_assertions, "cleaning_removes_duplicates", clean_stats["duplicates"] == 0, clean_stats)
    assert_condition(cleaning_assertions, "cleaning_preserves_columns", list(clean_before.columns) == list(clean_after.columns), list(clean_after.columns))
    report["checks"]["cleaning"] = {
        "before": webapp.dataframe_stats(clean_before),
        "after": clean_stats,
        "assertions": cleaning_assertions,
        "changed_examples": changed_examples(webapp, clean_before, clean_after),
        "output_csv": str(OUTPUT_DIR / "cleaned_full.csv")
    }

    repair_log = webapp.RunLogger("verify-repair")
    repair_engine = webapp.LocalRepairEngine(model_id=os.environ.get("CRUX_OLLAMA_MODEL", "llama3"))
    repair_after = repair_engine.run_repair_pipeline(
        str(source),
        str(OUTPUT_DIR / "repaired_full.csv"),
        logger=repair_log
    )
    repair_assertions = []
    repair_stats = webapp.dataframe_stats(repair_after)
    assert_condition(repair_assertions, "repair_removes_missing_values", repair_stats["missing"] == 0, repair_stats)
    assert_condition(repair_assertions, "repair_removes_duplicates", repair_stats["duplicates"] == 0, repair_stats)
    assert_condition(repair_assertions, "repair_fixes_negative_amount_like_values", repair_stats["negative_amounts"] == 0, repair_stats)
    assert_condition(repair_assertions, "repair_preserves_schema", list(source_df.columns) == list(repair_after.columns), list(repair_after.columns))
    report["checks"]["repair"] = {
        "before": source_stats,
        "after": repair_stats,
        "assertions": repair_assertions,
        "changed_examples": changed_examples(webapp, source_df, repair_after),
        "llm_category_repair_applicable": {"merchant_name", "merchant_category"}.issubset(set(source_df.columns)),
        "output_csv": str(OUTPUT_DIR / "repaired_full.csv")
    }

    subset_size = min(360, len(source_df))
    generation_input = OUTPUT_DIR / "generation_input_sample.csv"
    source_df.head(subset_size).to_csv(generation_input, index=False)

    generation_clean_log = webapp.RunLogger("verify-generation-cleaning")
    _, generation_cleaned = webapp.clean_dataframe(
        str(generation_input),
        str(OUTPUT_DIR / "generation_cleaned.csv"),
        generation_clean_log
    )
    generation_repair_log = webapp.RunLogger("verify-generation-repair")
    generation_repaired = repair_engine.run_repair_pipeline(
        str(OUTPUT_DIR / "generation_cleaned.csv"),
        str(OUTPUT_DIR / "generation_repaired.csv"),
        logger=generation_repair_log
    )
    generator = webapp.LocalGenerationEngine()
    discrete_cols = webapp.infer_discrete_columns(generation_repaired)
    generation_log = webapp.RunLogger("verify-generation")
    training = generator.train_generator(str(OUTPUT_DIR / "generation_repaired.csv"), discrete_cols, logger=generation_log)
    synthetic = generator.generate_synthetic_data(
        num_rows=len(generation_repaired),
        output_csv=str(OUTPUT_DIR / "synthetic_sample.csv"),
        logger=generation_log
    )
    evaluation = webapp.evaluation_engine.evaluate_synthetic_data(
        str(OUTPUT_DIR / "generation_repaired.csv"),
        str(OUTPUT_DIR / "synthetic_sample.csv")
    )
    quality = webapp.generation_quality_report(generation_repaired, synthetic)
    generation_assertions = []
    assert_condition(generation_assertions, "generation_trains_on_repaired_rows", training["training_rows"] > 0, training)
    assert_condition(generation_assertions, "generation_preserves_schema", quality["same_columns"], quality)
    assert_condition(generation_assertions, "generation_preserves_row_count", quality["synthetic_rows"] == quality["source_rows"], quality)
    assert_condition(generation_assertions, "generation_has_no_missing_values", quality["missing_values"] == 0, quality)
    assert_condition(generation_assertions, "generation_has_no_negative_amount_like_values", quality["negative_amounts"] == 0, quality)
    assert_condition(generation_assertions, "generation_not_exact_copy", quality["sample_row_overlap_pct"] < 90, quality)
    report["checks"]["generation"] = {
        "source_sample_rows": subset_size,
        "training": training,
        "quality": quality,
        "evaluation": evaluation,
        "assertions": generation_assertions,
        "output_csv": str(OUTPUT_DIR / "synthetic_sample.csv")
    }

    chatbot_query = (
        "Generate 120 rows from uploaded CSV. Focus: clean financial transaction rows "
        "with no blanks or negative amount-like values."
    )
    chatbot_requested_rows = webapp.parse_generation_row_count(chatbot_query)
    chatbot_log = webapp.RunLogger("verify-generation-chatbot")
    chatbot_synthetic = generator.generate_synthetic_data(
        num_rows=chatbot_requested_rows,
        output_csv=str(OUTPUT_DIR / "synthetic_chatbot_plan.csv"),
        logger=chatbot_log
    )
    chatbot_quality = webapp.generation_quality_report(generation_repaired, chatbot_synthetic)
    chatbot_assertions = []
    assert_condition(chatbot_assertions, "chatbot_query_extracts_requested_rows", chatbot_requested_rows == 120, chatbot_requested_rows)
    assert_condition(chatbot_assertions, "chatbot_generation_preserves_schema", chatbot_quality["same_columns"], chatbot_quality)
    assert_condition(chatbot_assertions, "chatbot_generation_uses_requested_row_count", chatbot_quality["synthetic_rows"] == 120, chatbot_quality)
    assert_condition(chatbot_assertions, "chatbot_generation_has_no_missing_values", chatbot_quality["missing_values"] == 0, chatbot_quality)
    assert_condition(chatbot_assertions, "chatbot_generation_has_no_negative_amount_like_values", chatbot_quality["negative_amounts"] == 0, chatbot_quality)
    report["checks"]["generation_chatbot_flow"] = {
        "query": chatbot_query,
        "requested_rows": chatbot_requested_rows,
        "quality": chatbot_quality,
        "assertions": chatbot_assertions,
        "output_csv": str(OUTPUT_DIR / "synthetic_chatbot_plan.csv")
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CRUX_FEATURE_VERIFICATION_OK")
    print(json.dumps({
        "source_rows": source_stats["rows"],
        "cleaning_after": clean_stats,
        "repair_after": repair_stats,
        "generation_quality": quality,
        "generation_chatbot_quality": chatbot_quality,
        "report": str(REPORT_PATH)
    }, indent=2))


if __name__ == "__main__":
    main()
