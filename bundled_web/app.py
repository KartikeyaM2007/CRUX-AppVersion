import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import pandas as pd
import numpy as np

from repair_engine import LocalRepairEngine
from generation_engine import LocalGenerationEngine
from evaluation_engine import LocalEvaluationEngine
from mock_data_generator import generate_mock_financial_data

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

app = FastAPI(title="Crux")

# Create necessary directories
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("data", exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize engines lazily to save startup time
repair_engine = None
generation_engine = None
evaluation_engine = LocalEvaluationEngine()
generation_request = {
    "query": "No generation request entered yet.",
    "interpretation": "The generator will infer schema from the uploaded or sample CSV.",
    "rows": None
}

REPAIR_SAMPLES = {
    "missing-payments": {
        "name": "Missing payments and labels",
        "path": "data/samples/repair_missing_payments.csv",
        "description": "Missing statuses, payment method variants, invalid date, partial product names, negative price and quantity.",
        "expected": "Repair should normalize payment methods, fill status with Needs Review, repair dates/IDs, fix product names, and remove negative numeric values."
    },
    "negative-prices": {
        "name": "Negative prices and quantities",
        "path": "data/samples/repair_negative_prices.csv",
        "description": "Negative prices, negative quantities, zero quantity, missing status, and mixed payment labels.",
        "expected": "Repair should convert numeric anomalies to valid positive values, set zero quantity to one, and normalize payment/status fields."
    },
    "dates-ids": {
        "name": "Broken dates and IDs",
        "path": "data/samples/repair_dates_ids.csv",
        "description": "Missing transaction/customer IDs, impossible dates, free-text dates, partial product names, and a negative price.",
        "expected": "Repair should generate placeholder IDs, replace invalid dates, normalize products, and fix negative price values."
    },
    "duplicates-mixed": {
        "name": "Duplicates and mixed errors",
        "path": "data/samples/repair_duplicates_mixed.csv",
        "description": "Duplicate transaction rows, broken date, missing customer ID, partial product labels, and numeric anomalies.",
        "expected": "Repair should remove duplicates, fill IDs, normalize product names, repair dates, and clean negative values."
    }
}

class RunLogger:
    def __init__(self, scope):
        self.scope = scope
        self.entries = []

    def __call__(self, message, level="info"):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "scope": self.scope,
            "level": level,
            "message": str(message)
        }
        self.entries.append(entry)
        print(f"[{entry['time']}] [{level.upper()}] {message}")

def get_repair_engine():
    global repair_engine
    if repair_engine is None:
        model_id = os.environ.get("CRUX_OLLAMA_MODEL", "llama3")
        print(f"Initializing Repair Engine LLM with {model_id}...")
        repair_engine = LocalRepairEngine(model_id=model_id)
    return repair_engine

def get_generation_engine():
    global generation_engine
    print("Initializing CTGAN...")
    generation_engine = LocalGenerationEngine()
    return generation_engine

def ensure_raw_data():
    raw_csv = "data/raw_transactions.csv"
    if not os.path.exists(raw_csv):
        df = generate_mock_financial_data(num_rows=1000)
        df.to_csv(raw_csv, index=False)
    return raw_csv

def safe_value(value):
    if pd.isna(value):
        return ""
    if hasattr(value, "item"):
        return value.item()
    return value

def dataframe_preview(df, limit=6):
    preview = []
    for _, row in df.head(limit).iterrows():
        preview.append({col: safe_value(row[col]) for col in df.columns})
    return preview

def changed_dataframe_previews(before_df, after_df, limit=6):
    before_records = []
    after_records = []
    shared_columns = [col for col in after_df.columns if col in before_df.columns]
    max_rows = min(len(before_df), len(after_df))

    for idx in range(max_rows):
        before_row = before_df.iloc[idx]
        after_row = after_df.iloc[idx]
        changed = any(str(safe_value(before_row[col])) != str(safe_value(after_row[col])) for col in shared_columns)
        if changed:
            before_records.append({col: safe_value(before_row[col]) for col in before_df.columns})
            after_records.append({col: safe_value(after_row[col]) for col in after_df.columns})
        if len(after_records) >= limit:
            break

    if len(after_records) < limit:
        used = len(after_records)
        for idx in range(max_rows):
            before_row = before_df.iloc[idx]
            after_row = after_df.iloc[idx]
            before_item = {col: safe_value(before_row[col]) for col in before_df.columns}
            after_item = {col: safe_value(after_row[col]) for col in after_df.columns}
            if before_item in before_records and after_item in after_records:
                continue
            before_records.append(before_item)
            after_records.append(after_item)
            used += 1
            if used >= limit:
                break

    return before_records, after_records

def dataframe_stats(df):
    missing_by_column = df.isnull().sum().sort_values(ascending=False)
    stats = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "missing": int(df.isnull().sum().sum()),
        "duplicates": int(df.duplicated().sum()),
        "missing_by_column": {
            col: int(count) for col, count in missing_by_column.items() if int(count) > 0
        }
    }
    negative_count = 0
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in df.columns:
        if col in numeric_cols:
            numeric = pd.to_numeric(df[col], errors="coerce")
        elif any(token in col.lower() for token in ["amount", "price", "cost", "total", "quantity", "balance"]):
            numeric, _ = maybe_numeric_series(df[col])
        else:
            numeric = None
        if numeric is not None:
            negative_count += int((numeric < 0).sum())
    stats["negative_amounts"] = negative_count
    amount_like_cols = [
        col for col in numeric_cols
        if any(token in col.lower() for token in ["amount", "price", "cost", "total", "quantity"])
    ]
    if amount_like_cols:
        stats["avg_amount"] = round(float(df[amount_like_cols[0]].mean()), 2)
    category_cols = [col for col in df.columns if "category" in col.lower() or "status" in col.lower()]
    if category_cols:
        stats["category_nulls"] = int(df[category_cols].isnull().sum().sum())
    return stats

def dataset_intelligence(df, feature="generation", query="", sample=None):
    stats = dataframe_stats(df)
    columns = list(map(str, df.columns))
    column_preview = ", ".join(columns[:8])
    missing_cols = stats.get("missing_by_column", {})
    missing_text = ", ".join(f"{col} ({count})" for col, count in list(missing_cols.items())[:4]) or "no missing columns detected"
    duplicate_text = f"{stats['duplicates']} duplicate rows"
    negative_text = f"{stats.get('negative_amounts', 0)} negative numeric values"

    labels = {
        "generation": {
            "query": query or "Generate synthetic data from the active CSV.",
            "problem": "Create new private rows while preserving the uploaded table shape.",
            "expected": "A synthetic CSV with regenerated IDs/dates, calibrated numeric distributions, and local fidelity checks."
        },
        "repair": {
            "query": query or "Repair broken values in the active CSV.",
            "problem": f"Repair {missing_text}, {duplicate_text}, and {negative_text} without uploading data.",
            "expected": "A repaired CSV with normalized labels, valid dates/IDs, positive amount-like values, and fewer unresolved blanks."
        },
        "cleaning": {
            "query": query or "Clean the active CSV before repair or generation.",
            "problem": f"Clean whitespace, parse dates/currency, fill blanks, and remove {duplicate_text}.",
            "expected": "A cleaner CSV ready for repair/generation, with trimmed strings, parsed values, and duplicate rows removed."
        }
    }
    picked = labels.get(feature, labels["generation"])
    if sample:
        picked = {
            **picked,
            "query": f"Use sample: {sample.get('name', 'sample CSV')}",
            "problem": sample.get("description", picked["problem"]),
            "expected": sample.get("expected", picked["expected"])
        }
    return {
        **picked,
        "understood": f"Detected {stats['rows']} rows, {stats['columns']} columns ({column_preview}). Missing: {stats['missing']}. Duplicates: {stats['duplicates']}. Negative amount-like values: {stats.get('negative_amounts', 0)}.",
        "stats": stats
    }

def build_response(message, before_df, after_df, logs, download_url, extra=None):
    before_sample, after_sample = changed_dataframe_previews(before_df, after_df)
    response = {
        "status": "success",
        "message": message,
        "before": dataframe_stats(before_df),
        "after": dataframe_stats(after_df),
        "before_sample": before_sample,
        "after_sample": after_sample,
        "columns": list(after_df.columns),
        "logs": logs.entries,
        "download_url": download_url,
        "intel": dataset_intelligence(before_df)
    }
    if extra:
        response.update(extra)
    return response

def is_date_column(col):
    return "date" in col.lower() or "time" in col.lower()

def is_currency_column(col):
    tokens = ["price", "amount", "cost", "total", "balance", "revenue", "payment"]
    return any(token in col.lower() for token in tokens)

def is_id_column(col):
    return col.lower().endswith("_id") or col.lower() == "id" or "transaction_id" in col.lower() or "customer_id" in col.lower()

def maybe_numeric_series(series):
    cleaned = series.astype("string").str.replace(r"[$,]", "", regex=True).str.strip()
    numeric = pd.to_numeric(cleaned, errors="coerce")
    non_null = series.notna().sum()
    if non_null == 0:
        return None, 0
    return numeric, float(numeric.notna().sum() / non_null)

def generation_quality_report(source_df, synthetic_df):
    shared_columns = [col for col in source_df.columns if col in synthetic_df.columns]
    id_or_date_cols = [col for col in shared_columns if is_id_column(str(col)) or is_date_column(str(col))]
    compare_cols = [col for col in shared_columns if col not in id_or_date_cols]
    source_sample = source_df[compare_cols].head(2000).astype("string").fillna("").agg("|".join, axis=1) if compare_cols else pd.Series(dtype="string")
    synthetic_sample = synthetic_df[compare_cols].head(2000).astype("string").fillna("").agg("|".join, axis=1) if compare_cols else pd.Series(dtype="string")
    overlap = 0
    if len(synthetic_sample) and len(source_sample):
        overlap = int(synthetic_sample.isin(set(source_sample)).sum())

    id_checks = {}
    for col in id_or_date_cols:
        if is_id_column(str(col)) and col in synthetic_df.columns:
            values = synthetic_df[col].astype("string").head(25)
            id_checks[col] = bool(values.str.contains("_SYN_", regex=False).all()) if len(values) else False

    numeric_deltas = []
    for col in synthetic_df.select_dtypes(include=[np.number]).columns:
        if col not in source_df.columns:
            continue
        source_mean = pd.to_numeric(source_df[col], errors="coerce").mean()
        synthetic_mean = pd.to_numeric(synthetic_df[col], errors="coerce").mean()
        if pd.isna(source_mean) or pd.isna(synthetic_mean):
            continue
        denom = abs(source_mean) if abs(source_mean) > 1e-9 else 1
        numeric_deltas.append({
            "column": str(col),
            "source_mean": round(float(source_mean), 4),
            "synthetic_mean": round(float(synthetic_mean), 4),
            "mean_delta_pct": round(float(abs(synthetic_mean - source_mean) / denom * 100), 2)
        })

    return {
        "same_columns": list(source_df.columns) == list(synthetic_df.columns),
        "source_rows": int(len(source_df)),
        "synthetic_rows": int(len(synthetic_df)),
        "sample_row_overlap_pct": round(float(overlap / max(1, len(synthetic_sample)) * 100), 2),
        "id_columns_regenerated": id_checks,
        "missing_values": int(synthetic_df.isnull().sum().sum()),
        "negative_amounts": dataframe_stats(synthetic_df).get("negative_amounts", 0),
        "numeric_mean_deltas": numeric_deltas[:6]
    }

def clean_dataframe(input_csv, output_csv, logger=None):
    logger = logger or RunLogger("cleaning")
    logger("Data cleaning started.")
    logger(f"Loading source CSV: {input_csv}")
    df = pd.read_csv(input_csv)
    before_df = df.copy()
    logger(f"Analyzing structure: {len(df)} rows, {len(df.columns)} columns.")
    logger(f"Columns detected: {', '.join(df.columns)}")

    for idx, row in df.head(200).iterrows():
        row_id = row.get("transaction_id", row.get("Transaction_ID", idx + 1))
        logger(f"Analyzing row {idx + 1}: {row_id}")
    if len(df) > 200:
        logger(f"Skipped detailed row logging for remaining {len(df) - 200} rows to keep the UI responsive.")

    duplicate_count = int(df.duplicated().sum())
    logger(f"Duplicate scan complete: {duplicate_count} duplicate rows found.")
    df = df.drop_duplicates()

    for col in df.select_dtypes(include=["object"]).columns:
        logger(f"Normalizing text column '{col}'.")
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})

    for col in list(df.columns):
        if is_currency_column(col) and df[col].dtype == "object" or str(df[col].dtype).startswith("string"):
            numeric, ratio = maybe_numeric_series(df[col])
            if numeric is not None and ratio > 0.55:
                logger(f"Parsing numeric/currency column '{col}' ({ratio:.0%} numeric-like).")
                df[col] = numeric

    for col in df.columns:
        if is_date_column(col):
            logger(f"Parsing date column '{col}' into YYYY-MM-DD format.")
            parsed = pd.to_datetime(df[col], errors="coerce")
            fallback = parsed.dropna().mode()
            fallback_value = fallback.iloc[0] if not fallback.empty else pd.Timestamp.today().normalize()
            invalid_count = int(parsed.isna().sum())
            if invalid_count:
                logger(f"Date repair for '{col}': {invalid_count} missing/invalid values filled with {fallback_value.date()}.")
            parsed = parsed.fillna(fallback_value)
            df[col] = parsed.dt.strftime("%Y-%m-%d")

    for col in df.columns:
        if is_id_column(col) and df[col].isnull().any():
            missing_ids = int(df[col].isnull().sum())
            logger(f"ID repair scan for '{col}': {missing_ids} missing values.")
            prefix = "ID"
            if "transaction" in col.lower():
                prefix = "TXN"
            elif "customer" in col.lower():
                prefix = "CUST"
            values = []
            for idx, value in df[col].items():
                values.append(f"{prefix}_UNKNOWN_{idx + 1}" if pd.isna(value) else value)
            df[col] = values

    for col in df.select_dtypes(include=["object", "string"]).columns:
        if df[col].isnull().any():
            logger(f"Filling unresolved text blanks in '{col}' with Needs Review.")
            df[col] = df[col].fillna("Needs Review")

    for col in df.select_dtypes(include=["number"]).columns:
        if df[col].isnull().any():
            median = df[col].median()
            if pd.isna(median):
                median = 0
            logger(f"Filling numeric blanks in '{col}' with median {median}.")
            df[col] = df[col].fillna(median)

    df.to_csv(output_csv, index=False)
    logger(f"Cleaned dataset saved to {output_csv}")
    logger("Data cleaning completed.")
    return before_df, df

def infer_discrete_columns(df):
    discrete_cols = []
    for col in df.columns:
        lowered = col.lower()
        if df[col].dtype == "object" or str(df[col].dtype).startswith("string"):
            discrete_cols.append(col)
        elif is_id_column(col) or "status" in lowered or "method" in lowered or "category" in lowered:
            discrete_cols.append(col)
        elif df[col].nunique(dropna=True) <= min(50, max(10, len(df) * 0.02)):
            discrete_cols.append(col)
    return [str(col) for col in discrete_cols]

def interpret_generation_query(query, df=None):
    text = (query or "").strip()
    if not text:
        text = "Generate synthetic data matching the uploaded dataset."
    lower = text.lower()
    requested_rows = parse_generation_row_count(text)
    goals = []
    if "fraud" in lower:
        goals.append("preserve fraud-like rare events and class imbalance")
    if "financial" in lower or "transaction" in lower:
        goals.append("create transaction-style tabular records")
    if "customer" in lower:
        goals.append("keep customer-level identifiers synthetic")
    if "clean" in lower:
        goals.append("use cleaned and repaired rows before training")
    if not goals:
        goals.append("mirror column distributions from the current CSV")
    schema = ""
    if df is not None:
        schema = f"Detected {len(df)} rows and {len(df.columns)} columns: {', '.join(map(str, df.columns[:8]))}."
    row_text = f" Requested output: {requested_rows} rows." if requested_rows else ""
    return f"{schema} Interpreted request: {', '.join(goals)}.{row_text}"

def parse_generation_row_count(query, default=None, max_rows=100000):
    text = (query or "").lower().replace(",", "")
    patterns = [
        r"(\d{1,7})\s*(k|thousand)?\s*(?:rows|records|transactions)",
        r"(?:generate|create|make)\s+(\d{1,7})\s*(k|thousand)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = int(match.group(1))
            if match.group(2) in {"k", "thousand"}:
                value *= 1000
            return max(1, min(value, max_rows))
    return default

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/favicon.ico")
async def favicon():
    icon_path = "static/assets/crux-logo.png"
    if os.path.exists(icon_path):
        return FileResponse(path=icon_path, media_type="image/png")
    return FileResponse(path="static/assets/data-stack.png", media_type="image/png")

@app.post("/api/generate-mock")
async def api_generate_mock():
    # Helper endpoint to generate a mock CSV if the user doesn't have one
    logs = RunLogger("mock")
    logs("Sample test started.")
    logs("Creating 1000 dirty financial transaction rows.")
    csv_path = "data/raw_transactions.csv"
    df = generate_mock_financial_data(num_rows=1000)
    for idx, row in df.iterrows():
        logs(f"Creating row {idx + 1}: {row['transaction_id']} / {row['merchant_name']}")
    df.to_csv(csv_path, index=False)
    logs(f"Mock data generated at {csv_path}")
    return {
        "status": "success",
        "message": "Mock data generated.",
        "path": csv_path,
        "after": dataframe_stats(df),
        "after_sample": dataframe_preview(df),
        "columns": list(df.columns),
        "logs": logs.entries,
        "intel": dataset_intelligence(df, "generation", "Use mock dirty financial data.")
    }

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    logs = RunLogger("upload")
    logs(f"Upload started: {file.filename}")
    csv_path = "data/raw_transactions.csv"
    with open(csv_path, "wb") as buffer:
        buffer.write(await file.read())
    df = pd.read_csv(csv_path)
    logs(f"File saved to {csv_path}")
    logs(f"Loaded uploaded CSV: {len(df)} rows, {len(df.columns)} columns.")
    return {
        "status": "success",
        "message": "File uploaded successfully.",
        "path": csv_path,
        "after": dataframe_stats(df),
        "after_sample": dataframe_preview(df),
        "columns": list(df.columns),
        "logs": logs.entries,
        "intel": {
            "generation": dataset_intelligence(df, "generation", f"Generate synthetic data from uploaded file {file.filename}."),
            "repair": dataset_intelligence(df, "repair", f"Repair uploaded file {file.filename}."),
            "cleaning": dataset_intelligence(df, "cleaning", f"Clean uploaded file {file.filename}.")
        }
    }

@app.post("/api/use-repair-sample/{sample_id}")
async def api_use_repair_sample(sample_id: str):
    logs = RunLogger("repair")
    sample = REPAIR_SAMPLES.get(sample_id)
    if not sample:
        logs(f"Unknown repair sample: {sample_id}", "error")
        return {"status": "error", "message": "Unknown repair sample.", "logs": logs.entries}
    source = Path(sample["path"])
    if not source.exists():
        logs(f"Repair sample file missing: {source}", "error")
        return {"status": "error", "message": "Repair sample file missing.", "logs": logs.entries}
    csv_path = Path("data/raw_transactions.csv")
    shutil.copyfile(source, csv_path)
    df = pd.read_csv(csv_path)
    logs(f"Loaded repair sample: {sample['name']}")
    logs(f"Sample issue profile: {sample['description']}")
    logs(f"Expected after repair: {sample['expected']}")
    return {
        "status": "success",
        "message": f"Loaded repair sample: {sample['name']}",
        "sample": sample,
        "path": str(csv_path),
        "after": dataframe_stats(df),
        "after_sample": dataframe_preview(df),
        "columns": list(df.columns),
        "logs": logs.entries,
        "intel": dataset_intelligence(df, "repair", sample=sample)
    }

@app.post("/api/generation-query")
async def api_generation_query(payload: dict):
    query = str(payload.get("query", "")).strip()
    raw_csv = ensure_raw_data()
    df = pd.read_csv(raw_csv)
    generation_request["query"] = query or "Generate synthetic data matching the uploaded dataset."
    generation_request["rows"] = parse_generation_row_count(generation_request["query"])
    generation_request["interpretation"] = interpret_generation_query(generation_request["query"], df)
    return {
        "status": "success",
        "query": generation_request["query"],
        "interpretation": generation_request["interpretation"],
        "rows": generation_request["rows"],
        "intel": dataset_intelligence(df, "generation", generation_request["query"])
    }

@app.post("/api/run-cleaning")
async def api_run_cleaning():
    logs = RunLogger("cleaning")
    try:
        raw_csv = ensure_raw_data()
        cleaned_csv = "data/cleaned_transactions.csv"
        before_df, after_df = clean_dataframe(raw_csv, cleaned_csv, logs)
        return build_response(
            "Dataset cleaned successfully.",
            before_df,
            after_df,
            logs,
            "/api/download-cleaned",
            {"intel": dataset_intelligence(before_df, "cleaning")}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        logs(str(e), "error")
        return {"status": "error", "message": str(e), "logs": logs.entries}

@app.post("/api/run-repair")
async def api_run_repair():
    logs = RunLogger("repair")
    try:
        raw_csv = ensure_raw_data()
        repaired_csv = "data/repaired_transactions.csv"
        before_df = pd.read_csv(raw_csv)
        re = get_repair_engine()
        repaired = re.run_repair_pipeline(raw_csv, repaired_csv, logger=logs)
        return build_response(
            f"Dataset repaired with local {re.model_id} via Ollama.",
            before_df,
            repaired,
            logs,
            "/api/download-repaired",
            {
                "rows": int(len(repaired)),
                "remaining_nulls": int(repaired.isnull().sum().sum()),
                "intel": dataset_intelligence(before_df, "repair")
            }
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        logs(str(e), "error")
        return {"status": "error", "message": str(e), "logs": logs.entries}

@app.post("/api/run-generation")
async def api_run_generation():
    logs = RunLogger("generation")
    try:
        raw_csv = ensure_raw_data()
        cleaned_csv = "data/cleaned_transactions.csv"
        repaired_csv = "data/repaired_transactions.csv"
        synthetic_csv = "data/synthetic_transactions.csv"

        logs("Preparing source data for generation.")
        before_clean_df, cleaned_df = clean_dataframe(raw_csv, cleaned_csv, logs)
        logs("Running repair pass before CTGAN training.")
        re = get_repair_engine()
        re.run_repair_pipeline(cleaned_csv, repaired_csv, logger=logs)

        ge = get_generation_engine()
        df_repaired = pd.read_csv(repaired_csv)
        df_repaired.columns = [str(col) for col in df_repaired.columns]
        df_repaired.to_csv(repaired_csv, index=False)
        before_df = df_repaired.copy()
        discrete_cols = infer_discrete_columns(df_repaired)
        logs(f"Discrete columns selected: {', '.join(discrete_cols)}")
        logs(f"User generation query: {generation_request['query']}")
        logs(f"Model interpretation: {generation_request['interpretation']}")
        training_info = ge.train_generator(repaired_csv, discrete_cols, logger=logs)
        requested_rows = generation_request.get("rows")
        num_rows_to_generate = int(requested_rows or (len(df_repaired) if len(df_repaired) > 0 else 1000))
        logs(f"Requested synthetic row count: {num_rows_to_generate}")
        synthetic_df = ge.generate_synthetic_data(
            num_rows=num_rows_to_generate,
            output_csv=synthetic_csv,
            logger=logs
        )
        logs("Running fidelity evaluation.")
        results = evaluation_engine.evaluate_synthetic_data(repaired_csv, synthetic_csv)
        quality = generation_quality_report(before_df, synthetic_df)
        logs(f"Generation quality check: schema_match={quality['same_columns']}, row_overlap={quality['sample_row_overlap_pct']}%, missing={quality['missing_values']}.")
        logs("Generation and evaluation completed.")

        return build_response(
            "Synthetic dataset generated.",
            before_df,
            synthetic_df,
            logs,
            "/api/download-synthetic",
            {
                "rows": int(num_rows_to_generate),
                "evaluation": results,
                "training": training_info,
                "quality": quality,
                "intel": dataset_intelligence(before_df, "generation", generation_request["query"])
            }
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        logs(str(e), "error")
        return {"status": "error", "message": str(e), "logs": logs.entries}

@app.post("/api/run-pipeline")
async def run_pipeline():
    """
    Synchronous endpoint that runs the entire ML pipeline.
    In a production app, this would be asynchronous/background-task based,
    but for local MVP, blocking is acceptable while the UI shows a loading spinner.
    """
    try:
        raw_csv = ensure_raw_data()
        repaired_csv = "data/repaired_transactions.csv"
        synthetic_csv = "data/synthetic_transactions.csv"

        print("--- 1. Running Repair Engine ---")
        re = get_repair_engine()
        re.run_repair_pipeline(raw_csv, repaired_csv)

        print("--- 2. Running Generation Engine ---")
        ge = get_generation_engine()
        
        df_repaired = pd.read_csv(repaired_csv)
        expected_discrete_cols = ['transaction_id', 'date', 'user_id', 'merchant_name', 'merchant_category', 'is_fraud']
        discrete_cols = [col for col in expected_discrete_cols if col in df_repaired.columns]
        
        ge.train_generator(repaired_csv, discrete_cols)
        
        num_rows_to_generate = len(df_repaired) if len(df_repaired) > 0 else 1000
        ge.generate_synthetic_data(num_rows=num_rows_to_generate, output_csv=synthetic_csv)

        print("--- 3. Running Evaluation ---")
        results = evaluation_engine.evaluate_synthetic_data(repaired_csv, synthetic_csv)

        return {
            "status": "success",
            "evaluation": results,
            "download_url": "/api/download-synthetic"
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/download-synthetic")
async def download_synthetic():
    file_path = "data/synthetic_transactions.csv"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename="synthetic_transactions.csv", media_type='text/csv')
    return {"error": "File not found"}

@app.get("/api/download-repaired")
async def download_repaired():
    file_path = "data/repaired_transactions.csv"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename="repaired_transactions.csv", media_type='text/csv')
    return {"error": "File not found"}

@app.get("/api/download-cleaned")
async def download_cleaned():
    file_path = "data/cleaned_transactions.csv"
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename="cleaned_transactions.csv", media_type='text/csv')
    return {"error": "File not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
